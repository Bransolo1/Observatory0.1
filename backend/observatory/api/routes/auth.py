import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.auth.dependencies import get_current_user, get_db
from observatory.core.auth.schemas import AuthResponse, LoginRequest, RegisterRequest
from observatory.core.auth.service import AuthService
from observatory.core.models.user import User

router = APIRouter()


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    avatar_url: str | None


class OrgOption(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str


class SelectOrgRequest(BaseModel):
    org_id: uuid.UUID


@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    auth_service = AuthService(db)
    try:
        user, org = await auth_service.register(
            email=body.email,
            name=body.name,
            password=body.password,
            org_name=body.org_name,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration failed. Email may already exist.",
        )

    token = auth_service.create_access_token(
        user_id=user.id,
        org_id=org.id if org else None,
        role="owner" if org else None,
    )
    return AuthResponse(
        access_token=token,
        user_id=user.id,
        org_id=org.id if org else None,
        role="owner" if org else None,
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    auth_service = AuthService(db)
    user = await auth_service.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Get user's first org by default
    orgs = await auth_service.get_user_orgs(user.id)
    org, role = orgs[0] if orgs else (None, None)

    token = auth_service.create_access_token(
        user_id=user.id,
        org_id=org.id if org else None,
        role=role,
    )
    return AuthResponse(
        access_token=token,
        user_id=user.id,
        org_id=org.id if org else None,
        role=role,
    )


@router.post("/select-org", response_model=AuthResponse)
async def select_org(
    body: SelectOrgRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    auth_service = AuthService(db)
    role = await auth_service.get_user_org_role(user.id, body.org_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member")

    token = auth_service.create_access_token(
        user_id=user.id, org_id=body.org_id, role=role
    )
    return AuthResponse(
        access_token=token, user_id=user.id, org_id=body.org_id, role=role
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return UserResponse(
        id=user.id, email=user.email, name=user.name, avatar_url=user.avatar_url
    )


@router.get("/orgs", response_model=list[OrgOption])
async def get_my_orgs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    auth_service = AuthService(db)
    orgs = await auth_service.get_user_orgs(user.id)
    return [
        OrgOption(id=org.id, name=org.name, slug=org.slug, role=role)
        for org, role in orgs
    ]
