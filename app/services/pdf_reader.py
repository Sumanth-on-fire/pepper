import io
import os
from PIL import Image
import pdfplumber
import pdf2image
import pytesseract

def extract_text_from_any_pdf(pdf_bytes: bytes) -> str:
    """
    Extracts text from a PDF bytes object. Tries digital layout parsing first,
    and automatically falls back to OCR if a page contains no extractable text.
    """
    full_text = []
    
    # Step 1: Open the PDF with pdfplumber for standard digital text extraction
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for index, page in enumerate(pdf.pages):
            page_text = page.extract_text()
            
            # If digital text exists, keep it
            if page_text and page_text.strip():
                full_text.append(page_text)
            else:
                # Step 2: Fallback to OCR if the page returns nothing (Scanned Image/Form)
                print(f"[OCR] Page {index + 1} has no digital text. Running OCR...")
                try:
                    # Convert only this specific page to a PIL Image object
                    images = pdf2image.convert_from_bytes(
                        pdf_bytes, 
                        first_page=index + 1, 
                        last_page=index + 1
                    )
                    if images:
                        ocr_text = pytesseract.image_to_string(images[0])
                        full_text.append(ocr_text)
                except Exception as e:
                    print(f"Failed to OCR page {index + 1}: {e}")
                    full_text.append(f"[Error: Page {index + 1} could not be read]")

    return "\n\n".join(full_text)