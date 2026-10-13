"""P8.2.1 新模块单元测试：ChangeSet/Applier/Context/Consistency/Repair/Checkpoint。"""

import pytest

from app.domains.course_generation.lessons.change_applier import (
    apply_file_changes,
    compose_project_files,
)
from app.domains.course_generation.lessons.change_set import (
    FileChange,
    LessonChangeSet,
    content_hash,
)
from app.domains.course_generation.lessons.consistency_validator import (
    snapshot_hash_of,
    validate_material,
)
from app.domains.course_generation.lessons.cpp_repair_agent import (
    RepairBudget,
    classify_failure,
    repair_with_agent,
)
from app.domains.course_generation.lessons.project_context import (
    build_project_context,
    file_category,
)


def _change(path, op, content, base_hash=None, category="source"):
    return FileChange(path=path, operation=op, content=content,
                      base_hash=base_hash, reason="test", change_category=category)


# ---------------------------------------------------------------- Applier


def test_apply_create_update_delete():
    base = {"a.txt": "A", "b.txt": "B"}
    result = apply_file_changes(base, [
        _change("c.txt", "create", "C"),
        _change("a.txt", "update", "A2", base_hash=content_hash("A")),
        _change("b.txt", "delete", "", base_hash=content_hash("B")),
    ])
    assert result.ok
    assert result.files == {"a.txt": "A2", "c.txt": "C"}
    assert base == {"a.txt": "A", "b.txt": "B"}  # 原子性：不改基线


def test_apply_update_hash_strict_rejection_and_programmatic_repair():
    """P8.2.2：错误/缺失 baseHash 一律拒绝；程序化回填后可确定性通过。"""
    from app.domains.course_generation.lessons.change_applier import (
        hash_only_conflicts,
        repair_base_hashes,
    )

    base = {"a.txt": "A"}
    wrong = apply_file_changes(base, [_change("a.txt", "update", "A2", base_hash="wrong")])
    assert not wrong.ok
    assert wrong.conflicts[0]["errorCode"] == "base-hash-mismatch"
    missing = apply_file_changes(base, [_change("a.txt", "update", "A2")])
    assert not missing.ok
    assert missing.conflicts[0]["errorCode"] == "missing-base-hash"
    # 基线未被修改（无静默覆盖）
    assert base == {"a.txt": "A"}

    # 程序化回填：哈希类冲突 → 服务端重写 baseHash → 应用成功（零 LLM）
    assert hash_only_conflicts(wrong.conflicts)
    repaired = repair_base_hashes(base, [_change("a.txt", "update", "A2", base_hash="wrong")])
    ok = apply_file_changes(base, repaired)
    assert ok.ok and ok.files == {"a.txt": "A2"}
    # 非哈希冲突不可程序化回填
    assert not hash_only_conflicts([{"errorCode": "create-exists"}])


def test_apply_rejects_path_traversal_and_duplicates():
    with pytest.raises(Exception):
        FileChange(path="../escape.cpp", operation="create", content="x")
    with pytest.raises(Exception):
        FileChange(path="/abs/path.cpp", operation="create", content="x")
    base = {"a.txt": "A"}
    result = apply_file_changes(base, [
        _change("n.txt", "create", "1"),
        _change("n.txt", "create", "2"),
    ])
    assert not result.ok
    assert result.conflicts[0]["errorCode"] == "duplicate-change"


def test_apply_protected_delete_blocked():
    base = {"tests/CMakeLists.txt": "add_test(...)", "src/a.cpp": "x"}
    result = apply_file_changes(base, [
        _change("tests/CMakeLists.txt", "delete", "",
                base_hash=content_hash(base["tests/CMakeLists.txt"])),
    ])
    assert not result.ok
    assert result.conflicts[0]["errorCode"] == "protected-delete"


def test_apply_create_exists_rejected():
    base = {"a.txt": "A"}
    result = apply_file_changes(base, [_change("a.txt", "create", "B")])
    assert not result.ok
    assert result.conflicts[0]["errorCode"] == "create-exists"


def _changeset(reference=None, starter=None, tests=None, manifest=None,
               expected=None):
    return LessonChangeSet.model_validate({
        "taskId": "t1",
        "instructions": {"title": "t", "expectedFiles": expected or ["engine/src/World.cpp"]},
        "referenceChanges": reference or [],
        "starterChanges": starter or [],
        "testChanges": tests or [],
        "buildManifest": manifest or {"buildTargets": ["engine"],
                                      "testNames": ["world_update"]},
    })


def test_compose_project_files_synthesizes_full_project():
    cs = _changeset(
        reference=[
            _change("CMakeLists.txt", "create", "# root", category="cmake"),
            _change("engine/CMakeLists.txt", "create", "add_library(...)", category="cmake"),
            _change("engine/src/World.cpp", "create", "impl", category="source"),
        ],
        starter=[_change("engine/src/World.cpp", "create", "// TODO", category="source")],
        tests=[_change("tests/CMakeLists.txt", "create",
                       "add_test(NAME world_update ...)", category="test")],
    )
    reference, starter = compose_project_files({"旧文件": "keep"}, cs)
    assert reference.ok and starter.ok
    # 参考工程 = 基线 + reference + tests；未声明文件原样继承
    assert reference.files["旧文件"] == "keep"
    assert reference.files["engine/src/World.cpp"] == "impl"
    assert "tests/CMakeLists.txt" in reference.files
    # starter = 参考工程 + 挖空覆盖
    assert starter.files["engine/src/World.cpp"] == "// TODO"
    assert starter.files["tests/CMakeLists.txt"] == reference.files["tests/CMakeLists.txt"]


# ---------------------------------------------------------------- Project Context


def test_context_relevance_over_truncation():
    """>14 文件、单文件 >2200 字符：关键文件全文进上下文，其余仅 Manifest。"""
    files = {f"src/mod{i:02d}.cpp": "int f(){} // " + "x" * 3000 for i in range(20)}
    files["CMakeLists.txt"] = "cmake_minimum_required(VERSION 3.16)"
    files["tests/CMakeLists.txt"] = "add_test(NAME world_update COMMAND w)"
    files["engine/include/engine/World.hpp"] = "class World { void update(); };"
    ctx = build_project_context(files, {
        "taskId": "t2", "title": "增加 Entity 模块并与 World 集成",
        "description": "World 集成", "deliverables": ["Entity"],
    }, budget_chars=5000)
    # 关键构建/接口文件全文（不再 2200 截断）
    assert "CMakeLists.txt" in ctx.full_files
    assert "engine/include/engine/World.hpp" in ctx.full_files
    world = ctx.full_files["engine/include/engine/World.hpp"]
    assert world == files["engine/include/engine/World.hpp"]
    # 全量 Manifest（20+ 文件全部可见）
    assert len(ctx.manifest) == len(files)
    # 预算有限 → 部分文件降级为 Manifest 条目（可观测）
    assert ctx.truncated


def test_context_marks_summary_confidence():
    ctx = build_project_context(
        {"engine/include/engine/World.hpp": "namespace engine { class World{}; }"},
        {"taskId": "t", "title": "x"}, budget_chars=10000)
    meta = next(m for m in ctx.manifest if m.path.endswith("World.hpp"))
    assert meta.summary.startswith("[partial]")
    assert file_category("tests/test_w.cpp") == "test"


# ---------------------------------------------------------------- Consistency


def _consistent_material(**overrides):
    reference = {
        "CMakeLists.txt": "add_subdirectory(engine)\nenable_testing()\nadd_subdirectory(tests)",
        "engine/CMakeLists.txt": "add_library(engine STATIC src/World.cpp)",
        "engine/include/engine/World.hpp": "#pragma once\nnamespace engine {}\n",
        "engine/src/World.cpp": 'namespace engine { int world() { return 1; } }\n',
        "tests/CMakeLists.txt": "add_test(NAME world_update COMMAND world_tests)\n",
        "tests/test_world.cpp": "#include <cassert>\nint main(){ assert(1); }\n",
    }
    starter = dict(reference)
    starter["engine/src/World.cpp"] = "namespace engine { int world() { /* TODO: 实现 */ return 0; } }\n"
    manifest = {"buildTargets": ["engine"], "testNames": ["world_update"]}
    for key, value in overrides.items():
        if key == "manifest":
            manifest = value
        elif key == "reference":
            reference.update(value)
    errors = validate_material("t1", reference, starter, manifest, {},
                               ["engine/src/World.cpp"])
    return errors


def test_consistency_ok_on_valid_material():
    assert _consistent_material() == []


def test_consistency_missing_ctest_registration():
    errors = _consistent_material(manifest={"buildTargets": ["engine"],
                                            "testNames": ["entity_spawn"]})
    assert any(e["errorCode"] == "ctest-registration-mismatch" for e in errors)
    assert errors[0]["suggestedRepairScope"] == "tests/CMakeLists.txt"


def test_consistency_regression_test_removed():
    base = {"tests/CMakeLists.txt": "add_test(NAME old_test COMMAND o)\n"}
    reference = {
        "CMakeLists.txt": "x", "tests/CMakeLists.txt": "add_test(NAME new_test COMMAND n)\n",
        "engine/src/World.cpp": "int w(){return 1;}",
    }
    starter = dict(reference)
    errors = validate_material("t2", reference, starter,
                               {"buildTargets": [], "testNames": ["new_test"]},
                               base, [])
    assert any(e["errorCode"] == "regression-test-removed" for e in errors)


def test_consistency_starter_leak_and_missing_todo():
    errors = _consistent_material(reference={})
    assert errors == []  # 正常
    # 泄露：starter 与 reference 相同
    bad = _consistent_material()
    # 通过 overrides 直接改不了 starter；用底层 API 构造
    reference = {
        "CMakeLists.txt": "x",
        "tests/CMakeLists.txt": "add_test(NAME world_update COMMAND w)\n",
        "engine/src/World.cpp": "int world(){ return 1; }",
    }
    errors = validate_material("t1", reference, dict(reference),
                               {"buildTargets": [], "testNames": ["world_update"]},
                               {}, ["engine/src/World.cpp"])
    assert any(e["errorCode"] == "starter-leaks-answer" for e in errors)


def test_consistency_missing_include():
    errors = _consistent_material(
        reference={"engine/src/World.cpp": '#include "engine/Ghost.hpp"\nint w(){}'})
    assert any(e["errorCode"] == "missing-include" for e in errors)


def test_consistency_run_target_missing():
    errors = _consistent_material(manifest={"buildTargets": ["engine"],
                                            "runTargets": ["demo"],
                                            "testNames": ["world_update"]})
    assert any(e["errorCode"] == "run-target-missing" for e in errors)


def test_snapshot_hash_stable_and_sensitive():
    a = {"x": "1", "y": "2"}
    assert snapshot_hash_of(a) == snapshot_hash_of({"y": "2", "x": "1"})
    assert snapshot_hash_of(a) != snapshot_hash_of({"x": "1", "y": "3"})


# ---------------------------------------------------------------- Repair Agent


def test_classify_failure_categories():
    assert classify_failure([], ["base-hash-mismatch"]) == "file-change-conflict"
    assert classify_failure([], ["ctest-registration-mismatch"]) == "missing-ctest-registration"
    assert classify_failure(["CMake Configure 失败"], []) == "cmake-configure-error"
    assert classify_failure(["starter 上全部要求测试通过"], []) == "starter-invalid-failure"
    assert classify_failure(["参考实现测试未通过"], []) == "reference-test-failure"


def test_budget_exhaustion_blocks_llm():
    budget = RepairBudget(max_llm_calls=1, max_tokens=100)
    budget.llm_calls = 1
    outcome = repair_with_agent(
        None, {"taskId": "t"}, "compiler-error", [], [], {}, {}, budget, [])
    assert not outcome.ok
    assert "预算耗尽" in outcome.diagnosis


def test_repair_agent_returns_minimal_patch():
    class P:
        def chat(self, system, user):
            assert "最小补丁" in system
            assert "baseHash" in user  # 提供当前 hash 才能正确 update
            return type("R", (), {"content":
                                  '{"diagnosis":"d","failureClass":"missing-ctest-registration",'
                                  '"patch":[{"path":"tests/CMakeLists.txt","operation":"update",'
                                  '"baseHash":"x","content":"...","reason":"补注册",'
                                  '"changeCategory":"test"}]}',
                                  "prompt_tokens": 100, "completion_tokens": 50})()

    budget = RepairBudget()
    outcome = repair_with_agent(
        P(), {"taskId": "t2"}, "missing-ctest-registration",
        [{"errorCode": "ctest-registration-mismatch", "filePath": "tests/CMakeLists.txt",
          "expected": "add_test entity_spawn", "actual": "未注册",
          "suggestedRepairScope": "tests/CMakeLists.txt"}],
        ["CTest 找不到 entity_spawn"],
        {"tests/CMakeLists.txt": "add_test(NAME world_update ...)\n"},
        {"manifest": {"testNames": ["entity_spawn"]}}, budget, [])
    assert outcome.ok
    assert outcome.patch[0]["path"] == "tests/CMakeLists.txt"
    assert budget.llm_calls == 1 and budget.tokens_used == 150


# ---------------------------------------------------------------- ChangeSet schema


def test_changeset_schema_validates_and_rejects():
    valid = _changeset()
    assert valid.task_id == "t1"
    with pytest.raises(Exception):
        LessonChangeSet.model_validate({
            "taskId": "t1", "instructions": {"title": "t"},
            "referenceChanges": [{"path": "a/../b", "operation": "create", "content": "x"}],
            "buildManifest": {},
        })


def test_starter_overlay_base_server_authoritative():
    """starter update 哈希由服务端按参考版回填（两阶段快照关系，D47）。"""
    cs = _changeset(
        reference=[_change("engine/src/World.cpp", "create", "impl")],
        starter=[_change("engine/src/World.cpp", "update", "// TODO", base_hash="wrong-hash")],
    )
    reference, starter = compose_project_files({}, cs)
    assert reference.ok and starter.ok
    assert starter.files["engine/src/World.cpp"] == "// TODO"
