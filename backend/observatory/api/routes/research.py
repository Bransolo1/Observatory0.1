"""Research pipeline API routes — briefs, commissions, and knowledge gap detection."""

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.auth.dependencies import get_current_org, get_db, require_role
from observatory.core.models.organization import Organization
from observatory.core.models.research import ResearchBrief, ResearchCommission
from observatory.core.models.user import User

logger = structlog.get_logger()
router = APIRouter(prefix="/research", tags=["research"])


# --- Schemas ---

class BriefCreateRequest(BaseModel):
    title: str
    knowledge_gap: str
    methodology: str = "survey"
    product_area: Optional[str] = None
    priority: str = "medium"


class BriefUpdateRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None


class CommissionCreateRequest(BaseModel):
    brief_id: str
    provider: str = "askable"


# --- Brief Endpoints ---

@router.get("/briefs")
async def list_briefs(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """List research briefs for the organization."""
    user, org, role = auth
    query = select(ResearchBrief).where(ResearchBrief.org_id == org.id)
    if status:
        query = query.where(ResearchBrief.status == status)
    if priority:
        query = query.where(ResearchBrief.priority == priority)
    query = query.order_by(ResearchBrief.created_at.desc())

    result = await db.execute(query)
    briefs = result.scalars().all()
    return [
        {
            "id": str(b.id),
            "title": b.title,
            "knowledge_gap": b.knowledge_gap,
            "objective": b.objective,
            "methodology": b.methodology,
            "sample_description": b.sample_description,
            "sample_size": b.sample_size,
            "estimated_cost": b.estimated_cost,
            "estimated_cost_currency": b.estimated_cost_currency,
            "expected_value": b.expected_value,
            "product_area": b.product_area,
            "priority": b.priority,
            "status": b.status,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in briefs
    ]


@router.post("/briefs")
async def create_brief(
    req: BriefCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Create a new research brief."""
    user, org, role = auth
    brief = ResearchBrief(
        org_id=org.id,
        title=req.title,
        knowledge_gap=req.knowledge_gap,
        methodology=req.methodology,
        product_area=req.product_area,
        priority=req.priority,
        status="draft",
    )
    db.add(brief)
    await db.commit()
    await db.refresh(brief)
    return {"id": str(brief.id), "title": brief.title, "status": brief.status}


@router.get("/briefs/{brief_id}")
async def get_brief(
    brief_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Get a research brief by ID."""
    user, org, role = auth
    result = await db.execute(
        select(ResearchBrief).where(
            ResearchBrief.id == brief_id,
            ResearchBrief.org_id == org.id,
        )
    )
    brief = result.scalar_one_or_none()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")

    return {
        "id": str(brief.id),
        "title": brief.title,
        "knowledge_gap": brief.knowledge_gap,
        "objective": brief.objective,
        "methodology": brief.methodology,
        "sample_description": brief.sample_description,
        "sample_size": brief.sample_size,
        "estimated_cost": brief.estimated_cost,
        "estimated_cost_currency": brief.estimated_cost_currency,
        "expected_value": brief.expected_value,
        "expected_value_rationale": brief.expected_value_rationale,
        "product_area": brief.product_area,
        "priority": brief.priority,
        "status": brief.status,
        "evidence_sources": brief.evidence_sources,
        "reviewed_by": str(brief.reviewed_by) if brief.reviewed_by else None,
        "reviewed_at": brief.reviewed_at.isoformat() if brief.reviewed_at else None,
        "created_at": brief.created_at.isoformat() if brief.created_at else None,
    }


@router.patch("/briefs/{brief_id}")
async def update_brief(
    brief_id: uuid.UUID,
    req: BriefUpdateRequest,
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Update a research brief status or priority."""
    user, org, role = auth
    result = await db.execute(
        select(ResearchBrief).where(
            ResearchBrief.id == brief_id,
            ResearchBrief.org_id == org.id,
        )
    )
    brief = result.scalar_one_or_none()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")

    if req.status:
        valid_transitions = {
            "draft": ["pending_review"],
            "pending_review": ["approved", "rejected"],
            "approved": ["commissioned"],
            "commissioned": ["completed"],
        }
        allowed = valid_transitions.get(brief.status, [])
        if req.status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from '{brief.status}' to '{req.status}'. Allowed: {allowed}",
            )
        brief.status = req.status
        if req.status in ("approved", "rejected"):
            from datetime import datetime, timezone
            brief.reviewed_by = user.id
            brief.reviewed_at = datetime.now(timezone.utc)

    if req.priority:
        brief.priority = req.priority

    await db.commit()
    return {"id": str(brief.id), "status": brief.status, "priority": brief.priority}


# --- Knowledge Gap Detection ---

@router.post("/detect-gaps")
async def detect_knowledge_gaps(
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Detect knowledge gaps and optionally generate research briefs."""
    user, org, role = auth
    from observatory.ingestion.research.gap_detector import KnowledgeGapDetector

    detector = KnowledgeGapDetector(db=db, org_id=org.id)
    gaps = await detector.detect_gaps()
    return {"gaps": gaps, "count": len(gaps)}


@router.post("/generate-briefs")
async def generate_briefs_from_gaps(
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Detect gaps and auto-generate research briefs."""
    user, org, role = auth
    from observatory.ingestion.research.gap_detector import KnowledgeGapDetector
    from observatory.output.briefs.generator import ResearchBriefGenerator

    detector = KnowledgeGapDetector(db=db, org_id=org.id)
    gaps = await detector.detect_gaps()

    generator = ResearchBriefGenerator(db=db, org_id=org.id)
    briefs = await generator.generate_briefs_from_gaps(gaps)

    return {
        "gaps_detected": len(gaps),
        "briefs_generated": len(briefs),
        "brief_ids": [str(b.id) for b in briefs],
    }


# --- Commission Endpoints ---

@router.post("/commissions")
async def create_commission(
    req: CommissionCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Commission a research brief to a provider."""
    user, org, role = auth
    brief_uuid = uuid.UUID(req.brief_id)

    result = await db.execute(
        select(ResearchBrief).where(
            ResearchBrief.id == brief_uuid,
            ResearchBrief.org_id == org.id,
        )
    )
    brief = result.scalar_one_or_none()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")
    if brief.status != "approved":
        raise HTTPException(status_code=400, detail="Brief must be approved before commissioning")

    from datetime import datetime, timezone
    commission = ResearchCommission(
        org_id=org.id,
        brief_id=brief_uuid,
        provider=req.provider,
        status="pending",
        commissioned_at=datetime.now(timezone.utc),
    )
    db.add(commission)
    brief.status = "commissioned"
    await db.commit()
    await db.refresh(commission)

    return {
        "id": str(commission.id),
        "brief_id": str(commission.brief_id),
        "provider": commission.provider,
        "status": commission.status,
    }


@router.get("/commissions")
async def list_commissions(
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """List all research commissions."""
    user, org, role = auth
    result = await db.execute(
        select(ResearchCommission)
        .where(ResearchCommission.org_id == org.id)
        .order_by(ResearchCommission.commissioned_at.desc())
    )
    commissions = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "brief_id": str(c.brief_id),
            "provider": c.provider,
            "status": c.status,
            "actual_cost": c.actual_cost,
            "commissioned_at": c.commissioned_at.isoformat() if c.commissioned_at else None,
            "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        }
        for c in commissions
    ]
