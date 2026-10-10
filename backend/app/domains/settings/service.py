"""设置查询与更新（幂等 upsert）。"""

from sqlalchemy.orm import Session

from app.domains.settings.models import (
    DEFAULT_MODE,
    INTERVENTION_MODES,
    UserSettings,
    utcnow,
)


class SettingsError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        self.status = status
        super().__init__(message)


def get_settings(db: Session, owner_id: str = "dev-user") -> UserSettings:
    settings = db.get(UserSettings, owner_id)
    if settings is None:
        settings = UserSettings(owner_id=owner_id, intervention_mode=DEFAULT_MODE)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_mode(db: Session, mode: str, owner_id: str = "dev-user") -> UserSettings:
    if mode not in INTERVENTION_MODES:
        raise SettingsError(f"非法介入模式：{mode}（允许 quiet/adaptive/guided）")
    settings = get_settings(db, owner_id)
    settings.intervention_mode = mode
    settings.updated_at = utcnow()
    db.commit()
    db.refresh(settings)
    return settings
