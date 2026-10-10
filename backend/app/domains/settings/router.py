"""设置路由。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.projects.schemas import APIModel
from app.domains.settings import service
from app.domains.settings.service import SettingsError

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsRead(APIModel):
    interventionMode: str


class SettingsUpdate(APIModel):
    interventionMode: str = Field(pattern="^(quiet|adaptive|guided)$", min_length=1)


@router.get("", response_model=SettingsRead, summary="当前用户 AI 偏好")
def read_settings(db: Session = Depends(get_db)) -> SettingsRead:
    settings = service.get_settings(db)
    return SettingsRead(interventionMode=settings.intervention_mode)


@router.patch("", response_model=SettingsRead, summary="更新介入模式")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsRead:
    try:
        settings = service.update_mode(db, payload.interventionMode)
    except SettingsError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return SettingsRead(interventionMode=settings.intervention_mode)
