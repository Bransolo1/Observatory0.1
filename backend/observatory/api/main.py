from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from observatory.core.config import get_settings

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("observatory_starting", environment=settings.environment)
    yield
    logger.info("observatory_shutting_down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Consumer Intelligence Platform for Software-Led Organisations",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    from observatory.api.routes import auth, insights, friction, competitors, scores, knowledge, battlecards, digests, research

    app.include_router(auth.router, prefix=f"{settings.api_v1_prefix}/auth", tags=["auth"])
    app.include_router(
        insights.router, prefix=f"{settings.api_v1_prefix}/orgs/{{org_id}}/insights", tags=["insights"]
    )
    app.include_router(
        friction.router,
        prefix=f"{settings.api_v1_prefix}/orgs/{{org_id}}/friction-reports",
        tags=["friction"],
    )
    app.include_router(
        competitors.router,
        prefix=f"{settings.api_v1_prefix}/orgs/{{org_id}}/competitors",
        tags=["competitors"],
    )
    app.include_router(
        scores.router,
        prefix=f"{settings.api_v1_prefix}/orgs/{{org_id}}/scores",
        tags=["scores"],
    )
    app.include_router(
        knowledge.router,
        prefix=f"{settings.api_v1_prefix}/orgs/{{org_id}}/knowledge",
        tags=["knowledge"],
    )

    app.include_router(battlecards.router, prefix="/api/v1")
    app.include_router(digests.router, prefix="/api/v1")
    app.include_router(research.router, prefix="/api/v1")

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": "0.1.0"}

    return app


app = create_app()
