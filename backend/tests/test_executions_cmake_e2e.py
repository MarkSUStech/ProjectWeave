"""P8.1 CMake Project Runtime 真实 Docker E2E（选入：PW_SANDBOX_E2E=1）。

验收项目：tests/fixtures/sample-cmake-project（多子目录 + engine 静态库 +
game/inspect 两个可执行目标 + 两个 CTest 测试，其中 test_terrain 故意失败）。

真实链路：快照 → 受限 Docker 沙箱 → CMake Configure（Ninja）→ File API
目标发现 → 按目标构建/运行 → CTest（JUnit）→ 结构化结果。
覆盖验收点 A–J（K/L 由既有套件与前端测试覆盖）。
"""

import os
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.domains.executions import service

pytestmark = pytest.mark.skipif(
    os.environ.get("PW_SANDBOX_E2E") != "1",
    reason="需 PW_SANDBOX_E2E=1（真实 Docker + projectweave-sandbox-cpp:clang15-bookworm）",
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample-cmake-project"


@pytest.fixture()
def e2e_client(client: TestClient, db_session):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    service.set_session_factory(factory)
    yield client
    from app.core.db import SessionLocal

    service.set_session_factory(SessionLocal)


def _sample_files(overrides: dict[str, str] | None = None) -> dict[str, str]:
    files = {
        str(p.relative_to(FIXTURE)).replace("\\", "/"): p.read_text(encoding="utf-8")
        for p in FIXTURE.rglob("*") if p.is_file()
    }
    files.update(overrides or {})
    return files


def _create(client: TestClient, **payload):
    body = {
        "language": "cpp",
        "mode": "run",
        "entryPoint": None,
        "files": _sample_files(),
        "timeoutMs": 120000,
        "buildSystem": "cmake",
    }
    body.update(payload)
    resp = client.post("/api/v1/executions", json=body)
    assert resp.status_code == 202, resp.text
    return resp.json()["id"]


def _wait(client: TestClient, exec_id: str, timeout_s: float = 240.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/api/v1/executions/{exec_id}").json()
        if data["status"] in {"completed", "failed", "timed-out", "cancelled"}:
            return data
        time.sleep(0.5)
    pytest.fail("CMake 执行未在期限内到达终态")


def _docker_leftovers() -> list[str]:
    proc = subprocess.run(
        ["docker", "ps", "-a", "--filter", "label=pw.sandbox=1", "-q"],
        capture_output=True, text=True, timeout=20,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def test_ab_discover_real_targets(e2e_client: TestClient):
    """A 多目录 Configure 成功；B File API 返回正确目标列表与类型。"""
    final = _wait(e2e_client, _create(
        e2e_client, cmakeAction="discover", timeoutMs=120000))
    assert final["status"] == "completed", final["error"]
    targets = {t["name"]: t for t in final["cmake"]["targets"]}
    assert targets["engine"]["type"] == "STATIC_LIBRARY"
    assert targets["engine"]["runnable"] is False
    for exe in ("game", "inspect", "test_world", "test_terrain"):
        assert targets[exe]["type"] == "EXECUTABLE", (exe, targets[exe])
        assert targets[exe]["runnable"] is True
    assert targets["game"]["dependencies"] == ["engine"]
    assert targets["game"]["artifacts"] == ["build/game/game"]
    assert "engine/src/World.cpp" in targets["engine"]["sources"]
    assert final["cmake"]["generator"] == "Ninja"
    assert final["cmake"]["cmakeVersion"].startswith("cmake version")


def test_cd_run_game_links_engine(e2e_client: TestClient):
    """C engine 被 game 正确链接；D 运行 game 输出正确结果。"""
    final = _wait(e2e_client, _create(
        e2e_client, cmakeAction="run", targetName="game"))
    assert final["status"] == "completed", final["error"]
    assert final["exitCode"] == 0
    assert "hello weave" in final["stdout"]
    assert "elevation(-1)=5" in final["stdout"]
    assert "elevation(1)=10" in final["stdout"]
    assert final["cmake"]["target"] == "game"
    assert final["cmake"]["artifact"] == "build/game/game"
    phases = {p["name"]: p for p in final["phases"]}
    for name in ("configure", "build", "run"):
        assert phases[name]["status"] == "completed", name


def test_e_run_second_executable(e2e_client: TestClient):
    """E 另一个可执行目标（inspect）真实运行。"""
    final = _wait(e2e_client, _create(
        e2e_client, cmakeAction="run", targetName="inspect"))
    assert final["status"] == "completed", final["error"]
    assert final["stdout"].count("hello probe") >= 1


def test_build_only_target(e2e_client: TestClient):
    """build-only：构建 engine 库目标成功且不产生 run 阶段。"""
    final = _wait(e2e_client, _create(
        e2e_client, cmakeAction="build", targetName="engine"))
    assert final["status"] == "completed", final["error"]
    assert [p["name"] for p in final["phases"]] == ["configure", "build"]


def test_unknown_target_rejected_with_discovered_list(e2e_client: TestClient):
    """未知目标：明确报错并列出已发现目标（不猜测）。"""
    final = _wait(e2e_client, _create(
        e2e_client, cmakeAction="run", targetName="nope"))
    assert final["status"] == "completed"  # 业务结果如实呈现
    assert final["exitCode"] == 2
    messages = " ".join(d["message"] for d in final["diagnostics"])
    assert "目标不存在" in messages and "game" in messages


def test_fg_ctest_discovers_and_runs(e2e_client: TestClient):
    """F CTest 发现并执行多个测试；G 故意失败的测试显示为 failed。"""
    final = _wait(e2e_client, _create(
        e2e_client, mode="test", testPaths=[]))
    assert final["exitCode"] != 0  # test_terrain 失败 → 整体非零
    by_name = {r["path"]: r for r in final["testResults"]}
    assert by_name["test_world"]["status"] == "passed"
    assert by_name["test_world_extra"]["status"] == "passed"
    assert by_name["test_terrain"]["status"] == "failed"
    assert "99.0" in (by_name["test_terrain"]["error"] or "")
    assert set(final["cmake"]["discoveredTests"]) >= {"test_world", "test_terrain", "test_world_extra"}


def test_selected_tests_run_only_selection(e2e_client: TestClient):
    """选择执行：仅选中项作为通过条件；未选择项 skipped 不影响；前缀不误匹配。"""
    final = _wait(e2e_client, _create(
        e2e_client, mode="test", testPaths=[], selectedTests=["test_world"]))
    assert final["status"] == "completed", final["error"]
    assert final["exitCode"] == 0  # 选择执行真实通过（P8.1.1 修复点）
    executed = {r["path"] for r in final["testResults"] if r["status"] != "skipped"}
    # 全锚点 -R：test_world 不得误运行前缀测试 test_world_extra
    assert executed == {"test_world"}
    skipped = {r["path"] for r in final["testResults"] if r["status"] == "skipped"}
    assert skipped == {"test_terrain", "test_world_extra"}
    assert all("选择范围" in (r["error"] or "") for r in final["testResults"]
               if r["status"] == "skipped")


def test_selected_unknown_test_reports_error(e2e_client: TestClient):
    """显式选择的测试不存在 → 明确报错并列出实际发现（不静默）。"""
    final = _wait(e2e_client, _create(
        e2e_client, mode="test", testPaths=[], selectedTests=["no_such_test"]))
    assert final["exitCode"] == 2
    messages = " ".join(d["message"] for d in final["diagnostics"])
    assert "选择的测试不存在" in messages
    assert "no_such_test" in messages and "test_world" in messages


def test_h_compile_error_reports_file_and_line(e2e_client: TestClient):
    """H 编译错误返回具体文件与行号（阶段=build，不冒充 configure/run）。"""
    broken = _sample_files({"engine/src/World.cpp": (
        '#include "engine/World.hpp"\n'
        "#include <algorithm>\n"
        "namespace engine {\n"
        "std::string World::greet(const std::string& name) const {\n"
        "    return name;  // 缺少 entities_ 查找逻辑\n"
        "}\n"
        "double World::terrain_elevation(double x) const {\n"
        "    return oops_typo(x);  // 未声明标识符（第 8 行）\n"
        "}\n"
        "}  // namespace engine\n"
    )})
    final = _wait(e2e_client, _create(
        e2e_client, files=broken, mode="test", testPaths=[]))
    assert final["exitCode"] != 0
    phases = {p["name"]: p for p in final["phases"]}
    assert phases["configure"]["status"] == "completed"
    assert phases["build"]["status"] == "failed"
    assert phases["test"]["status"] == "skipped"  # 构建失败不进入测试
    compile_errors = [d for d in final["diagnostics"]
                      if d.get("stage") == "build" and d.get("file")]
    assert compile_errors, final["diagnostics"]
    assert compile_errors[0]["file"].endswith("World.cpp")
    assert compile_errors[0]["line"] == 8


def test_i_configure_vs_build_vs_run_errors_distinguished(e2e_client: TestClient):
    """I 三类错误可区分：configure 错误定位 CMakeLists 行号（幽灵子目录）。"""
    files = _sample_files({"CMakeLists.txt": (
        "cmake_minimum_required(VERSION 3.16)\n"
        "project(weave_world LANGUAGES CXX)\n"
        "add_subdirectory(engine)\n"
        "add_subdirectory(ghost)\n"  # 第 4 行：不存在的子目录 → configure 期错误
    )})
    final = _wait(e2e_client, _create(
        e2e_client, files=files, cmakeAction="run", targetName="game"))
    assert final["exitCode"] != 0
    diagnostics = final["diagnostics"]
    configure = [d for d in diagnostics if d.get("stage") == "configure"]
    assert configure, diagnostics
    assert configure[0]["file"] == "CMakeLists.txt"
    assert configure[0]["line"] == 4
    phases = {p["name"]: p for p in final["phases"]}
    assert phases["configure"]["status"] == "failed"
    assert phases["build"]["status"] == "skipped"
    assert phases["run"]["status"] == "skipped"


def test_j_no_container_leftovers(e2e_client: TestClient):
    """J 执行完成后无遗留沙箱容器。"""
    assert _docker_leftovers() == []
    _wait(e2e_client, _create(e2e_client, cmakeAction="run", targetName="game"))
    _wait(e2e_client, _create(e2e_client, mode="test", testPaths=[]))
    # 清理是异步收尾的一部分，给短暂宽限
    deadline = time.monotonic() + 15
    while _docker_leftovers() and time.monotonic() < deadline:
        time.sleep(0.5)
    assert _docker_leftovers() == []
