"""P8.2 执行档案派生单测：混合仓库评分、构建系统判定、外部依赖识别。"""

from app.domains.course_generation.execution_profile import (
    derive_execution_profile,
    detect_language_scored,
    find_external_dependencies,
)


def test_cpp_project_with_python_scripts_stays_cpp():
    """混合仓库：主构建系统是 CMake → cpp 课程，不因辅助 Python 脚本误判。"""
    language = detect_language_scored(
        ["C++20", "CMake", "Ninja"],
        ["CMakeLists.txt", "src/main.cpp", "tools/gen.py", "scripts/build.py"],
    )
    assert language == "cpp"


def test_python_project_stays_python():
    language = detect_language_scored(
        ["Python", "pytest"], ["main.py", "tests/test_app.py", "requirements.txt"])
    assert language == "python"


def test_derive_cpp_cmake_verified():
    profile = derive_execution_profile({
        "project": {"tech_stack": ["C++17", "CMake", "GoogleTest"]},
    })
    assert profile["primaryLanguage"] == "cpp"
    assert profile["buildSystem"] == "cmake"
    assert profile["executionProfile"] == "cmake-debug"
    assert profile["testFramework"] == "ctest"
    assert profile["compilerStandard"] == "c++20"
    assert profile["verified"] is True


def test_derive_typescript_unverified():
    profile = derive_execution_profile({
        "project": {"tech_stack": ["TypeScript", "React"]},
    })
    assert profile["primaryLanguage"] == "typescript"
    assert profile["verified"] is False


def test_external_dependency_detection():
    deps = find_external_dependencies([
        "find_package(SDL2 REQUIRED)\nFetchContent_Declare(fmt)\n",
    ])
    assert any("find_package" in d for d in deps)
    assert any("FetchContent" in d for d in deps)
