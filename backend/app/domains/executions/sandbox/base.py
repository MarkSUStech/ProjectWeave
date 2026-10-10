"""SandboxManager 协议与共享数据结构。"""

from dataclasses import dataclass, field
from typing import Protocol


class SandboxUnavailableError(RuntimeError):
    """沙箱不可用（Docker 未运行 / 镜像未构建）——必须显式暴露，不得伪造成功。"""

    def __init__(self, reason: str, hint: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.hint = hint


@dataclass
class SandboxResult:
    """一次沙箱运行的产物。"""

    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    # 输出事件流（增量）：[(channel, text)]
    output_events: list[tuple[str, str]] = field(default_factory=list)
    timed_out: bool = False
    killed: bool = False
    duration_ms: int = 0
    # 沙箱是否正常启动（False = 基础设施错误，stderr 为原因）
    started: bool = True
    engine: str = ""
    image: str = ""


@dataclass
class SandboxSpec:
    """启动一个一次性沙箱所需的全部输入（语言无关）。"""

    image: str
    # 完整容器命令参数（由 LanguageRunner 构造），如 ["sh", "-c", "..."]
    command: list[str]
    timeout_s: float
    container_name: str
    exec_id: str
    # 以 tar.gz（gzip）流写入容器 stdin 的文件包（可为 None）。
    stdin_archive: bytes | None = None
    # 资源限制（由执行服务统一给出，Runner 不决定）。
    memory_mb: int = 512
    cpus: float = 1.0
    pids_limit: int = 128
    # 额外环境变量（只允许白名单键，避免泄露服务端配置）。
    env: dict[str, str] = field(default_factory=dict)


class SandboxManager(Protocol):
    """隔离环境管理器接口。

    实现方必须满足：
    - run() 返回前终止并移除它创建的环境（超时/取消同样清理整个环境，
      而非单个子进程）；
    - 不向用户代码暴露 API 密钥/数据库凭据/服务端配置；
    - available() 失败时 run() 抛 SandboxUnavailableError。
    """

    engine: str

    def available(self) -> tuple[bool, str]:
        """(是否可用, 不可用原因+修复提示)。"""
        ...

    def run(
        self,
        spec: SandboxSpec,
        cancel_event,
        on_output=None,
    ) -> SandboxResult:
        """运行到终态（完成/失败/超时/取消），并清理环境。

        on_output(channel, text)：输出流式回调（stdout/stderr 分块），
        可为 None（测试用假沙箱可不触发）。
        """
        ...

    def cleanup_stale(self) -> int:
        """清理本服务遗留的沙箱环境（启动时调用），返回清理数量。"""
        ...
