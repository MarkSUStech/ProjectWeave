"""材料一致性验证器（P8.2.1，D46）：真实 Docker 构建前的确定性检查。

文件/引用/CMake 注册/测试注册/Manifest 一致性 + 泄露防护。所有检查为
确定性代码；CMake 语义的最终裁决仍归真实 Configure/File API/CTest——
本层只拦截可静态判定的不一致，给出结构化错误供修复 Agent 精确定位。
"""

from __future__ import annotations

import re

from app.domains.course_generation.lessons.change_set import content_hash

_ADD_TEST_RE = re.compile(r"add_test\s*\(\s*NAME\s+([A-Za-z0-9_.:-]+)")
_ADD_EXEC_RE = re.compile(r"add_executable\s*\(\s*([A-Za-z0-9_.-]+)")
_INCLUDE_RE = re.compile(r'#include\s+"([^"]+)"')
_PROTECTED_TEST_HINT = ("test_", "_test")


def _error(code: str, path: str, expected: str, actual: str,
           related_task: str = "", scope: str = "") -> dict:
    return {
        "errorCode": code,
        "filePath": path,
        "expected": expected,
        "actual": actual,
        "relatedTask": related_task,
        "suggestedRepairScope": scope or path,
    }


def validate_material(
    task_id: str,
    reference_files: dict[str, str],   # 合成后的参考工程（含测试）
    starter_files: dict[str, str],     # 合成后的 starter 工程（含测试）
    build_manifest: dict,
    base_files: dict[str, str],        # 上一任务已验证快照
    expected_files: list[str],
) -> list[dict]:
    """返回结构化不一致列表（空 = 通过）。"""
    errors: list[dict] = []
    manifest_tests = list(build_manifest.get("testNames") or [])
    manifest_targets = list(build_manifest.get("buildTargets") or [])
    run_targets = list(build_manifest.get("runTargets") or [])

    # ---- 文件一致性：引用的项目内头文件必须存在
    all_paths = set(reference_files)
    for path, content in reference_files.items():
        if not path.strip() or path != path.strip():
            errors.append(_error("invalid-path", path, "规范相对路径", repr(path), task_id))
        for include in _INCLUDE_RE.findall(content):
            if "/" not in include:
                continue  # 系统库或同目录包含（保守放行）
            resolved = [p for p in all_paths if p.endswith(include)]
            if not resolved:
                errors.append(_error(
                    "missing-include", path, f"被包含文件存在：{include}",
                    "工程中不存在", task_id, include))

    # ---- CMake 一致性：根 + 测试注册
    if "CMakeLists.txt" not in reference_files:
        errors.append(_error("missing-root-cmake", "CMakeLists.txt",
                             "根 CMakeLists 存在", "缺失", task_id, "CMakeLists.txt"))
    registered_tests: list[str] = []
    exec_targets: list[str] = []
    for path, content in reference_files.items():
        if "cmakelists.txt" not in path.lower():
            continue
        registered_tests.extend(_ADD_TEST_RE.findall(content))
        exec_targets.extend(_ADD_EXEC_RE.findall(content))
        exec_targets.extend(re.findall(r"add_library\s*\(\s*([A-Za-z0-9_.-]+)", content))
    for name in manifest_tests:
        if name not in registered_tests:
            errors.append(_error(
                "ctest-registration-mismatch", "tests/CMakeLists.txt",
                f"add_test NAME {name} 已注册（与 buildManifest.testNames 一致）",
                f"实际注册：{registered_tests or '（无）'}", task_id, "tests/CMakeLists.txt"))
    dup_tests = {t for t in registered_tests if registered_tests.count(t) > 1}
    if dup_tests:
        errors.append(_error("duplicate-test-registration", "tests/CMakeLists.txt",
                             "每个测试名只注册一次", f"重复：{sorted(dup_tests)}",
                             task_id, "tests/CMakeLists.txt"))
    missing_targets = [t for t in manifest_targets if t not in exec_targets]
    if missing_targets:
        errors.append(_error(
            "build-target-mismatch", "CMakeLists.txt",
            f"目标已声明：{missing_targets}",
            f"实际 add_executable：{exec_targets}", task_id, "CMakeLists.txt"))
    for target in run_targets:
        if target not in exec_targets:
            errors.append(_error("run-target-missing", "CMakeLists.txt",
                                 f"runTarget {target} 为可执行目标", "未声明",
                                 task_id, "CMakeLists.txt"))

    # ---- 回归保护：不得删除前序测试注册与已完成实现
    base_registered = set()
    for path, content in base_files.items():
        if "cmakelists.txt" in path.lower():
            base_registered.update(_ADD_TEST_RE.findall(content))
    lost = base_registered - set(registered_tests)
    if lost:
        errors.append(_error("regression-test-removed", "tests/CMakeLists.txt",
                             f"保留前序测试注册：{sorted(lost)}", "注册丢失",
                             task_id, "tests/CMakeLists.txt"))
    for path in base_files:
        if path not in reference_files and "cmakelists" not in path.lower():
            errors.append(_error("prior-file-deleted", path,
                                 "前序已验证文件保留（或以 update 显式变更）",
                                 "合成后缺失", task_id, path))

    # ---- Starter 一致性：实现区待完成 + 不泄露
    for path in expected_files:
        starter_content = starter_files.get(path)
        if starter_content is None:
            errors.append(_error("starter-missing-impl", path,
                                 "starter 包含待实现文件", "缺失", task_id, path))
            continue
        reference_content = reference_files.get(path, "")
        if starter_content.strip() == reference_content.strip():
            errors.append(_error("starter-leaks-answer", path,
                                 "starter 为挖空版（TODO/默认返回）",
                                 "与参考实现完全一致", task_id, path))
        elif "TODO" not in starter_content and _is_impl(path):
            errors.append(_error("starter-no-todo", path,
                                 "待实现区域含 TODO 标记", "无 TODO", task_id, path))
    # starter 引用的头文件必须同样存在
    starter_paths = set(starter_files)
    for path, content in starter_files.items():
        for include in _INCLUDE_RE.findall(content):
            if "/" not in include:
                continue
            if not any(p.endswith(include) for p in starter_paths):
                errors.append(_error("starter-missing-include", path,
                                     f"被包含文件存在：{include}", "starter 工程缺失",
                                     task_id, include))

    # 注：测试↔测试源的命名关联不做静态猜测（太脆）——由 add_test 注册
    # 检查 + 真实 CTest 发现裁决（ctest-selection 会明确报不存在的名字）。
    return errors


def _is_impl(path: str) -> bool:
    return path.lower().endswith((".cpp", ".cc", ".cxx"))


def _has_test_source(files: dict[str, str], test_name: str) -> bool:
    """测试名与测试源文件的命名关联（ctest 名 world_update ↔ test_world.cpp /
    world_tests 等；启发式：词干交集）。"""
    stems = set()
    for path in files:
        base = path.rsplit("/", 1)[-1].lower()
        if not (_is_impl(path) and ("test" in base)):
            continue
        stems.update(set(re.findall(r"[a-z0-9]+", base)) - {"cpp", "cc", "cxx", "test", "tests"})
    name_stems = set(re.findall(r"[a-z0-9]+", test_name.lower())) - {"test", "tests"}
    return bool(name_stems & stems) if stems else False


def snapshot_hash_of(files: dict[str, str]) -> str:
    """整快照指纹（有序路径+内容哈希）。"""
    payload = ";".join(f"{p}:{content_hash(c)}" for p, c in sorted(files.items()))
    return content_hash(payload)
