"""Base connector interface — all data source connectors implement this contract."""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SyncResult:
    """Result of a connector sync operation."""

    records_fetched: int = 0
    records_created: int = 0
    records_updated: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class ConnectionStatus:
    connected: bool
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Interface that all data source connectors must implement."""

    def __init__(self, org_id: uuid.UUID, credentials: dict[str, Any], config: dict[str, Any]):
        self.org_id = org_id
        self.credentials = credentials
        self.config = config

    @abstractmethod
    async def authenticate(self) -> ConnectionStatus:
        """Validate credentials and establish connection."""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """Quick health check."""
        ...

    @abstractmethod
    async def sync(self, since: datetime | None = None) -> SyncResult:
        """Fetch new/updated data since the given timestamp."""
        ...

    @abstractmethod
    async def get_schema(self) -> dict[str, Any]:
        """Describe the data this connector provides."""
        ...
