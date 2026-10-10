"""ProjectWeave 沙箱执行驱动（C++，P4.2c）。

随每次执行打包进容器（__pw/driver.py），不是用户代码。
流程：PREPARE（源集选择）→ BUILD（clang++ / cmake+ninja）→ RUN/TEST → 标记回传。

阶段语义（与后端 phases 对应）：
- build 失败 → 不进入 RUN，编译器输出原样保留 + 后端解析诊断；
- run 失败/超时/信号 → 退出码与 timedOut 如实上报；
- test = 逐测试可执行程序（编译 + 运行 + 退出码），空测试不判通过。

源码选择策略（确定性，无 LLM）：
- run：入口 + 全部非测试翻译单元（多 main 交给链接器报真实错误）；
- test：测试文件 + 全部非测试且不含 int main 的翻译单元
  （排除程序入口，避免多 main 链接冲突——D35）。
- CMakeLists.txt 存在且 run 模式 → cmake -G Ninja 构建，运行目标 = 入口文件名去扩展名。

约束：不下载外部依赖（网络本就禁用）；编译参数由本驱动固定，不拼接用户命令。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time

RESULT_MARKER = "===PW_RESULT==="
MANIFEST_PATH = os.path.join("__pw", "manifest.json")

SOURCE_EXTENSIONS = {".cpp", ".cc", ".cxx"}
TEST_RE = re.compile(r"(^|/)(test_[^/]+\.(cpp|cc|cxx)|[^/]+_test\.(cpp|cc|cxx))$")
MAIN_RE = re.compile(r"\bint\s+main\s*\(")
ADD_EXECUTABLE_RE = re.compile(r"add_executable\s*\(\s*([A-Za-z0-9_.-]+)([^)]*)\)", re.MULTILINE)

CLANGXX = "clang++"
BUILD_FLAGS = [
    "-std=c++20",
    "-O0",
    "-g",
    "-Wall",
    "-Wextra",
    "-fdiagnostics-color=never",
]
MAX_CAPTURE_CHARS = 8000
CMAKE_TARGET_TIMEOUT_S = 120


def _emit(payload: dict) -> None:
    sys.stdout.write(RESULT_MARKER + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _truncate(text: str) -> str:
    return text[:MAX_CAPTURE_CHARS] if len(text) > MAX_CAPTURE_CHARS else text


# ---------------------------------------------------------------- 源集选择（纯函数，可离线测试）


def is_test_file(path: str) -> bool:
    return bool(TEST_RE.search(path))


def find_entry_like_sources(files: dict[str, str]) -> set[str]:
    """内容启发式：非测试翻译单元中含 int main( 的视为程序入口（测试链接时排除）。"""
    return {
        path
        for path, content in files.items()
        if not is_test_file(path)
        and os.path.splitext(path)[1] in SOURCE_EXTENSIONS
        and MAIN_RE.search(content)
    }


def select_run_sources(files: dict[str, str], entry: str) -> list[str]:
    """run 模式：入口 + 全部非测试翻译单元（保序：入口优先，其余按路径排序）。"""
    others = sorted(
        p for p in files
        if not is_test_file(p) and os.path.splitext(p)[1] in SOURCE_EXTENSIONS and p != entry
    )
    return [entry, *others]


def select_test_sources(files: dict[str, str], test_path: str, entry_like: set[str]) -> list[str]:
    """test 模式：测试文件 + 非测试、非入口的翻译单元（避免多 main 链接冲突）。"""
    return [
        test_path,
        *sorted(
            p for p in files
            if not is_test_file(p)
            and os.path.splitext(p)[1] in SOURCE_EXTENSIONS
            and p not in entry_like
            and p != test_path
        ),
    ]


# ---------------------------------------------------------------- 构建与运行


def _run(cmd: list[str], *, cwd: str, timeout: float, stdin_text: str | None = None):
    """运行子进程（捕获输出），返回 (returncode, stdout, stderr, timed_out)。"""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            input=stdin_text,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or "", False
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        err = exc.stderr if isinstance(exc.stderr, str) else ""
        return None, out, err, True


def _run_streaming(cmd: list[str], *, cwd: str, timeout: float, stdin_text: str = ""):
    """运行子进程（输出直接继承 → 容器 stdout/stderr 实时流式）。

    编译产物运行用它：终端/取消依赖实时输出；退出码与超时仍受控。
    """
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdin=subprocess.PIPE, text=True,
    )
    import threading as _threading

    def _feed_stdin():
        try:
            if stdin_text:
                proc.stdin.write(stdin_text)
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    _threading.Thread(target=_feed_stdin, daemon=True).start()
    try:
        code = proc.wait(timeout=timeout)
        return code, "", "", False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return None, "", "", True


def _compile(sources: list[str], output: str, cwd: str, timeout: float):
    """clang++ 编译链接；编译器输出透传到容器 stderr（终端可见）并返回。"""
    code, _out, err, timed_out = _run(
        [CLANGXX, *BUILD_FLAGS, "-o", output, *sources], cwd=cwd, timeout=timeout
    )
    if err:
        sys.stderr.write(err)
        sys.stderr.flush()
    return code, _truncate(err), timed_out


def run_mode(manifest: dict) -> None:
    timeout = float(manifest.get("timeoutSec", 20))
    entry = manifest["entry"]
    stdin_text = manifest.get("stdin", "")
    work = os.getcwd()
    files = _project_files()

    has_cmake = "CMakeLists.txt" in files
    os.makedirs(os.path.join(work, "__pw_build"), exist_ok=True)
    binary = os.path.join(work, "__pw_build", "app")

    if has_cmake:
        target = resolve_cmake_target(files, entry)
        code, err, timed_out, binary = _cmake_build(work, target, timeout)
        if code != 0:
            _emit({"kind": "cpp", "phase": "build-failed", "buildExit": code,
                   "buildDiagnosticsRaw": err, "buildTool": "cmake", "timedOut": timed_out})
            sys.exit(code or 1)
    else:
        sources = select_run_sources(files, entry)
        build_start = time.monotonic()
        code, err, timed_out = _compile(sources, binary, work, min(timeout, 120))
        build_ms = int((time.monotonic() - build_start) * 1000)
        if code != 0 or timed_out:
            _emit({"kind": "cpp", "phase": "build-failed", "buildExit": code,
                   "buildDiagnosticsRaw": err, "buildTool": "clang++",
                   "buildMs": build_ms, "timedOut": timed_out})
            sys.exit(code or 1)

    run_start = time.monotonic()
    code, _out, _err, timed_out = _run_streaming(
        [binary], cwd=work, timeout=timeout, stdin_text=stdin_text
    )
    run_ms = int((time.monotonic() - run_start) * 1000)
    # 子进程输出经继承的 stdout/stderr 直接流式透传，无需回放
    _emit({
        "kind": "cpp", "phase": "ran",
        "buildExit": 0, "runExit": code, "timedOut": timed_out, "runMs": run_ms,
        "signal": _signal_name(code),
    })
    sys.exit(code if isinstance(code, int) and code >= 0 else (124 if timed_out else 1))


def test_mode(manifest: dict) -> None:
    timeout = float(manifest.get("timeoutSec", 20))
    work = os.getcwd()
    files = _project_files()
    entry_like = find_entry_like_sources(files)
    test_paths = list(manifest.get("testPaths", []))
    build_dir = os.path.join(work, "__pw_build")
    os.makedirs(build_dir, exist_ok=True)
    results = []

    for index, test_path in enumerate(test_paths):
        sources = select_test_sources(files, test_path, entry_like)
        binary = os.path.join(build_dir, f"test_{index}")
        build_start = time.monotonic()
        code, err, timed_out = _compile(sources, binary, work, min(timeout, 120))
        build_ms = int((time.monotonic() - build_start) * 1000)
        if code != 0 or timed_out:
            results.append({
                "name": test_path, "file": test_path, "passed": False, "status": "error",
                "exitCode": code, "durationMs": build_ms,
                "error": "编译失败：" + _last_error_line(err) if not timed_out else "编译超时",
                "buildStderr": err,
            })
            continue

        run_start = time.monotonic()
        run_code, out, err, timed_out = _run([binary], cwd=work, stdin_text="", timeout=timeout)
        duration_ms = int((time.monotonic() - run_start) * 1000)
        signal = _signal_name(run_code)
        combined = out + err
        passed = run_code == 0 and not timed_out and bool(combined.strip())
        if timed_out:
            status, error = "error", "测试执行超时"
        elif signal:
            status, error = "error", f"测试崩溃（{signal}）"
        elif run_code == 0 and not combined.strip():
            status, error = "error", "空测试：无任何输出（测试可执行程序需产生输出以证明断言执行）"
        elif run_code == 0:
            status, error = "passed", None
        else:
            # 干净退出但非零 = 断言失败（约定：测试程序用返回码报告失败）
            last_line = next((ln for ln in reversed(combined.strip().splitlines()) if ln.strip()), "")
            status = "failed"
            error = f"断言失败（退出码 {run_code}）" + (f"：{last_line[:200]}" if last_line else "")
        record = {
            "name": test_path, "file": test_path,
            "passed": passed,
            "status": status,
            "exitCode": run_code, "durationMs": duration_ms,
            "stdoutTail": _truncate(out), "stderrTail": _truncate(err),
            "signal": signal,
            "error": error,
        }
        results.append(record)

    _emit({"kind": "cpp", "phase": "tested", "tests": results})
    sys.exit(0 if results and all(r["passed"] for r in results) else 1)


def resolve_cmake_target(files: dict[str, str], entry: str) -> str:
    """从 CMakeLists.txt 解析包含入口源文件的 add_executable 目标。

    确定性规则：入口文件出现在哪个可执行目标的源列表里就用它；
    未命中时回退约定（目标名 = 入口文件名去扩展名）。
    """
    entry_base = os.path.basename(entry)
    cmake_text = files.get("CMakeLists.txt", "")
    for match in ADD_EXECUTABLE_RE.finditer(cmake_text):
        target, args = match.group(1), match.group(2)
        if entry in args or entry_base in args.split():
            return target
    return os.path.splitext(entry_base)[0]


def _cmake_build(work: str, target: str, timeout: float):
    """cmake -G Ninja 配置 + 构建指定目标，返回 (code, stderr, timed_out, binary_path)。"""
    build_dir = os.path.join(work, "build")
    config_cmd = [
        "cmake", "-S", work, "-B", build_dir, "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Debug",
        "-DCMAKE_CXX_COMPILER=clang++",
        f"-DCMAKE_CXX_FLAGS={BUILD_FLAGS[0]} -O0 -g -Wall -Wextra -fdiagnostics-color=never",
    ]
    code, _out, err, timed_out = _run(config_cmd, cwd=work, timeout=min(timeout, CMAKE_TARGET_TIMEOUT_S))
    if err:
        sys.stderr.write("[cmake 配置] " + err)
        sys.stderr.flush()
    if code != 0 or timed_out:
        return code, _truncate(err), timed_out, ""
    build_cmd = ["cmake", "--build", build_dir, "--target", target, "--parallel", "2"]
    code, _out, err, timed_out = _run(build_cmd, cwd=work, timeout=min(timeout, CMAKE_TARGET_TIMEOUT_S))
    if err:
        sys.stderr.write("[cmake 构建] " + err)
        sys.stderr.flush()
    if code != 0 or timed_out:
        return code, _truncate(err), timed_out, ""
    binary = os.path.join(build_dir, target)
    return 0, "", False, binary


def _project_files() -> dict[str, str]:
    """工作区内用户文件（路径 → 内容）；排除驱动命名空间与构建目录。"""
    files: dict[str, str] = {}
    for root, dirs, names in os.walk("."):
        dirs[:] = [d for d in dirs if d not in ("__pw", "__pw_build", "build")]
        for name in names:
            path = os.path.relpath(os.path.join(root, name), ".").replace(os.sep, "/")
            try:
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                    files[path] = fh.read()
            except OSError:
                continue
    return files


def _last_error_line(stderr: str) -> str:
    for line in reversed(stderr.splitlines()):
        if "error" in line.lower():
            return line.strip()[:400]
    return (stderr.strip().splitlines() or ["未知编译错误"])[-1][:400]


def _signal_name(code) -> str | None:
    """负返回值 = 信号；映射常见致命信号（教学可读）。"""
    signals = {-6: "SIGABRT", -11: "SIGSEGV", -4: "SIGILL", -8: "SIGFPE", -15: "SIGTERM"}
    return signals.get(code) if isinstance(code, int) and code < 0 else None


def main() -> None:
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        manifest = json.load(fh)
    timeout = float(manifest.get("timeoutSec", 20))

    def _watchdog() -> None:
        time.sleep(timeout + 15)
        _emit({"kind": "cpp", "phase": "watchdog", "timedOut": True})
        os._exit(124)

    threading.Thread(target=_watchdog, daemon=True).start()

    if manifest.get("mode") == "test":
        test_mode(manifest)
    else:
        run_mode(manifest)


if __name__ == "__main__":
    main()
