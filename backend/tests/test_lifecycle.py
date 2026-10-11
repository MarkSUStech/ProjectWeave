"""P7.3 学习生命周期测试：合并/激活/解锁/H4隔离/候选概念/最终验收。"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.db import SessionLocal
from app.domains.course_generation.lessons import lifecycle
from app.domains.course_generation.lessons.lesson_publisher import (
    instantiate_project,
    lesson_builder,
    _task_order,
    _normalize_blueprint,
)
from app.domains.course_generation.models import CourseGeneration, CourseRelease

NL = chr(10)


def _starter(path: str, todo: bool = True) -> dict:
    body = (
        "class Value:" + NL + "    def __init__(self, data):" + NL
        + "        self.data = data" + NL
        + (("# TODO: 实现 __add__" + NL) if todo else
           ("    def __add__(self, other):" + NL + "        return Value(self.data + other.data)" + NL))
    )
    return {"path": path, "content": body}


def _test(path: str) -> dict:
    return {
        "path": path,
        "content": ("from micrograd.value import Value" + NL + NL
                     + "def test_add():" + NL
                     + "    assert (Value(2) + Value(3)).data == 5.0" + NL),
    }


def _ref(path: str) -> dict:
    return {
        "path": path,
        "content": (
            "class Value:" + NL + "    def __init__(self, data):" + NL
            + "        self.data = data" + NL
            + "    def __add__(self, other):" + NL
            + "        return Value(self.data + other.data)" + NL
        ),
    }


def _artifact(task_id: str, ms_id: str = "ms-1") -> dict:
    return {
        "taskId": task_id, "milestoneId": ms_id, "language": "python",
        "instructions": {"title": task_id, "goal": "实现 Value"},
        "starterFiles": [_starter("micrograd/value.py")],
        "testFiles": [_test("tests/test_value.py")],
        "hints": [
            {"level": 1, "text": "H1"}, {"level": 2, "text": "H2"},
            {"level": 3, "text": "H3"}, {"level": 4, "text": "H4 参考级"},
        ],
        "status": "tests-passed",
        "verifications": [{"kind": "reference-tests", "status": "passed",
                           "total": 1, "passed": 1, "failed": 0}],
        "repairs": [], "error": None,
    }


def _blueprint_2tasks() -> dict:
    return {
        "project": {"title": "课程", "description": "d", "sourceUrl": "u",
                     "commitSha": "a" * 40, "license": {}, "techStack": ["Python"],
                     "finalArtifact": "引擎", "goals": [], "nonGoals": ["非目标X"]},
        "milestones": [
            {"milestoneId": "ms-1", "title": "M1", "deliverables": ["Value"],
             "acceptanceCriteria": ["通过"], "dependsOn": []},
        ],
        "tasks": [
            {"taskId": "t1", "milestoneId": "ms-1", "title": "任务1",
             "description": "d", "dependsOn": [], "requiredConcepts": [],
             "deliverables": ["value.py"], "acceptanceCriteria": ["通过"],
             "sourceEvidence": []},
            {"taskId": "t2", "milestoneId": "ms-1", "title": "任务2",
             "description": "d", "dependsOn": ["t1"], "requiredConcepts": [],
             "deliverables": ["mul"], "acceptanceCriteria": ["通过"],
             "sourceEvidence": []},
        ],
        "knowledgeRequirements": [],
    }


@pytest.fixture()
def course_client(client: TestClient, db_session):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    from app.domains.course_generation.lessons import lesson_publisher

    lesson_publisher.set_session_factory(factory)

    # 直接造 ready release + 实例化项目
    import uuid as _uuid

    blueprint = _blueprint_2tasks()
    gen = CourseGeneration(
        id=_uuid.uuid4(), source_url="u", status="published",
        repo_owner="k", repo_name="r", commit_sha="a" * 40,
    )
    db_session.add(gen)
    db_session.flush()

    t1_art = _artifact("t1")
    t2_art = _artifact("t2")
    # t2 的 starter 含更多 TODO
    t2_art["starterFiles"][0]["content"] += ("# TODO: 实现 __mul__" + NL)

    release = CourseRelease(
        generation_id=gen.id, status="ready", language="python",
        course_title="课程", blueprint_snapshot=blueprint,
        artifacts=[t1_art, t2_art],
        reference_store={"t1": [_ref("micrograd/value.py")]},
        verification_report={"finalIntegration": {"status": "passed", "total": 2, "passed": 2, "failed": 0}},
        ready_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db_session.add(release)
    db_session.commit()
    db_session.refresh(release)

    result = instantiate_project(db_session, str(release.id), "测试课程项目")
    project_id = str(result["project_id"])

    yield client, db_session, str(release.id), project_id
    lesson_publisher._session_factory = None


# ---------------------------------------------------------------- 三方合并


class TestThreeWayMerge:
    def test_new_file_created(self):
        m = lifecycle.three_way_merge(
            {}, {"a.py": "new"}, {},
        )
        assert m.ok and m.created == ["a.py"] and m.files["a.py"] == "new"

    def test_student_code_preserved_when_course_unchanged(self):
        m = lifecycle.three_way_merge(
            {"a.py": "base"}, {"a.py": "base"}, {"a.py": "student version"},
        )
        assert m.ok and m.files["a.py"] == "student version" and m.preserved == ["a.py"]

    def test_course_update_applied_when_student_unchanged(self):
        m = lifecycle.three_way_merge(
            {"a.py": "base"}, {"a.py": "updated"}, {"a.py": "base"},
        )
        assert m.ok and m.files["a.py"] == "updated" and m.updated == ["a.py"]

    def test_conflict_when_both_changed(self):
        m = lifecycle.three_way_merge(
            {"a.py": "base"}, {"a.py": "course"}, {"a.py": "student"},
        )
        assert not m.ok and len(m.conflicts) == 1
        assert m.files["a.py"] == "student"  # 不静默覆盖学生

    def test_student_todo_replaced_by_course_version(self):
        m = lifecycle.three_way_merge(
            {}, {"a.py": "full impl"}, {"a.py": "# TODO: impl\n"},
        )
        assert m.ok and m.files["a.py"] == "full impl"

    def test_student_non_todo_new_file_conflicts(self):
        m = lifecycle.three_way_merge(
            {}, {"a.py": "course version"}, {"a.py": "student wrote own"},
        )
        assert not m.ok and len(m.conflicts) == 1


# ---------------------------------------------------------------- 生命周期


class TestLifecycle:
    def test_initial_state(self, course_client):
        client, db, release_id, project_id = course_client
        progress = client.get(f"/api/v1/projects/{project_id}/course-progress").json()
        assert progress["courseMode"] is True
        statuses = {t["taskId"]: t["status"] for t in progress["tasks"]}
        assert statuses == {"t1": "active", "t2": "locked"}  # t1 已在 instantiate 时激活

    def test_activate_locked_rejected(self, course_client):
        client, db, release_id, project_id = course_client
        resp = client.post(f"/api/v1/projects/{project_id}/tasks/t2/activate")
        assert resp.status_code == 422
        assert "前置任务未完成" in resp.json()["detail"]

    def test_activate_idempotent(self, course_client):
        client, db, release_id, project_id = course_client
        resp = client.post(f"/api/v1/projects/{project_id}/tasks/t1/activate")
        assert resp.status_code == 200
        assert resp.json()["alreadyActive"] is True

    def test_complete_then_unlock_next(self, course_client):
        client, db, release_id, project_id = course_client
        # 模拟学生完成任务 t1（直接更新任务状态——测试内服务端操作）
        from app.domains.curriculum.models import ProjectTask
        import uuid as _uuid

        task = db.scalar(
            __import__("sqlalchemy").select(ProjectTask).where(
                ProjectTask.project_id == _uuid.UUID(project_id),
                ProjectTask.task_id == "t1",
            )
        )
        task.status = "done"
        db.commit()

        progress = client.get(f"/api/v1/projects/{project_id}/course-progress").json()
        statuses = {t["taskId"]: t["status"] for t in progress["tasks"]}
        assert statuses["t1"] == "completed"
        assert statuses["t2"] == "available"  # 解锁

        # 激活 t2：学生已有代码不被覆盖
        resp = client.post(f"/api/v1/projects/{project_id}/tasks/t2/activate")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["activated"] is True

        # 学生文件仍在（t1 的 starter 未被 t2 覆盖）
        files = {f["path"] for f in client.get(
            f"/api/v1/projects/{project_id}/files").json()["items"]}
        assert "micrograd/value.py" in files

    def test_final_report_requires_all_completed(self, course_client):
        client, db, release_id, project_id = course_client
        resp = client.get(f"/api/v1/projects/{project_id}/final-report")
        assert resp.status_code == 422

        from app.domains.curriculum.models import ProjectTask
        import uuid as _uuid

        for tid in ("t1", "t2"):
            task = db.scalar(
                __import__("sqlalchemy").select(ProjectTask).where(
                    ProjectTask.project_id == _uuid.UUID(project_id),
                    ProjectTask.task_id == tid,
                )
            )
            task.status = "done"
        db.commit()

        report = client.get(f"/api/v1/projects/{project_id}/final-report").json()
        assert report["completedTasks"] == 2
        assert report["referenceIntegrationVerified"] is True
        assert "非目标X" in report["nonGoals"]

    def test_non_course_project(self, client):
        from tests.conftest import VALID_CREATE_PAYLOAD

        pid = client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD).json()["id"]
        progress = client.get(f"/api/v1/projects/{pid}/course-progress").json()
        assert progress["courseMode"] is False


# ---------------------------------------------------------------- H4 隔离 + 候选概念


class TestH4AndConcepts:
    def test_h4_not_in_public_api(self, course_client):
        client, db, release_id, project_id = course_client
        detail = client.get(f"/api/v1/course-releases/{release_id}").json()
        for artifact in detail["artifacts"]:
            levels = {h["level"] for h in artifact["hints"]}
            assert levels == {1, 2, 3}  # H4 已被剥离
            assert "referenceFiles" not in json.dumps(artifact)

    def test_candidate_concepts_dont_break_plan(self, client, db_session):
        """课程项目引用图谱外概念 → 学习路线正常生成（安全降级）。"""
        from tests.conftest import VALID_CREATE_PAYLOAD
        from app.domains.concepts.service import ensure_seed_concepts

        ensure_seed_concepts(db_session)
        pid = client.post("/api/v1/projects", json=VALID_CREATE_PAYLOAD).json()["id"]
        from app.domains.curriculum.models import ProjectTask

        db_session.add(ProjectTask(
            project_id=__import__("uuid").UUID(pid), task_id="cand-1", milestone=1,
            title="候选概念任务", depends_on=[],
            required_concepts=["custom.generated.concept"],
        ))
        db_session.commit()

        plan = client.get(f"/api/v1/plans/{pid}")
        assert plan.status_code == 200
        assert len(plan.json()["tasks"]) >= 1


def _get_db_session(client):
    """获取 TestClient 的底层 db session（同请求生命周期）。"""
    gen = client.app.dependency_overrides.get(
        __import__("app.core.db", fromlist=["get_db"]).get_db
    )
    if gen:
        return next(iter([gen()])) if callable(gen) else next(iter(gen))
    raise RuntimeError("no db override")
