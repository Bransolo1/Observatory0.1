"""Celery tasks for knowledge base document processing."""

import uuid

import structlog
from celery import shared_task
from sqlalchemy import select

from observatory.core.database import async_session_factory

logger = structlog.get_logger()


@shared_task(name="observatory.ingestion.knowledge.tasks.process_document")
def process_document(document_id: str, org_id: str) -> dict:
    """Process an uploaded document: extract text, chunk, embed, summarize."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_process_document_async(document_id, org_id))
    finally:
        loop.close()


async def _process_document_async(document_id: str, org_id: str) -> dict:
    from observatory.core.models.knowledge import KnowledgeDocument, KnowledgeChunk
    from observatory.ingestion.knowledge.processors import (
        extract_text,
        chunk_text,
        generate_document_summary,
    )
    from observatory.core.llm import get_llm_service

    llm = get_llm_service()
    doc_uuid = uuid.UUID(document_id)

    async with async_session_factory() as db:
        # Get document
        result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == doc_uuid)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            logger.error("document_not_found", document_id=document_id)
            return {"status": "error", "message": "Document not found"}

        try:
            # Update status to processing
            doc.status = "processing"
            await db.commit()

            # Read file content
            # For now, we store file_bytes in metadata; in production this would be MinIO/S3
            file_bytes = doc.metadata_.get("file_bytes_b64")
            if file_bytes:
                import base64
                file_bytes = base64.b64decode(file_bytes)
            else:
                logger.error("no_file_content", document_id=document_id)
                doc.status = "failed"
                await db.commit()
                return {"status": "error", "message": "No file content found"}

            # Extract text
            pages = extract_text(file_bytes, doc.file_type)
            if not pages:
                doc.status = "failed"
                await db.commit()
                return {"status": "error", "message": "No text extracted"}

            logger.info(
                "text_extracted",
                document_id=document_id,
                pages=len(pages),
            )

            # Chunk text
            chunks = chunk_text(pages, max_tokens=512, overlap_tokens=50)

            # Generate embeddings for each chunk
            for chunk in chunks:
                embedding = await llm.embed(chunk["text"])
                chunk["embedding"] = embedding

            # Create chunk records
            for chunk in chunks:
                db_chunk = KnowledgeChunk(
                    document_id=doc_uuid,
                    chunk_index=chunk["chunk_index"],
                    text=chunk["text"],
                    section=chunk.get("section"),
                    page_number=chunk.get("page_number"),
                    token_count=chunk.get("token_count", 0),
                    embedding=chunk["embedding"],
                )
                db.add(db_chunk)

            # Generate summary
            summary_data = await generate_document_summary(chunks, doc.title)

            doc.summary = summary_data["summary"]
            doc.key_findings = {
                "findings": summary_data["key_findings"],
                "topics": summary_data.get("topics", []),
            }
            doc.chunk_count = len(chunks)
            doc.status = "indexed"

            # Remove raw bytes from metadata to save space
            if "file_bytes_b64" in doc.metadata_:
                meta = dict(doc.metadata_)
                del meta["file_bytes_b64"]
                doc.metadata_ = meta

            await db.commit()

            logger.info(
                "document_processed",
                document_id=document_id,
                chunks=len(chunks),
                summary_length=len(summary_data["summary"]),
            )

            return {
                "status": "success",
                "document_id": document_id,
                "chunks_created": len(chunks),
                "summary": summary_data["summary"][:200],
            }

        except Exception as e:
            logger.error("document_processing_error", document_id=document_id, error=str(e))
            doc.status = "failed"
            await db.commit()
            return {"status": "error", "message": str(e)}
