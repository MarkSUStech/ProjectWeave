"""执行会话契约（camelCase 对外，P4.2b）。

统一协议不绑定任何语言：语言差异封装在 LanguageRunner
（命令构造/结果解析），协议本身只描述会话与结果。
P8.1 增加构建系统维度：buildSystem=direct（默认，向后兼容）或
cmake（CMake 项目 profile：discover/build/run/test 操作）。
"""

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.domains.projects.schemas import APIModel

# 会话状态
STATUS_QUEUED = "queued"
STATUS_PREPARING = "preparing"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_TIMED_OUT = "timed-out"
STATUS_CANCELLED = "cancelled"
TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED, STATUS_TIMED_OUT, STATUS_CANCELLED}

# 输出通道
CHANNELS = {"stdout", "stderr", "system"}

# File API codemodel 的目标类型（P8.1；UTILITY/CUSTOM 统称 UTILITY）
CMAKE_TARGET_TYPES = {
    "EXECUTABLE", "STATIC_LIBRARY", "SHARED_LIBRARY",
    "OBJECT_LIBRARY", "INTERFACE_LIBRARY", "UTILITY",
}


class ExecutionCreate(APIModel):
    """创建执行：提交文件快照与运行意图。"""

    language: str = Field(min_length=1, max_length=20)
    mode: str = Field(pattern="^(run|test)$")
    entry_point: str | None = Field(default=None, max_length=300)
    test_paths: list[str] = Field(default_factory=list, max_length=50)
    files: dict[str, str] = Field(min_length=1)
    stdin: str | None = None
    timeout_ms: int = Field(default=20000, ge=1000, le=600000)
    code_fingerprint: str | None = Field(default=None, max_length=80)
    project_id: uuid.UUID | None = None
    # ---- P8.1 构建系统 profile（默认 direct = 旧行为，零破坏）----
    build_system: str = Field(default="direct", pattern="^(direct|cmake)$")
    # cmake 模式下的操作（仅 buildSystem=cmake 且 mode=run 时有效）：
    # discover = Configure + File API 目标发现；build = 构建指定目标不运行；
    # run = 构建 + 运行指定目标。缺省 = run。mode=test 时为 ctest 流程。
    cmake_action: str | None = Field(default=None, pattern="^(discover|build|run)$")
    # 必须来自真实 discover 结果的目标名（服务端与驱动双重白名单校验）。
    target_name: str | None = Field(default=None, max_length=100,
                                    pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")
    # ctest 选择执行（空 = 全部；名字经转义后作为 -R 正则传入）。
    selected_tests: list[str] = Field(default_factory=list, max_length=100)


class CmakeTargetRead(APIModel):
    """File API 发现的一个 CMake 目标（真实 codemodel 数据，非猜测）。"""

    name: str
    type: str  # CMAKE_TARGET_TYPES
    runnable: bool  # 仅 EXECUTABLE 且有产物
    source_directory: str = ""
    build_directory: str = ""
    sources: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    configuration: str = ""


class CmakeInfoRead(APIModel):
    """CMake profile 会话的结构化结果。"""

    operation: str  # discover | build | run | test
    targets: list[CmakeTargetRead] | None = None  # discover 返回
    discovered_tests: list[str] = Field(default_factory=list)  # test 返回
    # P8.1.1：要求执行但未运行的测试（判定失败的依据，透明展示）
    required_missing: list[str] = Field(default_factory=list)
    not_selected: list[str] = Field(default_factory=list)  # 未在本次选择范围
    target: str | None = None
    artifact: str | None = None
    generator: str | None = None
    cmake_version: str | None = None


class ExecutionEventRead(APIModel):
    seq: int
    at: datetime
    channel: str
    text: str


class DiagnosticRead(APIModel):
    """诊断（构建/运行/测试），兼容前端 execution 层 Diagnostic。"""

    severity: str = "error"
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    source: str = "runtime"
    # P8.1：构建阶段细分（configure | compile | link | run | test | target-not-found …）
    stage: str | None = None


class TestCaseRead(APIModel):
    name: str
    status: str  # passed | failed | error | skipped
    error: str | None = None
    file: str | None = None
    line: int | None = None
    duration_ms: int = 0


class TestFileRead(APIModel):
    path: str
    status: str  # passed | failed | error
    cases: list[TestCaseRead] = Field(default_factory=list)
    error: str | None = None


class PhaseRead(APIModel):
    """执行阶段（run 单阶段；C++ 未来 build+run 两阶段）。"""

    name: str  # prepare | build | run | test
    status: str  # completed | failed | skipped
    duration_ms: int = 0
    exit_code: int | None = None


class ExecutionRead(APIModel):
    id: uuid.UUID
    language: str
    mode: str
    status: str
    entry_point: str | None = None
    test_paths: list[str] = Field(default_factory=list)
    timeout_ms: int
    code_fingerprint: str | None = None
    project_id: uuid.UUID | None = None
    build_system: str = "direct"
    target_name: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    error: str | None = None
    stdout: str = ""
    stderr: str = ""
    events: list[ExecutionEventRead] = Field(default_factory=list)
    diagnostics: list[DiagnosticRead] = Field(default_factory=list)
    test_results: list[TestFileRead] | None = None
    phases: list[PhaseRead] = Field(default_factory=list)
    cmake: CmakeInfoRead | None = None
    sandbox: dict = Field(default_factory=dict)
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    run_time_ms: int = 0

    @field_validator("events", mode="before")
    @classmethod
    def _events_default(cls, v: object) -> object:
        return v if v is not None else []


class ExecutionCreated(APIModel):
    id: uuid.UUID
    status: str


class ExecutionCancelled(APIModel):
    id: uuid.UUID
    status: str
    already_finished: bool = False
