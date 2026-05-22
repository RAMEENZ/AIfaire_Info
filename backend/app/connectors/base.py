import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    def __init__(self) -> None:
        self.last_run: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self._logger = logging.getLogger(f"connector.{self.name}")

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def fetch(self) -> list[dict[str, Any]]:
        pass

    async def run(self) -> list[dict[str, Any]]:
        try:
            self._logger.info("Starting fetch")
            results = await self.fetch()
            self.last_run = datetime.utcnow()
            self.last_error = None
            self._logger.info("Fetched %d items", len(results))
            return results
        except Exception as exc:
            self.last_run = datetime.utcnow()
            self.last_error = str(exc)
            self._logger.error("Fetch failed: %s", exc, exc_info=True)
            return []
