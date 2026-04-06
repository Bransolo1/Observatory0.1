"""Digest API routes."""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.auth.dependencies import get_current_org, get_db
from observatory.core.models.organization import Organization
from observatory.core.models.user import User
from observatory.output.digests.generator import DigestGenerator

logger = structlog.get_logger()
router = APIRouter(prefix="/digests", tags=["digests"])


@router.get("")
async def list_digests(
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """List all generated digests (returns empty list — digests are generated on demand)."""
    return []


@router.get("/latest")
async def get_latest_digest(
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Get the latest weekly digest."""
    user, org, role = auth
    try:
        generator = DigestGenerator(db=db, org_id=org.id)
        digest = await generator.generate_weekly_digest()
        return digest
    except Exception as e:
        logger.error("digest_latest_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate digest")


@router.post("/generate")
async def generate_digest(
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Generate a new weekly digest."""
    user, org, role = auth
    try:
        generator = DigestGenerator(db=db, org_id=org.id)
        digest = await generator.generate_weekly_digest()
        return digest
    except Exception as e:
        logger.error("digest_generate_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate digest")
