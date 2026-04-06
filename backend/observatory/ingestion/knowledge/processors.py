"""Document processors for knowledge base ingestion — PDF, DOCX, PPTX."""

import io
import uuid
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# --- Text Extraction ---

def extract_text_from_pdf(file_bytes: bytes) -> list[dict[str, Any]]:
    """Extract text from PDF, returning pages with metadata."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({
                "text": text.strip(),
                "page_number": i + 1,
                "section": None,
            })
    return pages


def extract_text_from_docx(file_bytes: bytes) -> list[dict[str, Any]]:
    """Extract text from DOCX, preserving heading structure."""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    sections: list[dict[str, Any]] = []
    current_section = None
    current_text: list[str] = []

    for para in doc.paragraphs:
        if para.style and para.style.name and para.style.name.startswith("Heading"):
            # Save previous section
            if current_text:
                sections.append({
                    "text": "\n".join(current_text).strip(),
                    "page_number": None,
                    "section": current_section,
                })
            current_section = para.text.strip()
            current_text = []
        elif para.text.strip():
            current_text.append(para.text.strip())

    # Final section
    if current_text:
        sections.append({
            "text": "\n".join(current_text).strip(),
            "page_number": None,
            "section": current_section,
        })

    return sections


def extract_text_from_pptx(file_bytes: bytes) -> list[dict[str, Any]]:
    """Extract text from PPTX slides."""
    from pptx import Presentation

    prs = Presentation(io.BytesIO(file_bytes))
    slides = []
    for i, slide in enumerate(prs.slides):
        texts = []
        title = None
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    if shape == slide.shapes.title:
                        title = text
                    else:
                        texts.append(text)
        if texts or title:
            slides.append({
                "text": "\n".join(texts).strip(),
                "page_number": i + 1,
                "section": title,
            })
    return slides


def extract_text(file_bytes: bytes, file_type: str) -> list[dict[str, Any]]:
    """Route to the correct extractor based on file type."""
    extractors = {
        "pdf": extract_text_from_pdf,
        "docx": extract_text_from_docx,
        "pptx": extract_text_from_pptx,
    }
    extractor = extractors.get(file_type)
    if not extractor:
        raise ValueError(f"Unsupported file type: {file_type}")
    return extractor(file_bytes)


# --- Semantic Chunking ---

def chunk_text(
    pages: list[dict[str, Any]],
    max_tokens: int = 512,
    overlap_tokens: int = 50,
) -> list[dict[str, Any]]:
    """Split extracted pages/sections into semantic chunks with overlap.

    Uses a simple word-based approximation: 1 token ≈ 0.75 words.
    """
    chunks: list[dict[str, Any]] = []
    chunk_index = 0

    for page in pages:
        text = page["text"]
        words = text.split()
        max_words = int(max_tokens * 0.75)
        overlap_words = int(overlap_tokens * 0.75)

        if len(words) <= max_words:
            chunks.append({
                "chunk_index": chunk_index,
                "text": text,
                "section": page.get("section"),
                "page_number": page.get("page_number"),
                "token_count": int(len(words) / 0.75),
            })
            chunk_index += 1
        else:
            start = 0
            while start < len(words):
                end = min(start + max_words, len(words))
                chunk_words = words[start:end]
                chunk_text_str = " ".join(chunk_words)
                chunks.append({
                    "chunk_index": chunk_index,
                    "text": chunk_text_str,
                    "section": page.get("section"),
                    "page_number": page.get("page_number"),
                    "token_count": int(len(chunk_words) / 0.75),
                })
                chunk_index += 1
                start = end - overlap_words
                if start >= len(words):
                    break

    return chunks


# --- Document Summary ---

async def generate_document_summary(
    chunks: list[dict[str, Any]], title: str
) -> dict[str, Any]:
    """Use LLM to generate document summary and extract key findings."""
    from observatory.core.llm import get_llm_service

    llm = get_llm_service()

    # Use first N chunks (up to ~4000 tokens) for summary
    sample_text = ""
    for chunk in chunks[:10]:
        sample_text += chunk["text"] + "\n\n"
        if len(sample_text) > 6000:
            break

    prompt = (
        f"Summarize the following document titled '{title}'.\n\n"
        f"DOCUMENT CONTENT:\n{sample_text[:6000]}\n\n"
        "Provide your response in this exact format:\n"
        "SUMMARY: <2-3 sentence summary>\n"
        "KEY_FINDINGS:\n"
        "- <finding 1>\n"
        "- <finding 2>\n"
        "- <finding 3>\n"
        "- <finding 4>\n"
        "- <finding 5>\n"
        "TOPICS: <comma-separated list of topics covered>"
    )

    try:
        response = await llm.complete(prompt=prompt, tier="DEFAULT")

        # Parse response
        summary = ""
        findings = []
        topics = []

        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("SUMMARY:"):
                summary = line.replace("SUMMARY:", "").strip()
            elif line.startswith("- "):
                findings.append(line[2:].strip())
            elif line.startswith("TOPICS:"):
                topics = [t.strip() for t in line.replace("TOPICS:", "").split(",")]

        return {
            "summary": summary or response[:500],
            "key_findings": findings[:10],
            "topics": topics[:10],
        }
    except Exception as e:
        logger.error("document_summary_error", error=str(e))
        return {
            "summary": f"Summary generation failed: {str(e)}",
            "key_findings": [],
            "topics": [],
        }
