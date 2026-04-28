"""FastAPI app shell. Phase 2 = stub /health; Phase 3 adds /query and
/artifacts; Phase 4 (US2) replaces the stub /health with the real
multi-component check.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from discogs_agent.config import settings
from discogs_agent.observability.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.LOG_LEVEL)
    # Phase 2: skip validate_runtime so the test harness can boot
    # against a tmp DuckDB. Phase 4 will tighten this.
    logger.info("agent_starting", model_provider="openai", version=settings.AGENT_VERSION)
    yield
    logger.info("agent_stopping")


app = FastAPI(title="Discogs Conversational Analytics Agent", lifespan=_lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    """Phase 2 stub — replaced by the real multi-component check in US2."""
    return {"status": "ok"}


# /query and /artifacts routes are registered in api_query.py and
# imported into the app module here. Avoids a circular import where
# /query needs the graph builder and the graph builder needs the
# settings module.
def _register_routes() -> None:
    from discogs_agent import api_query  # noqa: F401  side-effect: registers routes


_register_routes()
