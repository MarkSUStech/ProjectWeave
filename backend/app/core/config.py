"""应用配置。

所有配置通过环境变量注入，前缀 PW_，支持 .env 文件。
禁止在代码中硬编码密钥或连接串。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ProjectWeave API"
    # 开发环境默认使用本地 SQLite；生产/联调通过 PW_DATABASE_URL 切换 PostgreSQL。
    database_url: str = "sqlite:///./projectweave.db"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    # 启动时自动执行 alembic upgrade head，方便本地开发首跑。
    auto_migrate: bool = True

    # --- AI Provider（Tutor Engine，P2.5）---
    # disabled（默认，无 Key 明确降级）| deepseek | mock（仅测试）
    ai_provider: str = "disabled"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # 单次教学回合的生成超时（秒）
    ai_timeout_seconds: float = 45.0


settings = Settings()
