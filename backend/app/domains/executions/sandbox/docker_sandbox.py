"""Docker 沙箱实现（开发/教学场景，D32）。

隔离手段（全部通过 docker run 参数施加，容器一次性、命名可追踪）：
- --network none            默认禁止网络
- --read-only + tmpfs       只读根文件系统，唯一可写区为 /sandbox（noexec）
- --user 10001:10001        非 root 运行用户
- --cap-drop ALL / no-new-privileges / seccomp 默认 profile
- --memory/--cpus/--pids-limit  资源上限
- --stop-timeout            SIGTERM 优雅期，超时 SIGKILL 整个容器

文件注入：stdin 流式 tar.gz → 容器内解包到 /sandbox/work，
不使用 docker cp / 宿主目录挂载（避免只读根与宿主共享配置问题）。
"""

from __future__ import annotations

import subprocess
import threading
import time

from app.domains.executions.sandbox.base import (
    SandboxResult,
    SandboxSpec,
    SandboxUnavailableError,
)

# 所有沙箱容器带此标签，供启动清理与审计。
LABEL_KEY = "pw.sandbox"
LABEL_EXEC = "pw.exec_id"

STOP_GRACE_S = 5


def _docker_base_args() -> list[str]:
    # Windows/低权限环境下不依赖 DOCKER_HOST 之外的任何全局状态。
    return ["docker"]


class DockerSandboxManager:
    """通过 docker CLI 管理一次性容器。

    线程模型：每个执行占用一个工作线程，run() 阻塞至终态。
    """

    engine = "docker"

    def __init__(self, docker_bin: str = "docker"):
        self._docker = docker_bin

    # --- 可用性 -------------------------------------------------------------

    def available(self) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                [self._docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"Docker 不可达（{exc}）。请安装并启动 Docker Desktop。"
        if proc.returncode != 0:
            return False, f"Docker 守护进程未运行：{proc.stderr.strip()[:200]}"
        return True, ""

    def ensure_image(self, image: str) -> tuple[bool, str]:
        ok, reason = self.available()
        if not ok:
            return False, reason
        proc = subprocess.run(
            [self._docker, "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return False, (
                f"沙箱镜像不存在：{image}。请先构建："
                f"docker build -t {image} backend/sandbox/python"
            )
        return True, ""

    # --- 运行 ---------------------------------------------------------------

    def _run_args(self, spec: SandboxSpec) -> list[str]:
        return [
            self._docker, "run",
            "--name", spec.container_name,
            "--label", f"{LABEL_KEY}=1",
            "--label", f"{LABEL_EXEC}={spec.exec_id}",
            # 网络：默认完全禁止
            "--network", "none",
            # 文件系统：只读根 + 唯一可写 tmpfs（属主=运行用户，禁止执行二进制）
            "--read-only",
            "--tmpfs", "/sandbox:rw,noexec,size=64m,uid=10001,gid=10001,mode=0770",
            # 身份与权限
            "--user", "10001:10001",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            # 资源上限
            "--memory", f"{spec.memory_mb}m",
            "--memory-swap", f"{spec.memory_mb}m",
            "--cpus", str(spec.cpus),
            "--pids-limit", str(spec.pids_limit),
            "--stop-timeout", str(STOP_GRACE_S),
            # stdin 传入文件包
            "--interactive",
            # 白名单环境变量（不继承宿主/服务端配置）
            *([arg for kv in spec.env.items() for arg in ("-e", f"{kv[0]}={kv[1]}")]),
            spec.image,
            *spec.command,
        ]

    def _kill_container(self, name: str) -> None:
        """终止并移除整个容器（幂等，尽力而为）。"""
        for args in (
            [self._docker, "kill", name],
            [self._docker, "rm", "-f", name],
        ):
            try:
                subprocess.run(args, capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def run(
        self,
        spec: SandboxSpec,
        cancel_event: threading.Event,
        on_output=None,
    ) -> SandboxResult:
        ok, image_err = self.ensure_image(spec.image)
        if not ok:
            raise SandboxUnavailableError(image_err.split("。")[0], image_err)

        result = SandboxResult(engine=self.engine, image=spec.image)
        args = self._run_args(spec)
        start = time.monotonic()

        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # 文本模式下 GBK 环境下的非 ASCII 输出会崩，统一按字节读再替换解码。
            )
        except OSError as exc:
            result.started = False
            result.stderr = f"无法启动容器：{exc}"
            return result

        killed_by_cancel = False
        timed_out = False

        def _write_stdin() -> None:
            try:
                if proc.stdin is not None:
                    if spec.stdin_archive is not None:
                        proc.stdin.write(spec.stdin_archive)
                    proc.stdin.close()
            except (OSError, ValueError):
                # 容器提前退出时写入失败可忽略（读取端会得到真实输出/错误）。
                pass

        writer = threading.Thread(target=_write_stdin, daemon=True)
        writer.start()

        deadline = start + spec.timeout_s + STOP_GRACE_S + 10
        # 读线程：逐块读取 stdout/stderr 直到 EOF 或被终止。
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []

        def _drain(pipe, sink: list[bytes], channel: str) -> None:
            try:
                while True:
                    # read1：有数据就返回（read(n) 会阻塞到读满 n 字节或 EOF，无法流式）
                    chunk = pipe.read1(8192)
                    if not chunk:
                        break
                    sink.append(chunk)
                    if on_output is not None:
                        try:
                            on_output(channel, chunk.decode("utf-8", errors="replace"))
                        except Exception:  # 回调失败不影响读取
                            pass
            except (OSError, ValueError):
                pass

        readers = [
            threading.Thread(target=_drain, args=(proc.stdout, stdout_chunks, "stdout"), daemon=True),
            threading.Thread(target=_drain, args=(proc.stderr, stderr_chunks, "stderr"), daemon=True),
        ]
        for reader in readers:
            reader.start()

        # 主循环：等待退出 / 超时 / 取消。
        while True:
            if cancel_event.is_set():
                killed_by_cancel = True
                self._kill_container(spec.container_name)
                break
            if proc.poll() is not None:
                break
            if time.monotonic() > deadline:
                timed_out = True
                self._kill_container(spec.container_name)
                break
            time.sleep(0.1)

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._kill_container(spec.container_name)
            proc.wait(timeout=30)
        for reader in readers:
            reader.join(timeout=10)
        writer.join(timeout=5)

        result.duration_ms = int((time.monotonic() - start) * 1000)
        result.exit_code = proc.returncode
        result.stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        result.stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        result.timed_out = timed_out
        result.killed = killed_by_cancel
        if killed_by_cancel:
            result.exit_code = None
        # 无论终态如何都销毁容器（一次性环境，不留 Exited 遗留）。
        self._kill_container(spec.container_name)
        return result

    # --- 清理 ---------------------------------------------------------------

    def cleanup_stale(self) -> int:
        """移除本服务遗留的沙箱容器（服务重启后调用）。"""
        try:
            proc = subprocess.run(
                [self._docker, "ps", "-a", "--filter", f"label={LABEL_KEY}=1", "-q"],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return 0
        ids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        for container_id in ids:
            self._kill_container(container_id)
        return len(ids)
