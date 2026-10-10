"""ProjectWeave 后端入口。

启动：uvicorn app.main:app --reload --port 8000
接口文档：http://localhost:8000/docs
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.auto_migrate:
        from app.core.db import SessionLocal
        from app.core.migrate import run_migrations
        from app.domains.concepts.service import ensure_seed_concepts

        run_migrations()
        # 知识图种子：空表时写入（幂等）。
        db = SessionLocal()
        try:
            ensure_seed_concepts(db)
        finally:
            db.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        description="AI 自适应项目式编程教学平台（当前为 P0 阶段：项目管理基础）",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
