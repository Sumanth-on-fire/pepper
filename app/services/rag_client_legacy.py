import io
import os
import uuid
import shutil
import tarfile
import logging
import pathlib
import requests
from pathlib import Path
from pypdf import PdfReader
from app.core.singleton import singleton
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

logger = logging.getLogger('rag')
BASE_DIR = Path(__file__).resolve().parent.parent

# fastembed logs its own HF fallback as ERROR which is misleading.
# Silence it — our logger provides clean startup messages instead.
from loguru import logger as _loguru_logger
_loguru_logger.disable("fastembed")

# fastembed tries HuggingFace Hub before GCS even when a direct GCS URL exists.
# On networks that block huggingface.co this causes a connection error at startup.
# Patching download_files_from_huggingface to raise immediately forces fastembed
# straight to the GCS path. Do NOT set HF_HUB_OFFLINE — that blocks GCS too.
import fastembed.common.model_management as _fe_mm

def _hf_disabled(*args, **kwargs):
    raise EnvironmentError("HF Hub disabled.")

def _gcs_download(cls, model_name: str, source_url: str, cache_dir: str,
                  deprecated_tar_struct: bool = False,
                  local_files_only: bool = False) -> pathlib.Path:
    prefix    = "fast-" if deprecated_tar_struct else ""
    model_dir = pathlib.Path(cache_dir) / f"{prefix}{model_name.split('/')[-1]}"

    if model_dir.exists() and any(model_dir.iterdir()):
        logger.info("Embedding model loaded from cache.")
        return model_dir

    if local_files_only:
        raise ValueError(f"Model not in cache: {model_dir}")

    tmp_dir  = pathlib.Path(cache_dir) / "tmp"
    tar_path = pathlib.Path(cache_dir) / f"{prefix}{model_name.split('/')[-1]}.tar.gz"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading embedding model (~130 MB)...")
    resp = requests.get(source_url, stream=True, timeout=300)
    resp.raise_for_status()

    total, downloaded = int(resp.headers.get("content-length", 0)), 0
    with open(tar_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=65_536):
            if chunk:
                fh.write(chunk)
                downloaded += len(chunk)
                if total and downloaded % (10 * 1024 * 1024) < 65_536:
                    logger.info("  %.0f%%", downloaded * 100 / total)

    logger.info("Extracting model archive...")
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(tmp_dir)
    tar_path.unlink()

    extracted = sorted(p for p in tmp_dir.iterdir() if p.is_dir())
    if not extracted:
        raise RuntimeError(f"Nothing extracted. tmp contents: {list(tmp_dir.iterdir())}")
    extracted[0].rename(model_dir)
    logger.info("Embedding model ready.")
    return model_dir

_fe_mm.ModelManagement.download_files_from_huggingface = classmethod(_hf_disabled)
_fe_mm.ModelManagement.retrieve_model_gcs              = classmethod(_gcs_download)

from fastembed import TextEmbedding


@singleton
class RagClient:
    def __init__(self):
        cache_path = os.path.join(BASE_DIR, 'fastembed_cache')
        os.makedirs(cache_path, exist_ok=True)

        # Remove partial HF cache folders left by previous failed runs.
        for stale in pathlib.Path(cache_path).glob("models--*"):
            shutil.rmtree(stale, ignore_errors=True)

        self.qdrant_client    = QdrantClient(":memory:")
        self.model_name       = "BAAI/bge-small-en"
        self.vector_dimension = 384

        logger.info("Initializing embedding model: %s", self.model_name)
        self.embedding_model = TextEmbedding(
            model_name=self.model_name,
            cache_dir=cache_path,
        )
        logger.info("Embedding model loaded successfully.")

    def _initialize_collection(self, collection_name: str) -> str:
        if not self.qdrant_client.collection_exists(collection_name):
            self.qdrant_client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=self.vector_dimension, distance=Distance.COSINE),
            )
        return collection_name

    def _chunk_text(self, text: str, chunk_size: int = 400, chunk_overlap: int = 50) -> list[str]:
        words = text.split()
        chunks, step = [], chunk_size - chunk_overlap
        for i in range(0, len(words), step):
            chunk = " ".join(words[i : i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)
        return chunks

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self.embedding_model.embed(texts)]

    def save(self, collection_name: str, public_url: str, headers: dict) -> int:
        """Download a PDF from public_url, embed its text, and store in Qdrant."""
        self._initialize_collection(collection_name)

        try:
            resp = requests.get(public_url, headers=headers,timeout=60, verify=False)
            
            if resp.status_code != 200:
                raise Exception(f"Could not download PDF. Status: {resp.status_code}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Network transport error encountered while fetching PDF: {e}")
            raise

        try:
            full_text = "".join(
                page.extract_text() + "\n"
                for page in PdfReader(io.BytesIO(resp.content)).pages
                if page.extract_text()
            )
        except Exception as e:
            logger.error(f"Failed to parse the download PDF binary stream: {e}")
            raise Exception(f"The download file could not be parsed as a PDF: {e}")
        
        if not full_text.strip():
            raise Exception("The PDF appears to be empty or unreadable.")

        chunks  = self._chunk_text(full_text)
        vectors = self._embed(chunks)

        self.qdrant_client.upsert(
            collection_name=collection_name,
            wait=True,
            points=[
                PointStruct(
                    id=uuid.uuid4().int >> 64,
                    vector=vector,
                    payload={"source_url": public_url, "text": chunk},
                )
                for chunk, vector in zip(chunks, vectors)
            ],
        )
        logger.info("Upserted %d chunks into '%s'.", len(chunks), collection_name)
        return len(chunks)

    def query(self, collection_name: str, question: str, top_k: int = 5) -> list[dict]:
        """Return the top-k most relevant chunks for a question."""
        if not self.qdrant_client.collection_exists(collection_name):
            raise Exception(f"Collection '{collection_name}' does not exist yet.")

        # 1. FIXED: Use query_points instead of search for modern qdrant-client versions
        # 2. FIXED: Changed 'query_vector' to 'query' as required by query_points
        results = self.qdrant_client.query_points(
            collection_name=collection_name,
            query=self._embed([question])[0],
            limit=top_k,
            with_payload=True,
        ).points  # Make sure to append .points to get the iterable list of hits

        # 3. SAFE PARSING: Extract fields securely without throwing KeyErrors
        return [
            {
                "text": h.payload.get("text", "") if h.payload else "", 
                "source_url": h.payload.get("source_url", "") if h.payload else "", 
                "score": h.score
            }
            for h in results
        ]


rag_client = RagClient()