import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.auth.dependencies import get_db, require_role
from observatory.core.models.insight import Insight
from observatory.core.models.organization import Organization
from observatory.core.models.user import User

router = APIRouter()


class InsightResponse(BaseModel):
    id: uuid.UUID
    insight_type: str
    title: str
    summary: str
    detail: str
    product_area: str | None
    confidence: float
    source_count: int
    academic_perspective: str | None
    business_perspective: str | None
    ux_perspective: str | None
    status: str
    generated_at: datetime
    created_at: datetime


class InsightListResponse(BaseModel):
    items: list[InsightResponse]
    total: int


@router.get("", response_model=InsightListResponse)
async def list_insights(
    insight_type: str | None = None,
    product_area: str | None = None,
    status: str | None = Query(default="active"),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst", "viewer"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    query = select(Insight).where(Insight.org_id == org.id).order_by(desc(Insight.generated_at))

    if insight_type:
        query = query.where(Insight.insight_type == insight_type)
    if product_area:
        query = query.where(Insight.product_area == product_area)
    if status:
        query = query.where(Insight.status == status)

    result = await db.execute(query.limit(limit).offset(offset))
    items = result.scalars().all()

    count_result = await db.execute(
        select(Insight.id).where(Insight.org_id == org.id)
    )
    total = len(count_result.all())

    return InsightListResponse(
        items=[
            InsightResponse(
                id=i.id,
                insight_type=i.insight_type,
                title=i.title,
                summary=i.summary,
                detail=i.detail,
                product_area=i.product_area,
                confidence=i.confidence,
                source_count=i.source_count,
                academic_perspective=i.academic_perspective,
                business_perspective=i.business_perspective,
                ux_perspective=i.ux_perspective,
                status=i.status,
                generated_at=i.generated_at,
                created_at=i.created_at,
            )
            for i in items
        ],
        total=total,
    )


@router.get("/{insight_id}", response_model=InsightResponse)
async def get_insight(
    insight_id: uuid.UUID,
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst", "viewer"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    result = await db.execute(
        select(Insight).where(Insight.id == insight_id, Insight.org_id == org.id)
    )
    insight = result.scalar_one_or_none()
    if not insight:
        from fastapi import HTTPException, status as http_status

        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Insight not found")

    return InsightResponse(
        id=insight.id,
        insight_type=insight.insight_type,
        title=insight.title,
        summary=insight.summary,
        detail=insight.detail,
        product_area=insight.product_area,
        confidence=insight.confidence,
        source_count=insight.source_count,
        academic_perspective=insight.academic_perspective,
        business_perspective=insight.business_perspective,
        ux_perspective=insight.ux_perspective,
        status=insight.status,
        generated_at=insight.generated_at,
        created_at=insight.created_at,
    )
