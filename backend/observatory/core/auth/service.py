import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.config import get_settings
from observatory.core.models.organization import Organization, OrganizationMembership
from observatory.core.models.user import User


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )

    def create_access_token(
        self,
        user_id: uuid.UUID,
        org_id: uuid.UUID | None = None,
        role: str | None = None,
    ) -> str:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=self.settings.jwt_expiration_minutes
        )
        payload = {
            "sub": str(user_id),
            "exp": expire,
        }
        if org_id:
            payload["org_id"] = str(org_id)
        if role:
            payload["role"] = role
        return jwt.encode(payload, self.settings.jwt_secret, algorithm=self.settings.jwt_algorithm)

    async def register(
        self, email: str, name: str, password: str, org_name: str | None = None
    ) -> tuple[User, Organization | None]:
        user = User(
            email=email,
            name=name,
            hashed_password=self.hash_password(password),
        )
        self.db.add(user)
        await self.db.flush()

        org = None
        if org_name:
            slug = org_name.lower().replace(" ", "-").replace("_", "-")
            org = Organization(name=org_name, slug=slug)
            self.db.add(org)
            await self.db.flush()

            membership = OrganizationMembership(
                user_id=user.id, org_id=org.id, role="owner"
            )
            self.db.add(membership)

        await self.db.commit()
        return user, org

    async def authenticate(self, email: str, password: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not self.verify_password(password, user.hashed_password):
            return None
        return user

    async def get_user_org_role(
        self, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> str | None:
        result = await self.db.execute(
            select(OrganizationMembership.role).where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_user_orgs(
        self, user_id: uuid.UUID
    ) -> list[tuple[Organization, str]]:
        result = await self.db.execute(
            select(Organization, OrganizationMembership.role)
            .join(OrganizationMembership, Organization.id == OrganizationMembership.org_id)
            .where(OrganizationMembership.user_id == user_id)
        )
        return [(row[0], row[1]) for row in result.all()]
