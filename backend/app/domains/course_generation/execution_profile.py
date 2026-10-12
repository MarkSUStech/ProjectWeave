"""课程执行档案（P8.2，D45）：从蓝图确定性派生执行环境信息。

不信任模型自述：语言/构建系统由技术栈与文件证据评分决定，且必须落在
沙箱已验证能力内（SANDBOX_VERIFIED）。混合语言仓库按主要构建系统判主语言，
不因辅助脚本误判。
"""

from __future__ import annotations

import re

# 各语言指示词（技术栈字符串/证据路径加权）
_CPP_HINTS = re.compile(r"\bc\+\+\b|\bcpp\b|clang|cmake|ninja|libc\+\+|stdc\+\+|\.cpp\b|\.hpp\b", re.IGNORECASE)
_PY_HINTS = re.compile(r"\bpython\b|pytest|pip|\.py\b|django|flask|numpy", re.IGNORECASE)
_TS_HINTS = re.compile(r"\btypescript\b|\bjavascript\b|\bnode\b|\.tsx?\b|vitest|jest", re.IGNORECASE)
_CMAKE_HINTS = re.compile(r"\bcmake\b|CMakeLists|\.cmake\b|ninja", re.IGNORECASE)

# 课程沙箱已验证的语言×构建系统组合（真实 Docker 全链验证过）
VERIFIED_PROFILES = {
    ("python", "direct"),   # pytest 直跑（P7.2）
    ("cpp", "cmake"),       # CMake/CTest（P8.1/P8.2）
    ("cpp", "direct"),      # Clang 直编单文件练习（P4.2c）
}

# 外部依赖/环境指示（当前沙箱无网络，无法自动获取 → 进入 nonGoals 或 unsupported）
EXTERNAL_DEP_HINTS = (
    re.compile(r"find_package\s*\(", re.IGNORECASE),
    re.compile(r"FetchContent", re.IGNORECASE),
    re.compile(r"\bvcpkg\b|\bconan\b", re.IGNORECASE),
    re.compile(r"\b(SDL|SDL2|SDL3|Qt[456]?|OpenGL|Vulkan|CUDA|OpenCV|Boost)\b", re.IGNORECASE),
    re.compile(r"ExternalProject", re.IGNORECASE),
)


def detect_language_scored(tech_stack: list[str], file_paths: list[str] | None = None) -> str:
    """评分式主语言判定：技术栈词频 + 文件扩展名证据（打破 python 先验优先）。"""
    text = " ".join(str(s) for s in tech_stack or [])
    paths = " ".join(file_paths or [])
    scores = {
        "python": len(_PY_HINTS.findall(text)) * 2 + len(_PY_HINTS.findall(paths)),
        "cpp": len(_CPP_HINTS.findall(text)) * 2 + len(_CPP_HINTS.findall(paths)),
        "typescript": len(_TS_HINTS.findall(text)) * 2 + len(_TS_HINTS.findall(paths)),
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "python"


def detect_build_system(language: str, tech_stack: list[str],
                        file_paths: list[str] | None = None) -> str:
    """C++ 课程默认 CMake（出现 cmake 迹象或含多模块工程时）；其余 direct。"""
    if language != "cpp":
        return "direct"
    text = " ".join(str(s) for s in tech_stack or [])
    paths = " ".join(file_paths or [])
    if _CMAKE_HINTS.search(text) or "CMakeLists.txt" in paths:
        return "cmake"
    return "cmake" if language == "cpp" else "direct"


def find_external_dependencies(cmake_texts: list[str]) -> list[str]:
    """扫描构建脚本中的外部依赖痕迹（无法联网获取 → 必须列入 nonGoals）。"""
    found: list[str] = []
    joined = "\n".join(cmake_texts)
    for pattern in EXTERNAL_DEP_HINTS:
        match = pattern.search(joined)
        if match:
            found.append(match.group(0))
    return sorted(set(found))


def derive_execution_profile(blueprint: dict) -> dict:
    """蓝图 → 确定性执行档案（服务端判定，非模型自述）。

    返回 {primaryLanguage, buildSystem, executionProfile, compilerStandard,
    testFramework, verified}。verified=False 的组合在课程内容生成前被拒绝。
    """
    project = blueprint.get("project") or {}
    tech_stack = project.get("tech_stack") or project.get("techStack") or []
    evidence_paths = [e.get("path", "") for e in project.get("evidence") or []]

    language = detect_language_scored(tech_stack, evidence_paths)
    build_system = detect_build_system(language, tech_stack, evidence_paths)
    verified = (language, build_system) in VERIFIED_PROFILES

    if language == "cpp":
        test_framework = "ctest"
        compiler_standard = "c++20"
        execution_profile = "cmake-debug" if build_system == "cmake" else "clang-direct"
    elif language == "typescript":
        test_framework, compiler_standard = "browser-worker", "es2022"
        execution_profile = "browser"
    else:
        test_framework, compiler_standard = "pytest", "py312"
        execution_profile = "docker-pytest"

    return {
        "primaryLanguage": language,
        "buildSystem": build_system,
        "executionProfile": execution_profile,
        "compilerStandard": compiler_standard,
        "testFramework": test_framework,
        "dependencyRequirements": [],
        "verified": verified,
    }


def unsupported_profile_message(profile: dict) -> str:
    return (f"课程执行环境暂不支持 {profile.get('primaryLanguage')}/"
            f"{profile.get('buildSystem')}（沙箱已验证：Python/pytest 与 C++/CMake）。"
            "为不伪造成功，已拒绝生成课程内容。")
