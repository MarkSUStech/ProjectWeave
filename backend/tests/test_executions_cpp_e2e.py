"""C++ 沙箱真实端到端验收（选入：PW_SANDBOX_E2E=1）。

覆盖任务验收 A-I / K：
A 单文件 / B 多翻译单元 / C 缺头文件诊断 / D 链接错误 / E stdin /
F 超时清理 / G 测试成败与空测试 / H CMake+Ninja / I 编译失败不报成功 /
K 容器安全限制在 C++ 镜像下同样生效。
前置：docker build -t projectweave-sandbox-cpp:clang15-bookworm backend/sandbox/cpp
"""

import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.domains.executions import service
from app.domains.executions.sandbox.docker_sandbox import LABEL_KEY

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="C++ 沙箱 E2E 需 PW_SANDBOX_E2E=1 与镜像 projectweave-sandbox-cpp:clang15-bookworm",
)

IMAGE = "projectweave-sandbox-cpp:clang15-bookworm"

HELLO = "#include <iostream>\n\nint main() {\n    std::cout << \"hello cpp\" << std::endl;\n    return 0;\n}\n"


@pytest.fixture()
def e2e_client(client: TestClient, db_session):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    service.set_session_factory(factory)
    yield client
    from app.core.db import SessionLocal

    service.set_session_factory(SessionLocal)


def _leftover_containers() -> list[str]:
    proc = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"label={LABEL_KEY}=1", "-q"],
        capture_output=True, text=True, timeout=20,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _create(client: TestClient, **overrides):
    payload = {
        "language": "cpp",
        "mode": "run",
        "entryPoint": "src/main.cpp",
        "files": {"src/main.cpp": HELLO},
        "timeoutMs": 30000,
    }
    payload.update(overrides)
    resp = client.post("/api/v1/executions", json=payload)
    assert resp.status_code == 202, resp.text
    return resp.json()["id"]


def _wait(client: TestClient, exec_id: str, timeout_s: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/api/v1/executions/{exec_id}").json()
        if data["status"] in {"completed", "failed", "timed-out", "cancelled"}:
            return data
        time.sleep(0.25)
    pytest.fail("执行未在期限内到达终态")


# ---------------------------------------------------------------- A/B/C/D/E


def test_a_single_file_run(e2e_client: TestClient):
    final = _wait(e2e_client, _create(e2e_client))
    assert final["status"] == "completed"
    assert final["exitCode"] == 0
    assert "hello cpp" in final["stdout"]
    assert final["sandbox"]["image"] == IMAGE
    # 两阶段：build + run 均 completed
    phases = {p["name"]: p for p in final["phases"]}
    assert phases["build"]["status"] == "completed"
    assert phases["run"]["status"] == "completed"


def test_b_multi_translation_unit(e2e_client: TestClient):
    files = {
        "src/math.hpp": "#pragma once\nint add(int a, int b);\n",
        "src/math.cpp": '#include "math.hpp"\nint add(int a, int b) { return a + b; }\n',
        "src/main.cpp": '#include <iostream>\n#include "math.hpp"\nint main() { std::cout << add(2, 3) << std::endl; }\n',
    }
    final = _wait(e2e_client, _create(e2e_client, files=files))
    assert final["status"] == "completed"
    assert final["exitCode"] == 0
    assert "5" in final["stdout"]


def test_c_missing_header_build_diagnostic(e2e_client: TestClient):
    files = {"src/main.cpp": '#include "nope.hpp"\nint main() { return 0; }\n'}
    final = _wait(e2e_client, _create(e2e_client, files=files))
    # 编译失败：会话 completed（生命周期跑完）但结果不成功（验收 I）
    assert final["status"] == "completed"
    assert final["exitCode"] != 0
    diag = final["diagnostics"][0]
    assert diag["source"] == "build"
    assert diag["file"] == "src/main.cpp"
    assert diag["line"] == 1
    assert "nope.hpp" in diag["message"]
    phases = {p["name"]: p for p in final["phases"]}
    assert phases["build"]["status"] == "failed"
    assert phases["run"]["status"] == "skipped"


def test_d_undefined_symbol_link_error(e2e_client: TestClient):
    files = {
        "src/math.hpp": "#pragma once\nint add(int a, int b);\n",
        "src/main.cpp": '#include <iostream>\n#include "math.hpp"\nint main() { std::cout << add(1, 2) << std::endl; }\n',
    }
    final = _wait(e2e_client, _create(e2e_client, files=files))
    assert final["exitCode"] != 0
    build_diags = [d for d in final["diagnostics"] if d["source"] == "build"]
    assert build_diags, "链接错误必须产生 build 诊断"
    assert any("add" in d["message"] for d in build_diags)
    assert {p["name"]: p for p in final["phases"]}["run"]["status"] == "skipped"


def test_e_cin_reads_stdin(e2e_client: TestClient):
    files = {
        "src/main.cpp": (
            "#include <iostream>\n#include <string>\n"
            "int main() { std::string s; std::cin >> s; std::cout << \"hi \" << s << std::endl; }\n"
        )
    }
    final = _wait(e2e_client, _create(e2e_client, files=files, stdin="ProjectWeave"))
    assert final["exitCode"] == 0
    assert "hi ProjectWeave" in final["stdout"]


def test_runtime_crash_reports_signal(e2e_client: TestClient):
    files = {"src/main.cpp": "int main() { int* p = nullptr; *p = 1; return 0; }\n"}
    final = _wait(e2e_client, _create(e2e_client, files=files))
    assert final["status"] == "completed"
    assert final["exitCode"] not in (0, None)
    assert any("SIGSEGV" in d["message"] for d in final["diagnostics"])


# ---------------------------------------------------------------- F 超时


def test_f_infinite_loop_timeout_and_cleanup(e2e_client: TestClient):
    files = {"src/main.cpp": "int main() { while (true) {} }\n"}
    exec_id = _create(e2e_client, files=files, timeoutMs=4000)
    final = _wait(e2e_client, exec_id, timeout_s=90)
    assert final["status"] == "timed-out"
    assert final["timedOut"] is True
    time.sleep(1.0)
    assert _leftover_containers() == [], "超时后不应遗留沙箱容器"


# ---------------------------------------------------------------- G 测试


def test_g_tests_pass_fail_empty(e2e_client: TestClient):
    files = {
        "src/math.hpp": "#pragma once\nint add(int a, int b);\n",
        "src/math.cpp": '#include "math.hpp"\nint add(int a, int b) { return a + b; }\n',
        "src/main.cpp": '#include <iostream>\n#include "math.hpp"\nint main() { std::cout << add(1, 1); }\n',
        # 通过：退出 0 且有输出
        "tests/test_ok.cpp": (
            '#include <iostream>\n#include "../src/math.hpp"\n'
            'int main() { int r = add(1, 2); std::cout << "check add(1,2)==3: " << (r == 3 ? "ok" : "bad") << std::endl; return r == 3 ? 0 : 1; }\n'
        ),
        # 失败：断言不成立 → 非零退出
        "tests/test_bad.cpp": (
            '#include <iostream>\n#include "../src/math.hpp"\n'
            'int main() { int r = add(1, 2); std::cout << "expect 99 got " << r << std::endl; return r == 99 ? 0 : 1; }\n'
        ),
        # 空测试：退出 0 但无输出 → 不判通过
        "tests/test_empty.cpp": '#include "../src/math.hpp"\nint main() { add(0, 0); return 0; }\n',
    }
    exec_id = _create(
        e2e_client, mode="test", entryPoint=None,
        testPaths=["tests/test_ok.cpp", "tests/test_bad.cpp", "tests/test_empty.cpp"],
        files=files,
    )
    final = _wait(e2e_client, exec_id)
    assert final["status"] == "completed"
    results = {r["path"]: r for r in final["testResults"]}
    assert results["tests/test_ok.cpp"]["status"] == "passed"
    assert results["tests/test_bad.cpp"]["status"] == "failed"
    assert results["tests/test_empty.cpp"]["status"] == "error"
    assert "空测试" in results["tests/test_empty.cpp"]["error"]
    # 测试元数据完整：名称/退出码/时长/失败信息
    ok_case = results["tests/test_ok.cpp"]["cases"][0]
    bad_case = results["tests/test_bad.cpp"]["cases"][0]
    assert ok_case["durationMs"] >= 0
    assert "断言失败" in bad_case["error"] and "退出码 1" in bad_case["error"]
    assert final["exitCode"] != 0  # 整体不通过


def test_g_test_compile_failure_is_error(e2e_client: TestClient):
    files = {"tests/broken.cpp": "int main() { return 0 "}  # 语法错误
    exec_id = _create(e2e_client, mode="test", entryPoint=None, testPaths=["tests/broken.cpp"], files=files)
    final = _wait(e2e_client, exec_id)
    results = final["testResults"]
    assert results[0]["status"] == "error"
    assert "编译失败" in results[0]["error"]


# ---------------------------------------------------------------- H CMake


def test_h_cmake_ninja_multi_file(e2e_client: TestClient):
    files = {
        "CMakeLists.txt": (
            "cmake_minimum_required(VERSION 3.20)\n"
            "project(demo LANGUAGES CXX)\n"
            "set(CMAKE_CXX_STANDARD 20)\n"
            "add_executable(demo src/math.cpp src/main.cpp)\n"
        ),
        "src/math.hpp": "#pragma once\nint add(int a, int b);\n",
        "src/math.cpp": '#include "math.hpp"\nint add(int a, int b) { return a + b; }\n',
        "src/main.cpp": '#include <iostream>\n#include "math.hpp"\nint main() { std::cout << "cmake:" << add(20, 2) << std::endl; }\n',
    }
    final = _wait(e2e_client, _create(e2e_client, files=files), timeout_s=120)
    assert final["status"] == "completed"
    assert final["exitCode"] == 0
    assert "cmake:22" in final["stdout"]


def test_h_cmake_config_failure_distinguished(e2e_client: TestClient):
    # CMake 配置失败（语法错误）→ build failed + run skipped，不冒充运行结果
    files = {
        "CMakeLists.txt": "this_is_not_cmake_syntax(\n",
        "src/main.cpp": HELLO,
    }
    final = _wait(e2e_client, _create(e2e_client, files=files), timeout_s=120)
    assert final["exitCode"] != 0
    phases = {p["name"]: p for p in final["phases"]}
    assert phases["build"]["status"] == "failed"
    assert phases["run"]["status"] == "skipped"


# ---------------------------------------------------------------- K 安全（C++ 容器同策略）


def test_k_container_lockdown(e2e_client: TestClient):
    files = {
        "src/main.cpp": (
            "#include <cstdio>\n"
            "int main() {\n"
            "    if (FILE* f = fopen(\"/etc/shadow\", \"r\")) { printf(\"SHADOW_OK\\n\"); fclose(f); }\n"
            "    else { printf(\"SHADOW_DENIED\\n\"); }\n"
            "    if (FILE* f = fopen(\"/etc/pwned\", \"w\")) { printf(\"ROOTFS_Writable\\n\"); fclose(f); }\n"
            "    else { printf(\"ROOTFS_READONLY\\n\"); }\n"
            "    return 0;\n"
            "}\n"
        )
    }
    final = _wait(e2e_client, _create(e2e_client, files=files))
    assert "SHADOW_DENIED" in final["stdout"]
    assert "SHADOW_OK" not in final["stdout"]
    assert "ROOTFS_READONLY" in final["stdout"]
    assert "ROOTFS_Writable" not in final["stdout"]


def test_k_cancel_running(e2e_client: TestClient):
    files = {"src/main.cpp": '#include <cstdio>\n#include <unistd.h>\nint main() { printf("started\\n"); fflush(stdout); while (true) { sleep(1); } }\n'}
    exec_id = _create(e2e_client, files=files, timeoutMs=30000)
    # 等待真实输出（编译 ~1s + 运行开始）
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        data = e2e_client.get(f"/api/v1/executions/{exec_id}").json()
        if "started" in data["stdout"]:
            break
        time.sleep(0.3)
    resp = e2e_client.post(f"/api/v1/executions/{exec_id}/cancel")
    assert resp.status_code == 200
    final = _wait(e2e_client, exec_id)
    assert final["status"] == "cancelled"
    time.sleep(1.0)
    assert _leftover_containers() == [], "取消后不应遗留沙箱容器"
