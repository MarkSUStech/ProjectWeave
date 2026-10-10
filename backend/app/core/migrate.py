"""在应用启动时执行数据库迁移（仅当 PW_AUTO_MIGRATE=true）。"""

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_migrations() -> None:
    ini_path = BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini_path))
    # alembic.ini 中的相对路径以 backend/ 为基准解析。
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")
