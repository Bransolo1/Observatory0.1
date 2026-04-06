import uuid
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.config import get_settings
from observatory.core.models.organization import Organization, OrganizationMembership
from observatory.core.models.user import User

security = HTTPBearer()


async def get_db():
    """Database session dependency — injected by the app lifespan."""
    from observatory.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_org(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Organization, str]:
    """Returns (user, organization, role) from a JWT that includes org_id."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        org_id = payload.get("org_id")
        if not user_id or not org_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token must include org_id",
            )
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    org_result = await db.execute(
        select(Organization).where(Organization.id == uuid.UUID(org_id))
    )
    org = org_result.scalar_one_or_none()
    if not org or not org.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    membership_result = await db.execute(
        select(OrganizationMembership.role).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.org_id == org.id,
        )
    )
    role = membership_result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member")

    return user, org, role


def require_role(allowed_roles: list[str]) -> Callable:
    """Dependency factory that checks the user has one of the allowed roles."""

    async def _check(
        org_context: tuple[User, Organization, str] = Depends(get_current_org),
    ) -> tuple[User, Organization, str]:
        user, org, role = org_context
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' not permitted. Requires: {allowed_roles}",
            )
        return user, org, role

    return _check
