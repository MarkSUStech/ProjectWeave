"""调试沙箱（P4.5a，D36）：长生命周期容器 + docker exec 通道。

与一次性执行沙箱的差异：
- 容器常驻（sleep infinity），构建/调试经 `docker exec -i` 进行；
- 文件经 exec stdin 的 gzip-tar 注入（同执行沙箱，不挂宿主目录）；
- **调试专用 seccomp**（backend/sandbox/cpp-debug/seccomp-debug.json）=
  上游 moby v28.0.1 默认 profile 仅放开 personality（LLDB 禁 ASLR 需要；
  ptrace 默认已允许）——只用于调试沙箱，绝不用于普通执行沙箱；
- 其余隔离与执行沙箱一致：禁网/只读根/exec tmpfs（uid 10001）/非 root/
  cap-drop ALL/no-new-privileges/资源限额/pw.debug 标签追踪。

安全边界：调试沙箱面向受控开发/教学环境（同 D32 声明），不是面向
不可信公网的强隔离服务。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
import threading
from typing import Protocol

from app.domains.executions.sandbox.base import SandboxUnavailableError

DEBUG_LABEL = "pw.debug=1"

IMAGE = "projectweave-sandbox-cpp-debug:clang19-trixie"
DEBUGGER_PROFILE = "lldb-dap:19"

_WORKDIR = "/sandbox/work"
# backend/app/domains/debugging → backend/sandbox/cpp-debug
_SECCOMP_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "sandbox", "cpp-debug", "seccomp-debug.json")

_EXEC_ENV = [
    "-e", "TMPDIR=/sandbox/tmp",
    "-e", "HOME=/sandbox/home",
    "-e", "PYTHONDONTWRITEBYTECODE=1",
]

# 调试构建参数（D35 编译约定：-O0 -g 保留完整调试信息）
DEBUG_BUILD_FLAGS = ["-std=c++20", "-O0", "-g", "-Wall", "-Wextra", "-fdiagnostics-color=never"]


def seccomp_profile_path() -> str:
    return os.path.abspath(_SECCOMP_PATH)


def build_files_archive(files: dict[str, str]) -> bytes:
    """项目文件 → gzip tar（调试会话不需要执行驱动，仅注入源码）。"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        def _add(name: str, data: str) -> None:
            payload = data.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))

        for path in sorted(files):
            _add(path, files[path])
    return buffer.getvalue()


class DebugSandboxProvider(Protocol):
    """调试容器生命周期原语（测试可注入假实现）。"""

    image: str

    def available(self) -> tuple[bool, str]: ...
    def start(self, name: str) -> None: ...
    def put_files(self, name: str, archive: bytes) -> None: ...
    def run_build(self, name: str, command: list[str], timeout_s: float) -> tuple[int, str, str]: ...
    def dap_argv(self, name: str) -> list[str]: ...
    def destroy(self, name: str) -> None: ...
    def cleanup_stale(self) -> int: ...


class DockerDebugSandbox:
    """docker CLI 实现。"""

    image = IMAGE
    engine = "docker"

    def _run(self, *args: str, stdin: bytes | None = None, timeout: float = 60.0, check: bool = False):
        proc = subprocess.run(
            ["docker", *args], input=stdin, capture_output=True, timeout=timeout
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"docker {args[0]} 失败：{proc.stderr.decode('utf-8', errors='replace')[:300]}"
            )
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )

    def available(self) -> tuple[bool, str]:
        try:
            code, _, err = self._run("info", "--format", "{{.ServerVersion}}", timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"Docker 不可达（{exc}）。请安装并启动 Docker Desktop。"
        if code != 0:
            return False, f"Docker 守护进程未运行：{err[:200]}"
        code, _, _ = self._run("image", "inspect", self.image, timeout=15)
        if code != 0:
            return False, (
                f"调试镜像不存在：{self.image}。请先构建："
                f"docker build -t {self.image} backend/sandbox/cpp-debug"
            )
        return True, ""

    def start(self, name: str) -> None:
        """启动常驻调试容器（受限 flag + 调试专用 seccomp，D36）。"""
        self._run(
            "run", "-d", "--name", name,
            "--label", DEBUG_LABEL,
            "--network", "none",
            "--read-only",
            "--tmpfs", "/sandbox:rw,exec,size=256m,uid=10001,gid=10001,mode=0770",
            "--user", "10001:10001",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--security-opt", f"seccomp={seccomp_profile_path()}",
            "--memory", "512m", "--memory-swap", "512m",
            "--cpus", "1.0", "--pids-limit", "128",
            self.image, "sleep", "infinity",
            timeout=60, check=True,
        )

    def put_files(self, name: str, archive: bytes) -> None:
        self._run(
            "exec", "-i", *_EXEC_ENV, name, "sh", "-c",
            f"mkdir -p {_WORKDIR} /sandbox/tmp /sandbox/home && tar -xzf - -C {_WORKDIR}",
            stdin=archive, timeout=60, check=True,
        )

    def run_build(self, name: str, command: list[str], timeout_s: float) -> tuple[int, str, str]:
        quoted = " ".join(command)
        code, out, err = self._run(
            "exec", *_EXEC_ENV, name, "sh", "-c",
            f"cd {_WORKDIR} && mkdir -p {_WORKDIR}/__pw_build && {quoted} 2>&1",
            timeout=timeout_s,
        )
        return code, out, err

    def dap_argv(self, name: str) -> list[str]:
        """DAP 通道：docker exec -i lldb-dap（stdio 直通）。"""
        return ["docker", "exec", "-i", *_EXEC_ENV, name, "lldb-dap"]

    def destroy(self, name: str) -> None:
        for args in (["kill", name], ["rm", "-f", name]):
            try:
                self._run(*args, timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def cleanup_stale(self) -> int:
        try:
            code, out, _ = self._run(
                "ps", "-a", "--filter", f"label={DEBUG_LABEL}", "-q", timeout=20
            )
        except (OSError, subprocess.TimeoutExpired):
            return 0
        ids = [line for line in out.splitlines() if line.strip()]
        for container_id in ids:
            self.destroy(container_id)
        return len(ids)
