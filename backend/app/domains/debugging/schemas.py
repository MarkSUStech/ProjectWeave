"""调试会话契约（camelCase 别名对外，P4.5a）。

DebugSnapshot = 真实 LLDB DAP 会话数据的结构化投影（非推测）：
位置/线程/栈帧/作用域变量全部来自调试器响应；file 为项目相对路径
（容器内 /sandbox/work 前缀已归一化），直接对应编辑器文件。
"""

import uuid
from datetime import datetime

from pydantic import Field

from app.domains.projects.schemas import APIModel

STATUS_CREATING = "creating"
STATUS_BUILDING = "building"
STATUS_CONFIGURING = "configuring"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_TERMINATED = "terminated"
TERMINAL_STATUSES = {STATUS_TERMINATED}


class BreakpointSpec(APIModel):
    path: str = Field(min_length=1, max_length=300)
    lines: list[int] = Field(min_length=1, max_length=50)


class DebugSessionCreate(APIModel):
    language: str = Field(default="cpp", pattern="^cpp$")
    entry_point: str = Field(min_length=1, max_length=300)
    files: dict[str, str] = Field(min_length=1)
    breakpoints: list[BreakpointSpec] = Field(default_factory=list, max_length=20)
    stop_on_entry: bool = False
    code_fingerprint: str | None = Field(default=None, max_length=80)
    project_id: uuid.UUID | None = None


class StackFrameRead(APIModel):
    id: int
    name: str
    file: str | None = None
    line: int | None = None
    column: int | None = None


class ThreadRead(APIModel):
    id: int
    name: str
    is_primary: bool = False


class VariableRead(APIModel):
    name: str
    value: str = ""
    type: str | None = None
    evaluate_name: str | None = None
    variables_reference: int = 0


class ScopeRead(APIModel):
    name: str
    variables_reference: int
    expensive: bool = False
    variables: list[VariableRead] = Field(default_factory=list)


class LocationRead(APIModel):
    file: str | None = None
    line: int | None = None
    column: int | None = None
    frame_name: str | None = None


class VerifiedBreakpointRead(APIModel):
    path: str
    line: int
    verified: bool
    message: str | None = None


class DebugSnapshotRead(APIModel):
    """GET /debug-sessions/{id} 的完整快照。"""

    id: uuid.UUID
    language: str
    status: str
    end_reason: str | None = None
    entry_point: str
    project_id: uuid.UUID | None = None
    code_fingerprint: str | None = None
    debugger_profile: str | None = None
    location: LocationRead | None = None
    stop_reason: str | None = None
    # 暂停代次：所有按 DAP 引用缓存的数据以此隔离（旧代次引用不得复用）
    pause_seq: int = 0
    thread_id: int | None = None
    # 指针关系图（真实 evaluate 地址匹配；未解析/空指针如实标注）
    pointer_graph: dict | None = None
    threads: list[ThreadRead] = Field(default_factory=list)
    stack_frames: list[StackFrameRead] = Field(default_factory=list)
    scopes: list[ScopeRead] = Field(default_factory=list)
    breakpoints: list[VerifiedBreakpointRead] = Field(default_factory=list)
    build_diagnostics: list[dict] = Field(default_factory=list)
    build_stdout: str = ""
    error: str | None = None
    # 调试期间程序的真实 stdout/stderr（DAP output 事件捕获）
    program_output: list[dict] = Field(default_factory=list)
    dap_log: list[dict] = Field(default_factory=list)
    sandbox: dict = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    paused_at: datetime | None = None
    finished_at: datetime | None = None


class DebugSessionCreated(APIModel):
    id: uuid.UUID
    status: str


class DebugCommandInput(APIModel):
    """结构化调试指令（白名单，非任意 LLDB 命令透传）。"""

    command: str = Field(pattern="^(continue|pause|next|stepIn|stepOut|stop|setBreakpoints)$")
    thread_id: int | None = None
    # 仅 setBreakpoints：整文件替换语义（与 DAP 一致：列表=该文件全部断点）
    breakpoints: list[BreakpointSpec] = Field(default_factory=list, max_length=20)


class DebugVariablesQuery(APIModel):
    """懒加载变量：按 DAP variablesReference 展开（复杂对象/深层作用域）。"""

    frame_id: int | None = None
    variables_reference: int


class FrameVariablesRead(APIModel):
    """按栈帧取作用域变量（当前暂停代次内有效；携带 pauseSeq 供缓存隔离）。"""

    frame_id: int
    pause_seq: int
    scopes: list[ScopeRead] = Field(default_factory=list)
    pointer_graph: dict | None = None
