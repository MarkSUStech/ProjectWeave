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

    # --- 远程执行沙箱（P4.2b，D32）---
    # 总开关：关闭时创建执行返回 503（不伪造成功）。
    execution_enabled: bool = True
    # 单次执行超时上限（毫秒）；请求值超过则 422。
    execution_max_timeout_ms: int = 30000
    # 同时运行的沙箱数上限（超出排队）。
    execution_max_concurrent: int = 2
    # 单次执行文件数 / 总字节数 / stdin 上限。
    execution_max_files: int = 200
    execution_max_total_bytes: int = 4 * 1024 * 1024
    execution_max_stdin_chars: int = 64 * 1024
    # stdout/stderr 各自保留上限（超出截断并标记）。
    execution_output_max_chars: int = 256 * 1024
    # 沙箱资源限制。
    execution_memory_mb: int = 512
    execution_cpus: float = 1.0
    execution_pids_limit: int = 128


settings = Settings()
