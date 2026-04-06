import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.auth.dependencies import get_db, require_role
from observatory.core.models.insight import (
    ExperimentRecommendation,
    PriorityScore,
    RecommendationOutcome,
)
from observatory.core.models.organization import Organization
from observatory.core.models.user import User

router = APIRouter()


class PriorityScoreResponse(BaseModel):
    id: uuid.UUID
    product_area: str
    score: float
    rank: int
    friction_score: float
    voc_score: float
    competitive_score: float
    telemetry_score: float
    strategic_score: float
    recommendation: str | None
    scored_at: datetime


class ExperimentResponse(BaseModel):
    id: uuid.UUID
    title: str
    hypothesis: str
    product_area: str | None
    expected_impact: str
    expected_revenue_impact: float | None
    confidence: float
    effort_estimate: str
    variants: dict
    status: str
    rank: int
    generated_at: datetime


class RecordOutcomeRequest(BaseModel):
    recommendation_id: uuid.UUID
    recommendation_type: str
    target_metric: str
    baseline_value: float
    outcome_value: float | None = None
    outcome: str | None = None
    revenue_impact: float | None = None
    notes: str | None = None


@router.get("/priorities", response_model=list[PriorityScoreResponse])
async def list_priority_scores(
    limit: int = Query(default=20, le=100),
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst", "viewer"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    result = await db.execute(
        select(PriorityScore)
        .where(PriorityScore.org_id == org.id)
        .order_by(PriorityScore.rank)
        .limit(limit)
    )
    scores = result.scalars().all()
    return [
        PriorityScoreResponse(
            id=s.id,
            product_area=s.product_area,
            score=s.score,
            rank=s.rank,
            friction_score=s.friction_score,
            voc_score=s.voc_score,
            competitive_score=s.competitive_score,
            telemetry_score=s.telemetry_score,
            strategic_score=s.strategic_score,
            recommendation=s.recommendation,
            scored_at=s.scored_at,
        )
        for s in scores
    ]


@router.get("/experiments", response_model=list[ExperimentResponse])
async def list_experiments(
    status_filter: str | None = Query(default="proposed", alias="status"),
    limit: int = Query(default=10, le=50),
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst", "viewer"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    query = (
        select(ExperimentRecommendation)
        .where(ExperimentRecommendation.org_id == org.id)
        .order_by(ExperimentRecommendation.rank)
        .limit(limit)
    )
    if status_filter:
        query = query.where(ExperimentRecommendation.status == status_filter)

    result = await db.execute(query)
    experiments = result.scalars().all()
    return [
        ExperimentResponse(
            id=e.id,
            title=e.title,
            hypothesis=e.hypothesis,
            product_area=e.product_area,
            expected_impact=e.expected_impact,
            expected_revenue_impact=e.expected_revenue_impact,
            confidence=e.confidence,
            effort_estimate=e.effort_estimate,
            variants=e.variants,
            status=e.status,
            rank=e.rank,
            generated_at=e.generated_at,
        )
        for e in experiments
    ]


@router.post("/outcomes", status_code=201)
async def record_outcome(
    body: RecordOutcomeRequest,
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    outcome = RecommendationOutcome(
        org_id=org.id,
        recommendation_id=body.recommendation_id,
        recommendation_type=body.recommendation_type,
        target_metric=body.target_metric,
        baseline_value=body.baseline_value,
        outcome_value=body.outcome_value,
        outcome=body.outcome,
        revenue_impact=body.revenue_impact,
        notes=body.notes,
    )
    db.add(outcome)
    await db.commit()
    return {"id": outcome.id, "status": "recorded"}
