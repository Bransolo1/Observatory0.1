import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.auth.dependencies import get_db, require_role
from observatory.core.models.competitor import CompetitorChange, CompetitorProfile
from observatory.core.models.organization import Organization
from observatory.core.models.user import User

router = APIRouter()


class CompetitorResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    website_url: str | None
    description: str | None
    is_active: bool


class CompetitorChangeResponse(BaseModel):
    id: uuid.UUID
    competitor_id: uuid.UUID
    change_type: str
    title: str
    description: str
    significance: str
    source_url: str | None
    detected_at: datetime


class CreateCompetitorRequest(BaseModel):
    name: str
    website_url: str | None = None
    description: str | None = None
    tracking_config: dict = {}


@router.get("", response_model=list[CompetitorResponse])
async def list_competitors(
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst", "viewer", "sales"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    result = await db.execute(
        select(CompetitorProfile)
        .where(CompetitorProfile.org_id == org.id, CompetitorProfile.is_active.is_(True))
        .order_by(CompetitorProfile.name)
    )
    competitors = result.scalars().all()
    return [
        CompetitorResponse(
            id=c.id,
            name=c.name,
            slug=c.slug,
            website_url=c.website_url,
            description=c.description,
            is_active=c.is_active,
        )
        for c in competitors
    ]


@router.post("", response_model=CompetitorResponse, status_code=status.HTTP_201_CREATED)
async def create_competitor(
    body: CreateCompetitorRequest,
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    slug = body.name.lower().replace(" ", "-").replace("_", "-")
    competitor = CompetitorProfile(
        org_id=org.id,
        name=body.name,
        slug=slug,
        website_url=body.website_url,
        description=body.description,
        tracking_config=body.tracking_config,
    )
    db.add(competitor)
    await db.commit()
    return CompetitorResponse(
        id=competitor.id,
        name=competitor.name,
        slug=competitor.slug,
        website_url=competitor.website_url,
        description=competitor.description,
        is_active=competitor.is_active,
    )


@router.get("/{competitor_id}/changes", response_model=list[CompetitorChangeResponse])
async def list_competitor_changes(
    competitor_id: uuid.UUID,
    change_type: str | None = None,
    limit: int = Query(default=20, le=100),
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst", "viewer", "sales"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    query = (
        select(CompetitorChange)
        .where(
            CompetitorChange.org_id == org.id,
            CompetitorChange.competitor_id == competitor_id,
        )
        .order_by(desc(CompetitorChange.detected_at))
        .limit(limit)
    )
    if change_type:
        query = query.where(CompetitorChange.change_type == change_type)

    result = await db.execute(query)
    changes = result.scalars().all()
    return [
        CompetitorChangeResponse(
            id=c.id,
            competitor_id=c.competitor_id,
            change_type=c.change_type,
            title=c.title,
            description=c.description,
            significance=c.significance,
            source_url=c.source_url,
            detected_at=c.detected_at,
        )
        for c in changes
    ]
