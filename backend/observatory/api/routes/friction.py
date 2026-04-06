import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.auth.dependencies import get_db, require_role
from observatory.core.models.organization import Organization
from observatory.core.models.telemetry import FrictionSignal
from observatory.core.models.user import User

router = APIRouter()


class FrictionSignalResponse(BaseModel):
    id: uuid.UUID
    signal_type: str
    severity: str
    product_area: str | None
    funnel_step: str | None
    current_rate: float
    baseline_rate: float
    deviation_score: float
    affected_users: int
    description: str | None
    evidence: dict
    status: str
    detected_at: datetime
    resolved_at: datetime | None


class FrictionListResponse(BaseModel):
    items: list[FrictionSignalResponse]
    total: int


@router.get("", response_model=FrictionListResponse)
async def list_friction_signals(
    severity: str | None = None,
    signal_status: str | None = Query(default="active", alias="status"),
    product_area: str | None = None,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst", "viewer"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    query = (
        select(FrictionSignal)
        .where(FrictionSignal.org_id == org.id)
        .order_by(desc(FrictionSignal.deviation_score))
    )

    if severity:
        query = query.where(FrictionSignal.severity == severity)
    if signal_status:
        query = query.where(FrictionSignal.status == signal_status)
    if product_area:
        query = query.where(FrictionSignal.product_area == product_area)

    result = await db.execute(query.limit(limit).offset(offset))
    items = result.scalars().all()

    return FrictionListResponse(
        items=[
            FrictionSignalResponse(
                id=f.id,
                signal_type=f.signal_type,
                severity=f.severity,
                product_area=f.product_area,
                funnel_step=f.funnel_step,
                current_rate=f.current_rate,
                baseline_rate=f.baseline_rate,
                deviation_score=f.deviation_score,
                affected_users=f.affected_users,
                description=f.description,
                evidence=f.evidence,
                status=f.status,
                detected_at=f.detected_at,
                resolved_at=f.resolved_at,
            )
            for f in items
        ],
        total=len(items),
    )


@router.patch("/{signal_id}/status")
async def update_friction_status(
    signal_id: uuid.UUID,
    new_status: str = Query(...),
    org_context: tuple[User, Organization, str] = Depends(
        require_role(["owner", "admin", "analyst"])
    ),
    db: AsyncSession = Depends(get_db),
):
    _, org, _ = org_context
    result = await db.execute(
        select(FrictionSignal).where(
            FrictionSignal.id == signal_id, FrictionSignal.org_id == org.id
        )
    )
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found")

    signal.status = new_status
    await db.commit()
    return {"id": signal.id, "status": signal.status}
