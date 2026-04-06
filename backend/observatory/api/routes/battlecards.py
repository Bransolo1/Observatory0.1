"""Battlecard API routes."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.auth.dependencies import get_current_org, get_db
from observatory.core.models.organization import Organization
from observatory.core.models.user import User
from observatory.output.battlecards.generator import BattlecardGenerator

logger = structlog.get_logger()
router = APIRouter(prefix="/battlecards", tags=["battlecards"])


@router.get("/{competitor_id}")
async def get_battlecard(
    competitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Get or generate a battlecard for a competitor."""
    user, org, role = auth
    try:
        generator = BattlecardGenerator(db=db, org_id=org.id)
        battlecard = await generator.generate(competitor_id)
        return battlecard
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("battlecard_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate battlecard")


@router.post("/{competitor_id}")
async def generate_battlecard(
    competitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: tuple[User, Organization, str] = Depends(get_current_org),
):
    """Generate a fresh battlecard for a competitor."""
    user, org, role = auth
    try:
        generator = BattlecardGenerator(db=db, org_id=org.id)
        battlecard = await generator.generate(competitor_id)
        return battlecard
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("battlecard_generate_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate battlecard")
