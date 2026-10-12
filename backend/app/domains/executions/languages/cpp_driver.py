"""ProjectWeave 沙箱执行驱动（C++，P4.2c / P8.1）。

随每次执行打包进容器（__pw/driver.py），不是用户代码。
流程：PREPARE（源集选择）→ BUILD（clang++ 或 cmake+ninja）→ RUN/TEST → 标记回传。

阶段语义（与后端 phases 对应）：
- build 失败 → 不进入 RUN，编译器输出原样保留 + 后端解析诊断；
- run 失败/超时/信号 → 退出码与 timedOut 如实上报；
- test = 逐测试可执行程序（编译 + 运行 + 退出码），空测试不判通过。

源码选择策略（确定性，无 LLM）：
- run：入口 + 全部非测试翻译单元（多 main 交给链接器报真实错误）；
- test：测试文件 + 全部非测试且不含 int main 的翻译单元
  （排除程序入口，避免多 main 链接冲突——D35）。

P8.1 CMake 项目 profile（buildSystem=cmake）：
- discover：写 File API query → cmake configure → 解析 codemodel 目标；
- build/run：configure → cmake --build --target（参数数组，无 shell 拼接）；
  run 的产物路径来自 File API，且必须在构建目录内（realpath 校验）；
- test：configure → 全量构建 → ctest（发现 json-v1 + 执行 --output-junit）；
  JUnit 解析有界，0 个测试执行不得判通过。

约束：不下载外部依赖（网络本就禁用）；所有命令为参数数组；目标名白名单校验。
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
CMAKE_CONFIGURE_TIMEOUT_S = 120
CMAKE_BUILD_TIMEOUT_S = 240
CTEST_TIMEOUT_S = 120
# 目标名白名单（防注入/路径穿越；与后端 Pydantic 同规则）
TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")
# File API 回复目录（相对构建目录）
FILE_API_DIR = os.path.join(".cmake", "api", "v1", "reply")
QUERY_DIR = os.path.join(".cmake", "api", "v1", "query")
MAX_JUNIT_BYTES = 2 * 1024 * 1024
MAX_TARGETS = 200
MAX_SOURCES_PER_TARGET = 400


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
    """run 模式源集（P5.1 修订 D35）：入口 + 非测试且不含 int main( 的翻译单元。

    排除其他含 main 的 TU：它们是独立程序（课程各任务/脚手架各带 main），
    链接进来只会产生重复符号或被其未完成 TODO 拖垮；排除后入口的真实
    多文件依赖（无 main 的实现单元）仍然全部参与链接。确定性内容启发式，
    与测试模式的排除策略一致。
    """
    others = sorted(
        p for p in files
        if not is_test_file(p)
        and os.path.splitext(p)[1] in SOURCE_EXTENSIONS
        and p != entry
        and not MAIN_RE.search(files.get(p, ""))
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
    """direct profile：clang++ 直接编译运行（P8.1 起不再自动猜测 CMake 目标）。"""
    timeout = float(manifest.get("timeoutSec", 20))
    entry = manifest["entry"]
    stdin_text = manifest.get("stdin", "")
    work = os.getcwd()
    files = _project_files()

    os.makedirs(os.path.join(work, "__pw_build"), exist_ok=True)
    binary = os.path.join(work, "__pw_build", "app")
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


# ---------------------------------------------------------------- CMake 项目 profile（P8.1）


class FileApiError(RuntimeError):
    """CMake File API 回复缺失/非法——不得伪造目标列表。"""


def _cmake_version() -> str:
    code, out, _err, _to = _run(["cmake", "--version"], cwd=".", timeout=15)
    if code == 0 and out:
        return out.splitlines()[0].strip()
    return ""


def _cmake_configure(work: str, build_dir: str, with_query: bool, timeout: float):
    """真实 CMake Configure（参数数组）。with_query 时先写 File API codemodel query。"""
    os.makedirs(build_dir, exist_ok=True)
    if with_query:
        query = os.path.join(build_dir, QUERY_DIR, "codemodel-v2")
        os.makedirs(os.path.dirname(query), exist_ok=True)
        with open(query, "w", encoding="utf-8"):
            pass  # 空 query 文件 = 被动请求 codemodel v2
    cmd = [
        "cmake", "-S", work, "-B", build_dir, "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Debug",
        "-DCMAKE_CXX_COMPILER=clang++",
        "-DCMAKE_CXX_FLAGS=" + " ".join(BUILD_FLAGS),
    ]
    return _run(cmd, cwd=work, timeout=min(timeout, CMAKE_CONFIGURE_TIMEOUT_S))


def parse_file_api_targets(work: str, build_dir: str) -> list[dict]:
    """解析 File API reply（index → codemodel → target 文件）为结构化目标列表。

    纯数据变换（可离线单测）：只读真实回复，缺文件/非法 JSON → FileApiError。
    """
    reply_dir = os.path.join(build_dir, FILE_API_DIR)
    if not os.path.isdir(reply_dir):
        raise FileApiError("CMake File API 无回复目录（configure 未完成或 CMake 版本过旧）")
    index_files = sorted(
        f for f in os.listdir(reply_dir) if f.startswith("index-") and f.endswith(".json")
    )
    if not index_files:
        raise FileApiError("CMake File API 无 index 回复")
    with open(os.path.join(reply_dir, index_files[-1]), encoding="utf-8") as fh:
        index = json.load(fh)
    # reply 是以 query 名为键的字典（真实格式）；容错兼容列表形状
    reply_obj = index.get("reply") or {}
    entries = reply_obj.values() if isinstance(reply_obj, dict) else reply_obj
    codemodel_file = next(
        (r.get("jsonFile") for r in entries
         if isinstance(r, dict) and r.get("kind") == "codemodel" and r.get("jsonFile")),
        None,
    )
    if not codemodel_file:
        raise FileApiError("File API 回复中无 codemodel（CMake 版本不支持 codemodel-v2）")
    with open(os.path.join(reply_dir, codemodel_file), encoding="utf-8") as fh:
        codemodel = json.load(fh)

    configs = codemodel.get("configurations") or []
    if not configs:
        raise FileApiError("codemodel 无 configurations")
    config = configs[0]
    trefs = config.get("targets") or []
    id_to_name = {t.get("id"): t.get("name", "") for t in trefs if t.get("id")}

    def _load(path: str) -> dict:
        with open(os.path.join(reply_dir, path), encoding="utf-8") as fh:
            return json.load(fh)

    # 真实语义（已对实物验证）：paths.source/build、sources[].path 相对顶层源目录，
    # artifacts[].path 相对顶层构建目录（build/）。
    def _proj_rel(rel: str) -> str:
        return os.path.normpath(rel).replace(os.sep, "/")

    targets: list[dict] = []
    for tref in trefs[:MAX_TARGETS]:
        if not tref.get("jsonFile"):
            continue
        try:
            data = _load(tref["jsonFile"])
        except (OSError, json.JSONDecodeError) as exc:
            raise FileApiError(f"目标文件解析失败：{tref.get('name')}（{exc}）") from exc
        paths = data.get("paths") or {}
        artifacts_proj = [_proj_rel(a.get("path", "")) for a in data.get("artifacts") or [] if a.get("path")]
        artifacts_abs = [os.path.join(build_dir, a) for a in artifacts_proj]
        targets.append({
            "name": data.get("name") or tref.get("name", ""),
            "type": data.get("type", "UNKNOWN"),
            # discover 阶段未构建：可运行性按 File API 声明判定
            # （类型 EXECUTABLE 且声明了产物）；真实存在性由 run 流程构建后校验。
            "runnable": data.get("type") == "EXECUTABLE" and bool(artifacts_proj),
            "sourceDirectory": _proj_rel(paths.get("source", "")),
            "buildDirectory": _proj_rel(os.path.join("build", paths.get("build", ""))),
            "sources": [
                _proj_rel(s.get("path", ""))
                for s in (data.get("sources") or [])[:MAX_SOURCES_PER_TARGET]
                if s.get("path")
            ],
            "artifacts": [_proj_rel(os.path.join("build", a)) for a in artifacts_proj],
            "dependencies": [
                id_to_name[d.get("id")] for d in data.get("dependencies") or []
                if d.get("id") in id_to_name
            ],
            "configuration": config.get("name", ""),
        })
    if not targets:
        raise FileApiError("File API 未返回任何目标")
    return targets


def _find_target(targets: list[dict], name: str) -> dict:
    for target in targets:
        if target["name"] == name:
            return target
    raise KeyError(name)


def _emit_cmake_failed(stage: str, code, err: str, timed_out: bool) -> None:
    _emit({"kind": "cpp", "phase": "cmake-failed", "stage": stage, "exitCode": code,
           "rawStderr": _truncate(err), "timedOut": timed_out})


def cmake_discover_mode(manifest: dict) -> None:
    """discover：Configure + File API 目标发现（不构建）。"""
    timeout = float(manifest.get("timeoutSec", 60))
    work = os.getcwd()
    build_dir = os.path.join(work, "build")
    config_start = time.monotonic()
    code, _out, err, timed_out = _cmake_configure(work, build_dir, with_query=True, timeout=timeout)
    config_ms = int((time.monotonic() - config_start) * 1000)
    if err:
        sys.stderr.write("[cmake 配置] " + err)
        sys.stderr.flush()
    if code != 0 or timed_out:
        _emit_cmake_failed("configure", code, err, timed_out)
        sys.exit(code or 1)
    try:
        targets = parse_file_api_targets(work, build_dir)
    except FileApiError as exc:
        _emit({"kind": "cpp", "phase": "cmake-failed", "stage": "file-api",
               "exitCode": 1, "rawStderr": str(exc), "timedOut": False})
        sys.stderr.write(f"[file-api] {exc}\n")
        sys.exit(1)
    _emit({
        "kind": "cpp", "phase": "cmake-discovered", "configureExit": 0,
        "configureMs": config_ms, "generator": "Ninja",
        "cmakeVersion": _cmake_version(), "targets": targets,
    })
    sys.exit(0)


def _cmake_target_build(work: str, build_dir: str, target: str, timeout: float):
    """构建指定目标（参数数组，白名单名）。Ninja 把编译错误打到 stdout，
    因此失败回传 stdout+stderr 合并输出（诊断解析需要 clang 行）。"""
    cmd = ["cmake", "--build", build_dir, "--target", target, "--parallel", "2"]
    code, out, err, timed_out = _run(
        cmd, cwd=work, timeout=min(timeout, CMAKE_BUILD_TIMEOUT_S))
    combined = (out or "") + (err or "")
    if combined:
        sys.stderr.write("[cmake 构建] " + combined)
        sys.stderr.flush()
    return code, combined, timed_out


def cmake_build_run_mode(manifest: dict) -> None:
    """build / run：Configure（含 query）→ Build 目标 →（run）执行 File API 产物。"""
    timeout = float(manifest.get("timeoutSec", 120))
    action = manifest.get("cmakeAction") or "run"
    target_name = manifest.get("targetName") or ""
    if not TARGET_NAME_RE.match(target_name):
        _emit({"kind": "cpp", "phase": "cmake-failed", "stage": "validate",
               "exitCode": 2, "rawStderr": f"非法目标名：{target_name!r}", "timedOut": False})
        sys.exit(2)

    work = os.getcwd()
    build_dir = os.path.join(work, "build")
    code, _out, err, timed_out = _cmake_configure(work, build_dir, with_query=True, timeout=timeout)
    if err:
        sys.stderr.write("[cmake 配置] " + err)
        sys.stderr.flush()
    if code != 0 or timed_out:
        _emit_cmake_failed("configure", code, err, timed_out)
        sys.exit(code or 1)

    try:
        targets = parse_file_api_targets(work, build_dir)
        target = _find_target(targets, target_name)
    except FileApiError as exc:
        _emit({"kind": "cpp", "phase": "cmake-failed", "stage": "file-api",
               "exitCode": 1, "rawStderr": str(exc), "timedOut": False})
        sys.exit(1)
    except KeyError:
        known = ", ".join(sorted(t["name"] for t in targets)[:20])
        _emit({"kind": "cpp", "phase": "cmake-failed", "stage": "target-not-found",
               "exitCode": 2, "target": target_name,
               "rawStderr": f"目标不存在：{target_name}（已发现：{known}）", "timedOut": False})
        sys.exit(2)

    build_start = time.monotonic()
    code, err, timed_out = _cmake_target_build(work, build_dir, target_name, timeout)
    build_ms = int((time.monotonic() - build_start) * 1000)
    if code != 0 or timed_out:
        _emit({"kind": "cpp", "phase": "cmake-failed", "stage": "build",
               "exitCode": code, "target": target_name,
               "rawStderr": _truncate(err), "buildMs": build_ms, "timedOut": timed_out})
        sys.exit(code or 1)

    if action == "build":
        # 构建完成即止：产物以 File API 记录为准（文件在构建目录内已真实生成）
        artifacts = [a for a in target["artifacts"] if a]
        _emit({"kind": "cpp", "phase": "cmake-built", "target": target_name,
               "buildMs": build_ms, "artifacts": artifacts,
               "cmakeVersion": _cmake_version(), "generator": "Ninja"})
        sys.exit(0)

    # ---- run：产物路径必须来自 File API 且位于构建目录内 ----
    if target["type"] != "EXECUTABLE":
        _emit({"kind": "cpp", "phase": "cmake-failed", "stage": "target-not-runnable",
               "exitCode": 2, "target": target_name,
               "rawStderr": f"目标 {target_name} 类型为 {target['type']}，不可运行（仅 EXECUTABLE）",
               "timedOut": False})
        sys.exit(2)
    artifacts_abs = [
        os.path.normpath(os.path.join(work, a)) for a in target["artifacts"] if a
    ]
    build_dir_abs = os.path.realpath(build_dir)
    artifact_abs = next(
        (p for p in artifacts_abs
         if os.path.commonpath([os.path.realpath(p), build_dir_abs]) == build_dir_abs
         and os.path.isfile(p)),
        None,
    )
    if artifact_abs is None:
        _emit({"kind": "cpp", "phase": "cmake-failed", "stage": "artifact-missing",
               "exitCode": 2, "target": target_name,
               "rawStderr": "File API 产物在构建目录内不存在（构建可能未生成可执行文件）",
               "timedOut": False})
        sys.exit(2)

    run_start = time.monotonic()
    code, _out, _err, timed_out = _run_streaming(
        [artifact_abs], cwd=work, timeout=timeout, stdin_text=manifest.get("stdin", "")
    )
    run_ms = int((time.monotonic() - run_start) * 1000)
    _emit({"kind": "cpp", "phase": "cmake-ran", "target": target_name,
           "artifact": os.path.relpath(artifact_abs, work).replace(os.sep, "/"),
           "runExit": code, "timedOut": timed_out, "runMs": run_ms,
           "signal": _signal_name(code), "buildMs": build_ms,
           "cmakeVersion": _cmake_version(), "generator": "Ninja"})
    sys.exit(code if isinstance(code, int) and code >= 0 else (124 if timed_out else 1))


def _ctest_discover(work: str, build_dir: str) -> list[dict]:
    """ctest --show-only=json-v1 → 测试列表（真实发现，缺 JSON 则报错）。"""
    code, out, err, timed_out = _run(
        ["ctest", "--test-dir", build_dir, "--show-only=json-v1"], cwd=work, timeout=30)
    if code != 0 or timed_out:
        raise FileApiError(f"ctest 发现已失败：{(err or out).strip()[:300]}")
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        raise FileApiError(f"ctest 发现输出非 JSON：{exc}") from exc
    return payload.get("tests") or []


def _parse_junit(path: str) -> list[dict] | None:
    """CTest JUnit XML → 逐测试结果（有界：文件大小上限 + 解析失败返回 None）。"""
    import xml.etree.ElementTree as ET

    if not os.path.isfile(path):
        return None
    if os.path.getsize(path) > MAX_JUNIT_BYTES:
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    results: list[dict] = []
    for case in root.iter("testcase"):
        name = case.get("name", "")
        duration_ms = int((float(case.get("time", 0) or 0)) * 1000)
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None or error is not None:
            node = failure if failure is not None else error
            status = "failed" if failure is not None else "error"
            # ctest JUnit 的 failure message 常为空，断言输出在 system-out/system-err
            message = (node.get("message") or (node.text or "")).strip()
            if not message:
                for tag in ("system-out", "system-err"):
                    node = case.find(tag)
                    if node is not None and (node.text or "").strip():
                        message = node.text.strip()
                        break
        elif skipped is not None:
            status, message = "skipped", (skipped.get("message") or "").strip()
        else:
            status, message = "passed", ""
        results.append({
            "name": name, "status": status, "durationMs": duration_ms,
            "error": _truncate(message) if message else None,
        })
    return results


def cmake_test_mode(manifest: dict) -> None:
    """CTest 流程：Configure → 全量构建 → 发现 → 执行（JUnit）→ 结构化结果。"""
    timeout = float(manifest.get("timeoutSec", 120))
    selected = [t for t in manifest.get("selectedTests") or [] if TARGET_NAME_RE.match(t)]
    work = os.getcwd()
    build_dir = os.path.join(work, "build")

    code, _out, err, timed_out = _cmake_configure(work, build_dir, with_query=False, timeout=timeout)
    if err:
        sys.stderr.write("[cmake 配置] " + err)
        sys.stderr.flush()
    if code != 0 or timed_out:
        _emit_cmake_failed("configure", code, err, timed_out)
        sys.exit(code or 1)

    build_start = time.monotonic()
    code, out, err, timed_out = _run(
        ["cmake", "--build", build_dir, "--parallel", "2"], cwd=work,
        timeout=min(timeout, CMAKE_BUILD_TIMEOUT_S))
    build_ms = int((time.monotonic() - build_start) * 1000)
    combined = (out or "") + (err or "")
    if combined:
        sys.stderr.write("[cmake 构建] " + combined)
        sys.stderr.flush()
    err = combined
    if code != 0 or timed_out:
        _emit({"kind": "cpp", "phase": "cmake-failed", "stage": "build", "exitCode": code,
               "rawStderr": _truncate(err), "buildMs": build_ms, "timedOut": timed_out})
        sys.exit(code or 1)

    try:
        discovered = _ctest_discover(work, build_dir)
    except FileApiError as exc:
        _emit({"kind": "cpp", "phase": "cmake-failed", "stage": "ctest-discovery",
               "exitCode": 1, "rawStderr": str(exc), "timedOut": False})
        sys.exit(1)
    discovered_names = [t.get("name", "") for t in discovered]

    junit_path = os.path.join(build_dir, "__pw_junit.xml")
    cmd = ["ctest", "--test-dir", build_dir, "--output-on-failure",
           "--output-junit", junit_path]
    if selected:
        # 选择执行：逐名转义后以 -R 正则传入（ctest 无逐名参数）
        import re as _re

        pattern = "|".join(_re.escape(name) for name in selected)
        cmd += ["-R", pattern]
    ctest_start = time.monotonic()
    code, out, err, timed_out = _run(cmd, cwd=work, timeout=min(timeout, CTEST_TIMEOUT_S))
    ctest_ms = int((time.monotonic() - ctest_start) * 1000)
    if err:
        sys.stderr.write("[ctest] " + err)
        sys.stderr.flush()

    executed = _parse_junit(junit_path)
    if executed is None:
        # JUnit 缺失/非法：不得把结果伪装成通过——如实报告 ctest 原始输出
        _emit({"kind": "cpp", "phase": "cmake-tested", "ctestExit": code,
               "tests": [], "discovered": discovered_names,
               "junitError": "CTest 结果报告缺失或无效（未判定为通过）",
               "stdoutTail": _truncate(out), "timedOut": timed_out})
        sys.exit(1)

    # ctest 退出码非 0 且无任何失败记录 → 结果不完整（如选择的名字不存在）
    by_name = {r["name"]: r for r in executed}
    not_run = [
        {"name": n, "status": "skipped", "durationMs": 0,
         "error": "未执行（Not Run：可能被过滤或禁用）"}
        for n in discovered_names if n not in by_name
    ]
    _emit({"kind": "cpp", "phase": "cmake-tested", "ctestExit": code,
           "tests": [*executed, *not_run], "discovered": discovered_names,
           "ctestMs": ctest_ms, "buildMs": build_ms, "timedOut": timed_out,
           "cmakeVersion": _cmake_version(), "generator": "Ninja"})
    all_ok = (code == 0 and executed
              and all(r["status"] == "passed" for r in executed)
              and not any(t.get("status") != "passed" for t in not_run))
    sys.exit(0 if all_ok else 1)


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

    if (manifest.get("buildSystem") or "direct") == "cmake":
        if manifest.get("mode") == "test":
            cmake_test_mode(manifest)
        elif (manifest.get("cmakeAction") or "run") == "discover":
            cmake_discover_mode(manifest)
        else:
            cmake_build_run_mode(manifest)
    elif manifest.get("mode") == "test":
        test_mode(manifest)
    else:
        run_mode(manifest)


if __name__ == "__main__":
    main()
