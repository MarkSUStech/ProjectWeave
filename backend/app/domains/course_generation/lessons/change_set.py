"""LessonChangeSet 契约（P8.2.1，D46）：C++ 课程增量生成协议。

模型只描述本任务需要 create/update/delete 的文件（每条提供完整新内容），
未修改文件由服务端从已验证快照继承——彻底消除全量再生成的一致性问题。
"""

from __future__ import annotations

import hashlib

from pydantic import Field, field_validator

from app.domains.projects.schemas import APIModel

# 生成器协议版本（Checkpoint 兼容性判定用；协议变更必须递增）
CHANGESET_PROTOCOL = "cpp-changeset-v1"


def content_hash(content: str) -> str:
    """文件内容短哈希（baseHash 校验与快照指纹）。"""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:12]


class FileChange(APIModel):
    """单个文件操作（内容为修改后的完整文件，非 diff hunk）。"""

    path: str = Field(min_length=1, max_length=300)
    operation: str = Field(pattern="^(create|update|delete)$")
    # update/delete 必须提供基线哈希（乐观锁：防止覆盖未预期的基线状态）
    base_hash: str | None = Field(default=None, max_length=32)
    content: str = Field(default="", max_length=2_000_000)
    reason: str = Field(default="", max_length=500)
    change_category: str = Field(default="source",
                                 pattern="^(source|header|cmake|test|documentation)$")
    # 修复补丁专用：该变更作用于参考工程还是 starter 挖空（生成组内忽略）
    target: str = Field(default="reference", pattern="^(reference|starter)$")

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        if "\\" in value or value.startswith("/") or ".." in value.split("/"):
            raise ValueError(f"非法路径：{value}")
        if value.startswith("__pw"):
            raise ValueError(f"保留命名空间：{value}")
        return value


class TaskInstructionsInput(APIModel):
    title: str = Field(min_length=1, max_length=200)
    context: str = Field(default="", max_length=2000)
    goal: str = Field(default="", max_length=2000)
    required_concepts: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    expected_files: list[str] = Field(default_factory=list)
    io_behavior: str = Field(default="", max_length=2000)
    constraints: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    relation_to_prev: str = Field(default="", max_length=2000)
    relation_to_next: str = Field(default="", max_length=2000)


class BuildManifestInput(APIModel):
    build_targets: list[str] = Field(default_factory=list, max_length=20)
    run_targets: list[str] = Field(default_factory=list, max_length=10)
    test_names: list[str] = Field(default_factory=list, max_length=50)
    expected_failure_phase: str | None = Field(default=None,
                                               pattern="^(configure|build|test)$")
    expected_failure_keywords: list[str] = Field(default_factory=list, max_length=10)


class HintInput(APIModel):
    level: int = Field(ge=1, le=4)
    text: str = Field(min_length=1, max_length=2000)


class LessonChangeSet(APIModel):
    """一个 C++ 课程任务的增量变更集。"""

    task_id: str = Field(min_length=1, max_length=60)
    base_snapshot_id: str = Field(default="", max_length=100)
    base_snapshot_hash: str = Field(default="", max_length=32)
    instructions: TaskInstructionsInput
    reference_changes: list[FileChange] = Field(default_factory=list, max_length=100)
    starter_changes: list[FileChange] = Field(default_factory=list, max_length=100)
    test_changes: list[FileChange] = Field(default_factory=list, max_length=100)
    build_manifest: BuildManifestInput
    hints: list[HintInput] = Field(default_factory=list, max_length=4)
    rationale: str = Field(default="", max_length=4000)
