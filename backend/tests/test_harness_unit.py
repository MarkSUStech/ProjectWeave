"""Harness 确定性测试（P8.2.3，D48）：工具协议/状态机/权限/评估独立。

不依赖 Docker 的部分（workspace/权限/租约）+ 受控 provider 的
E2E B（主动修复）在 PW_SANDBOX_E2E 套件中。
"""

import json

import pytest

from app.domains.course_generation.harness.workspace import CourseWorkspace
from app.domains.course_generation.lessons.change_set import FileChange, content_hash


def _ws():
    return CourseWorkspace({
        "referenceFiles": {
            "CMakeLists.txt": "cmake_minimum_required(VERSION 3.16)\n",
            "engine/src/World.cpp": "int world(){return 1;}\n",
        },
        "baseSnapshot": {"referenceFiles": {
            "CMakeLists.txt": "cmake_minimum_required(VERSION 3.16)\n"}},
    })


def test_workspace_list_and_read():
    ws = _ws()
    files = ws.list_files()
    assert [f["path"] for f in files] == ["CMakeLists.txt", "engine/src/World.cpp"]
    assert files[0]["category"].endswith("cmake")
    result = ws.read_file("engine/src/World.cpp")
    assert result["content"].startswith("int world")
    assert ws.read_file("nope.cpp")["error"]


def test_workspace_apply_atomic_and_revision():
    ws = _ws()
    result = ws.apply_changes([
        FileChange(path="engine/src/Entity.cpp", operation="create",
                   content="int entity(){}\n"),
        FileChange(path="engine/src/World.cpp", operation="update",
                   baseHash=content_hash("int world(){return 1;}\n"),
                   content="int world(){return 2;}\n"),
    ])
    assert result["ok"] and result["revision"] == 1
    assert ws.reference_files["engine/src/World.cpp"] == "int world(){return 2;}\n"

    # 冲突整体失败：不改状态、不推进 Revision
    before = dict(ws.reference_files)
    rev = ws.revision
    bad = ws.apply_changes([
        FileChange(path="new.cpp", operation="create", content="x"),
        FileChange(path="engine/src/World.cpp", operation="update",
                   baseHash="wrong", content="y"),
    ])
    assert not bad["ok"]
    assert bad["conflicts"][0]["errorCode"] == "base-hash-mismatch"
    assert ws.reference_files == before and ws.revision == rev


def test_workspace_starter_overlay_authoritative_base():
    ws = _ws()
    result = ws.apply_changes([
        FileChange(path="engine/src/World.cpp", operation="update",
                   baseHash=content_hash("int world(){return 1;}\n"),
                   content="int world(){return 42;}\n"),
        FileChange(path="engine/src/World.cpp", operation="update",
                   baseHash="whatever-wrong", target="starter",
                   content="int world(){ /* TODO */ return 0; }\n"),
    ])
    assert result["ok"]
    material = ws.material_dict()
    starter_world = next(f["content"] for f in material["starterFiles"]
                         if f["path"] == "engine/src/World.cpp")
    assert "TODO" in starter_world
    ref_world = next(f["content"] for f in material["referenceFiles"]
                     if f["path"] == "engine/src/World.cpp")
    assert "42" in ref_world


def test_workspace_revision_history_and_hash():
    ws = _ws()
    ws.apply_changes([FileChange(path="a.cpp", operation="create", content="1")])
    ws.apply_changes([FileChange(path="a.cpp", operation="update",
                                 baseHash=content_hash("1"), content="2")])
    assert [r["revision"] for r in ws.revisions] == [1, 2]
    assert ws.revisions[-1]["hash"] != ws.revisions[0]["hash"]


def test_material_split_test_vs_source():
    ws = _ws()
    ws.apply_changes([
        FileChange(path="tests/test_w.cpp", operation="create", content="int main(){}"),
        FileChange(path="app/main.cpp", operation="create", content="int main(){}"),
    ])
    material = ws.material_dict()
    test_paths = {f["path"] for f in material["testFiles"]}
    assert "tests/test_w.cpp" in test_paths
    assert "app/main.cpp" not in test_paths
