import uuid

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    org_name: str | None = None


class TokenPayload(BaseModel):
    sub: str  # user_id
    org_id: str | None = None
    role: str | None = None
    exp: int


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    org_id: uuid.UUID | None = None
    role: str | None = None
