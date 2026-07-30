import io
import logging
import math
import uuid
from types import SimpleNamespace
from typing import Any
import urllib3
import requests

from app.services.pdf_reader import extract_text_from_any_pdf

# Suppress insecure request warnings due to verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover - fallback for light environments
    class RecursiveCharacterTextSplitter:
        def __init__(self, chunk_size: int = 600, chunk_overlap: int = 100) -> None:
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap

        def split_text(self, text: str) -> list[str]:
            if not text:
                return []
            chunks = []
            start = 0
            while start < len(text):
                end = min(start + self.chunk_size, len(text))
                chunk = text[start:end]
                chunks.append(chunk)
                start = end - self.chunk_overlap
            return chunks

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - fallback for light environments
    class PdfReader:
        def __init__(self, stream: io.BytesIO) -> None:
            self.stream = stream

        @property
        def pages(self):
            return []

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - fallback for light environments
    SentenceTransformer = None

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
except ImportError:  # pragma: no cover - fallback for light environments
    QdrantClient = None
    Distance = None
    PointStruct = None
    VectorParams = None

from app.core.singleton import singleton

logger = logging.getLogger("rag")


class _SimpleEncoder:
    def encode(self, texts: Any) -> list[list[float]]:
        if isinstance(texts, str):
            texts = [texts]
        return [[float(sum(ord(ch) for ch in text.lower()) % 97) / 97.0 for _ in range(8)] for text in texts]


class _FallbackQdrantClient:
    def __init__(self) -> None:
        self.collections: dict[str, list[dict[str, Any]]] = {}

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, collection_name: str, vectors_config: Any, **_: Any) -> None:
        self.collections[collection_name] = []

    def upsert(self, collection_name: str, points: list[Any]) -> None:
        self.collections.setdefault(collection_name, []).extend(points)

    def query_points(self, collection_name: str, query: list[float], limit: int, with_payload: bool = True) -> Any:
        points = self.collections.get(collection_name, [])
        scored = []
        for point in points:
            score = self._cosine_similarity(query, point.vector)
            scored.append(SimpleNamespace(score=score, payload=point.payload))
        scored.sort(key=lambda item: item.score, reverse=True)
        return SimpleNamespace(points=scored[:limit])

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right))
        denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
        if denominator == 0:
            return 0.0
        return numerator / denominator


@singleton
class RagClient:
    def __init__(self) -> None:
        self.qdrant_client = QdrantClient(":memory:") if QdrantClient is not None else _FallbackQdrantClient()
        self.model_name = "sentence-transformers/all-MiniLM-L6-v2"
        self.encoder = SentenceTransformer(self.model_name) if SentenceTransformer is not None else _SimpleEncoder()
        self.vector_dimension = 8

    def _initialize_collection(self, collection_name: str) -> str:
        if not self.qdrant_client.collection_exists(collection_name):
            if VectorParams is not None and Distance is not None:
                self.qdrant_client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=self.vector_dimension, distance=Distance.COSINE),
                )
            else:
                self.qdrant_client.create_collection(collection_name=collection_name, vectors_config=None)
        return collection_name

    def save(self, collection_name: str, public_url: str, headers: dict=None) -> dict:
        self._initialize_collection(collection_name)

        try:
            resp = requests.get(public_url, timeout=60, verify=False)
            if resp.status_code != 200:
                raise Exception(f"Could not download PDF. Status: {resp.status_code}")
        except requests.exceptions.RequestException as exc:
            logger.error("Network transport error encountered while fetching PDF: %s", exc)
            raise

        try:
            full_text = extract_text_from_any_pdf(resp.content)
        except Exception as exc:
            logger.error("Failed to parse the download PDF binary stream: %s", exc)
            raise Exception(f"The download file could not be parsed as a PDF: {exc}") from exc

        if not full_text.strip():
            raise Exception("The PDF appears to be empty or unreadable.")

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=100)
        chunks = text_splitter.split_text(full_text)
        if not chunks:
            return {"status": "error", "message": "No plain text parsed from request"}

        embeddings = self.encoder.encode(chunks)
        points = []
        for chunk, vector in zip(chunks, embeddings):
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={"text": chunk},
                )
                if PointStruct is not None
                else SimpleNamespace(vector=vector, payload={"text": chunk})
            )

        self.qdrant_client.upsert(collection_name=collection_name, points=points)
        return {"status": "success", "chunks_count": len(chunks)}

    def query(self, collection_name: str, question: str, top_k: int = 5) -> dict:
        query_vector = self.encoder.encode(question)
        query_response = self.qdrant_client.query_points(
            collection_name=collection_name,
            query=query_vector[0] if isinstance(query_vector, list) and query_vector and isinstance(query_vector[0], list) else query_vector,
            limit=min(top_k, 5),
            with_payload=True,
        )

        return {
            "results": [
                {"text": hit.payload["text"], "score": hit.score}
                for hit in query_response.points
            ]
        }


rag_client = RagClient()