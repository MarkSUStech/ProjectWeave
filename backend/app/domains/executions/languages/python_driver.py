"""ProjectWeave 沙箱执行驱动（Python）。

本文件由后端在每次执行时打包进容器（__pw/driver.py），不是用户代码。
职责：
- run 模式：以子进程运行入口 .py，转发 stdout/stderr（直接继承容器流），
  程序 stdin 来自 manifest；子进程超时被杀并上报标记；
- test 模式：以 pytest Python API 运行测试，内置 Recorder 插件收集
  逐用例结果（文件/行号/失败消息），结束打印结果标记行；
- 结果经 stdout 尾部的 ===PW_RESULT=== 标记行回传（后端解析）。

约束：不 import 项目用户代码，不联网，退出码 = 程序退出码（测试全过为 0）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

RESULT_MARKER = "===PW_RESULT==="
MANIFEST_PATH = os.path.join("__pw", "manifest.json")
MAX_MESSAGE_CHARS = 600


def _emit(payload: dict) -> None:
    sys.stdout.write(RESULT_MARKER + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _truncate(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.strip()
    return text[:MAX_MESSAGE_CHARS] if text else None


def run_mode(manifest: dict) -> None:
    entry = manifest["entry"]
    stdin_text = manifest.get("stdin", "")
    timeout = float(manifest.get("timeoutSec", 20))
    try:
        proc = subprocess.run(
            [sys.executable, "-u", entry],
            input=stdin_text,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
        )
    except subprocess.TimeoutExpired:
        _emit({"kind": "run", "exitCode": None, "timedOut": True})
        sys.exit(124)
    _emit({"kind": "run", "exitCode": proc.returncode, "timedOut": False})
    code = proc.returncode if proc.returncode >= 0 else 128 - proc.returncode
    sys.exit(code)


def test_mode(manifest: dict) -> None:
    import pytest

    timeout = float(manifest.get("timeoutSec", 20))
    test_paths = list(manifest.get("testPaths", []))
    records: dict[str, dict] = {}
    file_errors: list[dict] = []

    class Recorder:
        """pytest 插件：逐用例聚合 setup/call 阶段结果。"""

        def pytest_runtest_logreport(self, report):
            nodeid = report.nodeid
            relpath, lineno, _name = report.location
            if report.when == "setup":
                current = {"file": relpath, "line": lineno + 1}
                if report.failed:
                    current.update(
                        status="error",
                        error=_truncate(getattr(report.longrepr, "reprcrash", None) and report.longrepr.reprcrash.message) or "setup 失败",
                        duration_ms=0,
                    )
                    records[nodeid] = current
                elif report.skipped:
                    records.setdefault(
                        nodeid,
                        {"file": relpath, "line": lineno + 1, "status": "skipped", "error": None, "duration_ms": 0},
                    )
                else:
                    records.setdefault(
                        nodeid,
                        {"file": relpath, "line": lineno + 1, "status": "passed", "error": None, "duration_ms": 0},
                    )
                return
            if report.when == "call":
                rec = records.setdefault(
                    nodeid, {"file": relpath, "line": lineno + 1, "status": "passed", "error": None, "duration_ms": 0}
                )
                rec["duration_ms"] = int(report.duration * 1000)
                if report.failed:
                    crash = getattr(report.longrepr, "reprcrash", None)
                    rec["status"] = "failed"
                    rec["error"] = _truncate(crash.message if crash else str(report.longrepr)) or "断言失败"
                    # 崩溃位置（1-based）指向失败断言行，比 location 的 def 行更精确
                    if crash is not None and getattr(crash, "lineno", None):
                        rec["file"] = str(getattr(crash, "path", relpath) or relpath)
                        rec["line"] = crash.lineno
                elif report.passed:
                    # setup 通过 + call 通过 → passed
                    if rec.get("status") not in ("error",):
                        rec["status"] = "passed"
                elif report.skipped:
                    rec["status"] = "skipped"

        def pytest_collectreport(self, report):
            if report.failed:
                crash = getattr(report.longrepr, "reprcrash", None)
                file_errors.append(
                    {
                        "file": report.nodeid or "",
                        "error": _truncate(crash.message if crash else str(report.longrepr))
                        or "收集失败（导入错误）",
                    }
                )

    # 看门狗：pytest 无法从内部中断僵死用例，超时强制上报并退出。
    def _watchdog() -> None:
        time.sleep(timeout + 5)
        _emit({"kind": "pytest", "exitCode": None, "timedOut": True, "tests": [], "fileErrors": file_errors, "partial": True})
        os._exit(124)

    threading.Thread(target=_watchdog, daemon=True).start()

    code = pytest.main(
        ["-q", "--tb=short", "--color=no", "-p", "no:cacheprovider", *test_paths],
        plugins=[Recorder()],
    )
    # 保持执行顺序（dict 插入序），不按状态重排。
    tests = [{"name": nodeid, **rec} for nodeid, rec in records.items()]
    _emit(
        {
            "kind": "pytest",
            "exitCode": int(code),
            "timedOut": False,
            "tests": tests,
            "fileErrors": file_errors,
            "partial": False,
        }
    )
    all_ok = not file_errors and all(t["status"] == "passed" for t in tests)
    sys.exit(0 if all_ok else 1)


def main() -> None:
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        manifest = json.load(fh)
    if manifest.get("mode") == "test":
        test_mode(manifest)
    else:
        run_mode(manifest)


if __name__ == "__main__":
    main()
