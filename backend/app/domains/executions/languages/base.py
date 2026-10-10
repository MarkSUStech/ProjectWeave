"""LanguageRunner 协议：语言差异的封装点。

公共执行服务（service.py）只做会话生命周期编排，不含任何
语言特有命令/命名逻辑——新增 C++ 时实现本协议并注册，服务与
API 零改动（D33）。
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domains.executions.sandbox.base import SandboxResult, SandboxSpec


@dataclass
class ParsedOutcome:
    """沙箱结果 → 协议化执行结果（语言相关解析在此完成）。"""

    ok: bool = False
    exit_code: int | None = None
    timed_out: bool = False
    # 诊断：构建/运行/测试，含 file/line（教学映射用）
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    # 测试结果（仅 test 模式）
    test_results: list[dict[str, Any]] | None = None
    # 阶段记录（run 单阶段；C++ 未来 build+run）
    phases: list[dict[str, Any]] = field(default_factory=list)
    # 协议错误信息（如结果标记解析失败）
    protocol_error: str | None = None


@dataclass
class ExecutionSpecInput:
    """来自请求的已校验输入（语言无关部分由服务校验，语言部分由 Runner 校验）。"""

    exec_id: str
    mode: str  # run | test
    entry_point: str | None
    test_paths: list[str]
    files: dict[str, str]
    stdin: str
    timeout_s: float


class LanguageRunner(Protocol):
    """一种语言的执行策略：校验文件、构造沙箱规格、解析结果。"""

    language: str
    image: str

    def validate_files(self, spec: ExecutionSpecInput) -> list[str]:
        """语言特有校验（扩展名白名单等），返回错误列表。"""
        ...

    def build_spec(self, spec: ExecutionSpecInput, timeout_s: float) -> SandboxSpec:
        """构造沙箱启动规格（命令 + stdin 文件包）。"""
        ...

    def parse_result(self, result: SandboxResult, spec: ExecutionSpecInput) -> ParsedOutcome:
        """把沙箱原始输出解析为协议化结果。"""
        ...
