import base64
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.auth.dependencies import get_db, require_role
from observatory.core.models.knowledge import KnowledgeDocument
from observatory.core.models.organization import Organization
from observatory.core.models.user import User

router = APIRouter()


class KnowledgeDocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    doc_type: str
    file_type: str | None
    summary: str | None
    key_findings: dict
    chunk_count: int
    status: str


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


class SearchResult(BaseModel):
    document_id: uuid.UUID
    document_title: str
    chunk_text: str
    section: str | None
    relevance_score: float


@router.get("", response_model=list[KnowledgeDocumentResponse])
async def list_documents(
    doc_type: str | None = None,
    limit: int = Query(default=20, le=100),
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst", "viewer"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    query = (
        select(KnowledgeDocument)
        .where(KnowledgeDocument.org_id == org.id)
        .order_by(desc(KnowledgeDocument.created_at))
        .limit(limit)
    )
    if doc_type:
        query = query.where(KnowledgeDocument.doc_type == doc_type)

    result = await db.execute(query)
    docs = result.scalars().all()
    return [
        KnowledgeDocumentResponse(
            id=d.id,
            title=d.title,
            doc_type=d.doc_type,
            file_type=d.file_type,
            summary=d.summary,
            key_findings=d.key_findings,
            chunk_count=d.chunk_count,
            status=d.status,
        )
        for d in docs
    ]


@router.post("/upload", response_model=KnowledgeDocumentResponse, status_code=201)
async def upload_document(
    title: str,
    doc_type: str,
    file: UploadFile = File(...),
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context

    # Determine file type
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "unknown"

    file_bytes = await file.read()

    doc = KnowledgeDocument(
        org_id=org.id,
        title=title,
        doc_type=doc_type,
        file_type=file_ext,
        status="pending",
        metadata={"file_b64": base64.b64encode(file_bytes).decode("utf-8")},
    )
    db.add(doc)
    await db.commit()

    # Trigger async processing task (chunking, embedding, summarisation)
    from observatory.ingestion.knowledge.tasks import process_document
    process_document.delay(str(doc.id), str(org.id))

    return KnowledgeDocumentResponse(
        id=doc.id,
        title=doc.title,
        doc_type=doc.doc_type,
        file_type=doc.file_type,
        summary=doc.summary,
        key_findings=doc.key_findings,
        chunk_count=doc.chunk_count,
        status=doc.status,
    )


@router.post("/search", response_model=list[SearchResult])
async def search_knowledge(
    body: SearchRequest,
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst", "viewer"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context

    # Semantic search using pgvector
    from observatory.core.llm import get_llm_service
    from observatory.core.models.knowledge import KnowledgeChunk

    llm = get_llm_service()
    query_embedding = (await llm.embed([body.query]))[0]

    result = await db.execute(
        select(
            KnowledgeChunk,
            KnowledgeChunk.embedding.cosine_distance(query_embedding).label("distance"),
        )
        .where(KnowledgeChunk.org_id == org.id)
        .where(KnowledgeChunk.embedding.isnot(None))
        .order_by("distance")
        .limit(body.limit)
    )

    rows = result.all()

    # Fetch parent document titles
    doc_ids = {row[0].document_id for row in rows}
    if doc_ids:
        doc_result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id.in_(doc_ids))
        )
        doc_map = {d.id: d.title for d in doc_result.scalars().all()}
    else:
        doc_map = {}

    return [
        SearchResult(
            document_id=chunk.document_id,
            document_title=doc_map.get(chunk.document_id, "Unknown"),
            chunk_text=chunk.text,
            section=chunk.section,
            relevance_score=max(0, 1 - distance),
        )
        for chunk, distance in rows
    ]
