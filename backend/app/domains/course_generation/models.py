"""课程生成持久化模型（P7.1）。

一次生成 = 一条流水线记录：URL → 仓库快照 → 分析 → 蓝图 → 验证 →（发布）。
阶段状态持久化（前端可轮询进度/错误/中间产物）；commit SHA 不可变记录
保证可复现；蓝图与验证结果以 JSON 落库可重读。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Uuid, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

# 流水线阶段（status 单调推进；失败记录 stage）
GEN_STATUSES = (
    "pending", "fetching", "analyzing", "scoping", "generating",
    "validating", "draft", "published", "failed",
)
STAGE_PROGRESS = {
    "pending": 0, "fetching": 10, "analyzing": 30, "scoping": 55,
    "generating": 75, "validating": 88, "draft": 100, "published": 100, "failed": 100,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CourseGeneration(Base):
    __tablename__ = "course_generations"
    __table_args__ = (Index("ix_course_generations_owner_created", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid := __import__("sqlalchemy").Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String(64), default="dev-user")

    # 输入
    source_url: Mapped[str] = mapped_column(String(500))
    # 流水线状态
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(JSONType, default=list)

    # 仓库快照（fetching 阶段产出；不可变 commit 锚定）
    repo_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    repo_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    license_info: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    repo_meta: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    # {tree: [{path,type,size}], files: {path: content}}（限额内文本文件）
    snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    # 分析产物（RepositoryAnalyzer Agent 输出，含证据分级）
    analysis: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    analysis_tool_calls: Mapped[list] = mapped_column(JSONType, default=list)

    # 蓝图（Generator 输出）与确定性验证
    blueprint: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    repair_rounds: Mapped[int] = mapped_column(Integer, default=0)

    # 发布（草稿→正式；不标记为已验证的可运行课程——D42）
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 发布时转换的任务规格（供 P7.2 项目实例化使用）
    published_tasks: Mapped[list | None] = mapped_column(JSONType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CourseRelease(Base):
    """已验证课程的不可变版本（P7.2，D42）。

    一个 Blueprint（generation）可多次生成课程内容产生不同 release；
    release ready 后冻结。参考实现存在受保护列，普通 API 永不下发。
    """

    __tablename__ = "course_releases"
    __table_args__ = (Index("ix_course_releases_gen", "generation_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    generation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("course_generations.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str] = mapped_column(String(64), default="dev-user")
    release_version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="generating", index=True)
    language: Mapped[str] = mapped_column(String(20), default="python")
    course_title: Mapped[str] = mapped_column(String(300), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_task: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    blueprint_snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)
    artifacts: Mapped[list] = mapped_column(JSONType, default=list)
    reference_store: Mapped[dict] = mapped_column(JSONType, default=dict)
    verification_report: Mapped[dict] = mapped_column(JSONType, default=dict)

    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CourseCheckpoint(Base):
    """课程生成检查点（P8.2.1，D46）：每个任务**真实验证通过**后固化。

    内容含累积参考快照与测试注册表——服务端受保护（绝不进入普通 API）。
    resume 时按（generation、blueprint 哈希、协议版本）兼容复用。
    """

    __tablename__ = "course_checkpoints"
    __table_args__ = (
        Index("ix_course_checkpoints_gen_seq", "generation_id", "task_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    generation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("course_generations.id", ondelete="CASCADE"), index=True
    )
    release_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("course_releases.id", ondelete="CASCADE"), index=True, nullable=True
    )
    task_seq: Mapped[int] = mapped_column(Integer)             # 任务序（0 基）
    task_id: Mapped[str] = mapped_column(String(60))
    blueprint_hash: Mapped[str] = mapped_column(String(32))    # 兼容性校验
    protocol_version: Mapped[str] = mapped_column(String(40))
    sandbox_image: Mapped[str] = mapped_column(String(120), default="")
    source_commit: Mapped[str] = mapped_column(String(64), default="")

    # 已验证累积参考工程（源+测试）与测试注册表（受保护，不下发）
    snapshot_files: Mapped[dict] = mapped_column(JSONType, default=dict)
    snapshot_hash: Mapped[str] = mapped_column(String(32), default="")
    # P8.2.2：任务规格哈希（蓝图变更/拆分后默认不复用）与前序快照链
    task_spec_hash: Mapped[str] = mapped_column(String(32), default="")
    prev_snapshot_hash: Mapped[str] = mapped_column(String(32), default="")
    test_registry: Mapped[list] = mapped_column(JSONType, default=list)
    artifact: Mapped[dict] = mapped_column(JSONType, default=dict)        # 公开材料
    reference_delta: Mapped[list] = mapped_column(JSONType, default=list)  # 受保护参考实现
    verification_evidence: Mapped[list] = mapped_column(JSONType, default=list)
    diagnostics: Mapped[dict] = mapped_column(JSONType, default=dict)     # 修复轮/token 等度量

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GenerationJob(Base):
    """课程生成 Job 持久化（P8.2.1，D46）：可恢复的长任务状态。

    同一 release 同时至多一个 worker（lease_token + 心跳）；
    服务重启后 interrupted 任务等待显式 resume。
    """

    __tablename__ = "generation_jobs"
    __table_args__ = (
        Index("ix_generation_jobs_release", "release_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("course_releases.id", ondelete="CASCADE"), index=True, nullable=True
    )
    generation_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    # running | completed | failed | interrupted | cancelled
    current_task: Mapped[str | None] = mapped_column(String(60), nullable=True)
    completed_task_ids: Mapped[list] = mapped_column(JSONType, default=list)
    reused_task_ids: Mapped[list] = mapped_column(JSONType, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    diagnostics: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
