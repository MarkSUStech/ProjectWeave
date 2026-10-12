"""课程教学内容契约（P7.2，D42）：LessonArtifact / CourseRelease / 验证记录。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.domains.projects.schemas import APIModel

# 单任务教学材料的验证状态（单调推进，不混用）
TASK_BUILD_STATUSES = (
    "generated",        # LLM 已产出材料
    "schema-valid",     # 结构与防伪守卫通过
    "build-valid",      # 参考实现可构建/导入
    "tests-passed",     # 本任务测试 + 回归测试真实通过
    "failed",           # 修复轮耗尽仍失败
    "unsupported",      # 沙箱不支持（语言/依赖）——如实标注
)

RELEASE_STATUSES = (
    "generating", "verifying", "ready", "failed",
)


class TaskInstructions(APIModel):
    title: str
    context: str = ""            # 项目背景
    goal: str = ""               # 本阶段目标
    required_concepts: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)      # 要实现的功能
    expected_files: list[str] = Field(default_factory=list)
    io_behavior: str = ""        # 输入输出行为
    constraints: list[str] = Field(default_factory=list)   # 实现限制
    acceptance: list[str] = Field(default_factory=list)
    relation_to_prev: str = ""   # 与前一任务的关系
    relation_to_next: str = ""


class HintSpec(APIModel):
    level: int  # 1-4
    text: str


class CodeFile(APIModel):
    path: str
    content: str


class SandboxVerification(APIModel):
    """一次真实沙箱执行的证据（确定性记录，非 LLM 判断）。"""

    kind: str  # reference-tests | regression | starter-expected-fail | final-integration
    status: str  # passed | failed | error | skipped
    # P8.2.1：人类可读佐证（如 starter 预期失败的具体测试名）
    note: str = ""
    exit_code: int | None = None
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    diagnostics: list[dict] = Field(default_factory=list)  # file/line/message
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int = 0


class RepairRecord(APIModel):
    round: int
    problem: str           # 修复前的真实错误摘要
    changed_files: list[str] = Field(default_factory=list)
    outcome: str           # fixed | still-failing


class CmakeBuildManifest(APIModel):
    """CMake 任务的构建清单（P8.2，D45）：验证与验收的权威契约。

    目标/测试名必须由真实 CMake File API / CTest 发现结果证实——
    生成器只声明意图，验证器负责校验存在性。
    """

    build_targets: list[str] = Field(default_factory=list)   # 本任务需构建的目标
    run_targets: list[str] = Field(default_factory=list)     # 需真实运行的目标（demo）
    test_names: list[str] = Field(default_factory=list)      # 要求通过的 CTest 测试名
    # 仅"修复构建"类教学任务允许声明预期失败阶段（configure|build），
    # 并附预期诊断关键词；普通功能任务为 None。
    expected_failure_phase: str | None = Field(default=None,
                                               pattern="^(configure|build|test)$")
    expected_failure_keywords: list[str] = Field(default_factory=list)


class LessonArtifact(APIModel):
    """一个任务的可执行教学材料（参考实现受保护，不下发前端）。"""

    task_id: str
    milestone_id: str
    language: str  # 执行层语言 id（python/cpp/typescript）
    instructions: TaskInstructions
    starter_files: list[CodeFile] = Field(default_factory=list)
    test_files: list[CodeFile] = Field(default_factory=list)
    # 服务端受保护：绝不进入普通 API 响应/项目文件
    reference_files: list[CodeFile] = Field(default_factory=list)
    hints: list[HintSpec] = Field(default_factory=list)
    # P8.2：CMake 任务的构建清单（Python 课程为 None）
    build_manifest: CmakeBuildManifest | None = None
    # 验证元数据
    artifact_version: int = 1
    status: str = Field(default="generated", pattern="^(" + "|".join(TASK_BUILD_STATUSES) + ")$")
    verifications: list[SandboxVerification] = Field(default_factory=list)
    repairs: list[RepairRecord] = Field(default_factory=list)
    generation_model: str = ""
    error: str | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------- API 契约


class ArtifactPublicRead(APIModel):
    """前端可见的材料（参考实现剥离）。"""

    task_id: str
    milestone_id: str
    language: str
    instructions: TaskInstructions
    starter_files: list[CodeFile]
    test_files: list[CodeFile]
    hints: list[HintSpec]  # 服务端剥离 H4 后下发（H4 走 Tutor Gate）
    build_manifest: CmakeBuildManifest | None = None
    status: str
    verifications: list[SandboxVerification]
    repairs: list[RepairRecord]
    error: str | None


class ReleaseRead(APIModel):
    id: uuid.UUID
    generation_id: uuid.UUID
    release_version: int
    status: str
    language: str
    total_tasks: int = 0
    passed_tasks: int = 0
    failed_tasks: int = 0
    progress: int = 0
    current_task: str | None = None
    error: str | None = None
    course_title: str = ""
    ready_at: datetime | None = None
    created_at: datetime
    # P8.2.1：验证汇总（最终集成/诊断/检查点复用信息；不含参考实现）
    verification_report: dict = Field(default_factory=dict)


class ReleaseDetailRead(ReleaseRead):
    artifacts: list[ArtifactPublicRead] = Field(default_factory=list)


class InstantiateRequest(APIModel):
    project_title: str | None = Field(default=None, max_length=200)


class InstantiateResponse(APIModel):
    project_id: uuid.UUID
    first_task_id: str | None = None
