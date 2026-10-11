"""Agent Runtime / 工具注册表 / 只读工具测试（Mock Provider 脚本化，无真实 LLM）。

覆盖任务书验收：单次/连续工具调用、按结果决定下一步、参数不合法、
路径穿越与跨项目、失败与恢复、预算耗尽、未知工具、H4 门控、决策落库、
无工具直接回复、向后兼容。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.agents.registry import ToolArgumentError, UnknownToolError, registry, validate_args
from app.agents.runtime import agent_record_to_dicts, run_agent
from app.agents.schemas import AgentBudget, ToolContext
from app.agents.tools import register_builtin_tools
from app.ai.provider import MockProvider, ScriptedRound

register_builtin_tools()


@pytest.fixture()
def agent_client(client: TestClient, db_session):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    from app.domains.debugging import service as debug_service

    debug_service.set_session_factory(factory)
    yield client
    from app.core.db import SessionLocal

    debug_service.set_session_factory(SessionLocal)


def _make_cpp_project(client: TestClient, stack=("C++",)) -> str:
    from tests.conftest import VALID_CREATE_PAYLOAD

    payload = dict(VALID_CREATE_PAYLOAD)
    payload["stack"] = list(stack)
    return client.post("/api/v1/projects", json=payload).json()["id"]


def _put_file(client: TestClient, pid: str, path: str, content: str) -> None:
    resp = client.put(f"/api/v1/projects/{pid}/files", json={"path": path, "content": content})
    assert resp.status_code in (200, 201), resp.text


def _tool_ctx(db, pid) -> ToolContext:
    return ToolContext(db=db, project_id=pid)


# ---------------------------------------------------------------- 注册表与校验


def test_registry_whitelist_and_openai_export():
    names = registry.names()
    assert set(names) >= {
        "list_project_files", "read_project_file", "get_current_task",
        "get_recent_diagnostics", "get_learner_mastery", "get_debug_snapshot",
    }
    tools = registry.openai_tools()
    assert all(t["type"] == "function" for t in tools)
    assert all("handler" not in json.dumps(t) for t in tools)  # 不外泄处理器


def test_validate_args_rejects_bad_input():
    spec = registry.get("read_project_file")
    with pytest.raises(ToolArgumentError):
        validate_args(spec, "not-a-dict")
    with pytest.raises(ToolArgumentError):
        validate_args(spec, {})  # 缺 path
    with pytest.raises(ToolArgumentError):
        validate_args(spec, {"path": "a.cpp", "hacker": 1})  # 未知参数
    with pytest.raises(ToolArgumentError):
        validate_args(spec, {"path": 123})  # 类型错误
    validate_args(spec, {"path": "a.cpp"})  # 合法


def test_unknown_tool_error():
    with pytest.raises(UnknownToolError):
        registry.get("rm_rf_slash")  # 白名单外


# ---------------------------------------------------------------- 工具（真实业务数据 + 安全）


def test_tools_scoped_to_project(agent_client: TestClient, db_session):
    pid_a = _make_cpp_project(agent_client)
    pid_b = _make_cpp_project(agent_client)
    _put_file(agent_client, pid_a, "src/a_only.cpp", "int a(){}")
    _put_file(agent_client, pid_b, "src/b_only.cpp", "int b(){}")

    ctx_a = _tool_ctx(db_session, pid_a)
    listing = registry.get("list_project_files").handler(ctx_a)
    paths = [f["path"] for f in listing["files"]]
    assert "src/a_only.cpp" in paths and "src/b_only.cpp" not in paths

    # 跨项目读取：B 的文件在 A 的上下文中不可见（DB 行级过滤）
    record = registry.get("read_project_file")
    from app.agents.registry import execute_tool

    result = execute_tool(record, ctx_a, {"path": "src/b_only.cpp"}, 1)
    assert result.ok is False and "不存在" in result.error


def test_read_file_rejects_traversal(agent_client: TestClient, db_session):
    pid = _make_cpp_project(agent_client)
    ctx = _tool_ctx(db_session, pid)
    tool = registry.get("read_project_file")
    for bad in ["../etc/passwd", "/abs/path.cpp", "a\\b.cpp", "__pw/manifest.json", "../../other/x.cpp"]:
        result = __import__("app.agents.registry", fromlist=["execute_tool"]).execute_tool(
            tool, ctx, {"path": bad}, 1
        )
        assert result.ok is False, bad  # 全部被拒绝


def test_read_file_truncates(agent_client: TestClient, db_session):
    pid = _make_cpp_project(agent_client)
    _put_file(agent_client, pid, "src/big.cpp", "x" * 5000)
    ctx = _tool_ctx(db_session, pid)
    out = registry.get("read_project_file").handler(ctx, path="src/big.cpp", max_chars=500)
    assert out["truncated"] is True and len(out["content"]) < 600


def test_get_recent_diagnostics_reads_real_executions(agent_client: TestClient, db_session):
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.domains.executions.models import ExecutionSession

    pid = _make_cpp_project(agent_client)
    db_session.add(ExecutionSession(
        id=_uuid.uuid4(), project_id=_uuid.UUID(pid), language="cpp", mode="run",
        status="completed", entry_point="src/bad.cpp",
        diagnostics=[{
            "severity": "error", "message": "expected '}'", "file": "src/bad.cpp",
            "line": 1, "column": 20, "source": "build",
        }],
        exit_code=1, timed_out=False, cancelled=False, error=None,
        stdout_text="", stderr_text="1 error generated.",
        queued_at=datetime.now(timezone.utc),
    ))
    db_session.commit()

    ctx = _tool_ctx(db_session, pid)
    out = registry.get("get_recent_diagnostics").handler(ctx)
    entry = out["recentDiagnostics"][0]
    assert entry["buildDiagnostics"][0]["file"] == "src/bad.cpp"
    assert entry["stderrTail"] == "1 error generated."


def test_get_current_task_uses_ctx_task(agent_client: TestClient, db_session):
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    pid = _make_cpp_project(agent_client)
    agent_client.get(f"/api/v1/plans/{pid}")  # 种子 C++ 课程任务
    tasks = agent_client.get(f"/api/v1/plans/{pid}").json()["tasks"]
    ctx = _tool_ctx(db_session, pid)
    ctx.current_task_id = tasks[0]["taskId"]
    out = registry.get("get_current_task").handler(ctx)
    assert out["taskId"] == tasks[0]["taskId"] and out["hints"]


# ---------------------------------------------------------------- Runtime 循环


def _runtime_db_ctx(agent_client, db_session, pid):
    return _tool_ctx(db_session, pid)


def test_runtime_single_tool_then_final(agent_client: TestClient, db_session):
    pid = _make_cpp_project(agent_client)
    _put_file(agent_client, pid, "src/main.cpp", "int main(){}")
    ctx = _runtime_db_ctx(agent_client, db_session, pid)

    provider = MockProvider()
    provider.scripted_rounds = [
        ScriptedRound(tool_calls=[{"id": "c1", "name": "list_project_files", "arguments": {}}]),
        ScriptedRound(tool_calls=[{"id": "c2", "name": "read_project_file", "arguments": {"path": "src/main.cpp"}}]),
        ScriptedRound(content=json.dumps({"intent": "hint", "hintLevel": 1, "message": "看看这个文件"}, ensure_ascii=False)),
    ]
    from app.agents.context import build_initial_messages

    run = run_agent(provider, build_initial_messages("q", {}, False), ctx)
    assert run.rounds == 3 and len(run.tool_calls) == 2
    assert run.tool_calls[0].ok and run.tool_calls[1].ok
    assert "看看这个文件" in run.final_content
    # 工具结果真实回填进模型上下文（第二轮消息包含 role=tool）
    round2 = provider.chat_with_tools_calls[1]["messages"]
    assert '"role": "tool"' in round2 or '"role":"tool"' in round2
    round3 = provider.chat_with_tools_calls[2]["messages"]
    assert "int main(){}" in round3  # read 的真实结果回填第 3 轮


def test_runtime_unknown_tool_recovers(agent_client: TestClient, db_session):
    pid = _make_cpp_project(agent_client)
    ctx = _runtime_db_ctx(agent_client, db_session, pid)
    provider = MockProvider()
    provider.scripted_rounds = [
        ScriptedRound(tool_calls=[{"id": "c1", "name": "exec_shell", "arguments": {"cmd": "rm -rf /"}}]),
        ScriptedRound(content=json.dumps({"intent": "explain", "hintLevel": 1, "message": "已恢复"}, ensure_ascii=False)),
    ]
    from app.agents.context import build_initial_messages

    run = run_agent(provider, build_initial_messages("q", {}, False), ctx)
    assert run.tool_calls[0].ok is False and "未知工具" in run.tool_calls[0].error
    assert "已恢复" in run.final_content  # 错误结果回填后模型恢复


def test_runtime_bad_args_recovers(agent_client: TestClient, db_session):
    pid = _make_cpp_project(agent_client)
    ctx = _runtime_db_ctx(agent_client, db_session, pid)
    provider = MockProvider()
    provider.scripted_rounds = [
        ScriptedRound(tool_calls=[{"id": "c1", "name": "read_project_file", "arguments": {"path": "../evil"}}]),
        ScriptedRound(content=json.dumps({"intent": "hint", "hintLevel": 1, "message": "ok"}, ensure_ascii=False)),
    ]
    from app.agents.context import build_initial_messages

    run = run_agent(provider, build_initial_messages("q", {}, False), ctx)
    assert run.tool_calls[0].ok is False


def test_runtime_round_budget_forces_final():
    # 无 db 依赖的工具（用 mock 工具上下文跑纯循环）
    ctx = ToolContext(db=None, project_id="00000000-0000-4000-8000-0000000000aa")
    provider = MockProvider()
    # 模型永远要调用工具，直到预算强制收尾（默认脚本第 2 轮会最终——这里覆写为持续要工具）
    provider.scripted_rounds = [
        ScriptedRound(tool_calls=[{"id": f"c{i}", "name": "list_project_files", "arguments": {}}])
        for i in range(10)
    ]
    from app.agents.context import build_initial_messages
    from app.agents.schemas import AgentError

    # 无 db：list_project_files 会失败（db=None），但循环继续消耗轮数直至耗尽
    with pytest.raises(AgentError):
        run_agent(provider, build_initial_messages("q", {}, False), ctx, AgentBudget(max_rounds=3))


def test_runtime_tool_call_budget():
    ctx = ToolContext(db=None, project_id="00000000-0000-4000-8000-0000000000aa")
    provider = MockProvider()
    provider.scripted_rounds = [
        ScriptedRound(tool_calls=[{"id": "c1", "name": "list_project_files", "arguments": {}}]),
        ScriptedRound(tool_calls=[{"id": "c2", "name": "list_project_files", "arguments": {}}]),
        # 调用预算=1：第二轮的调用触发 budget-calls → 注入收尾 → 下一轮（脚本空→默认最终）
    ]
    from app.agents.context import build_initial_messages

    run = run_agent(provider, build_initial_messages("q", {}, False), ctx, AgentBudget(max_rounds=5, max_tool_calls=1))
    assert len(run.tool_calls) == 1
    assert run.stop_reason == "budget-calls"


def test_runtime_token_budget():
    ctx = ToolContext(db=None, project_id="00000000-0000-4000-8000-0000000000aa")
    provider = MockProvider()
    provider.scripted_rounds = [
        ScriptedRound(tool_calls=[{"id": "c1", "name": "list_project_files", "arguments": {}}]),
        ScriptedRound(content=json.dumps({"intent": "hint", "hintLevel": 1, "message": "done"}, ensure_ascii=False)),
    ]
    from app.agents.context import build_initial_messages

    run = run_agent(provider, build_initial_messages("q", {}, False), ctx, AgentBudget(max_total_tokens=10))
    assert run.stop_reason == "budget-tokens"  # 第一轮即超预算 → 收尾
    assert "done" in run.final_content


def test_runtime_no_tools_direct_answer():
    ctx = ToolContext(db=None, project_id="00000000-0000-4000-8000-0000000000aa")
    provider = MockProvider()
    provider.scripted_rounds = [
        ScriptedRound(content=json.dumps({"intent": "question", "hintLevel": 0, "message": "你觉得呢？"}, ensure_ascii=False)),
    ]
    from app.agents.context import build_initial_messages

    run = run_agent(provider, build_initial_messages("q", {}, False), ctx)
    assert run.rounds == 1 and run.tool_calls == []


def test_agent_record_dicts_shape():
    from app.agents.schemas import ToolCallRecord

    out = agent_record_to_dicts([
        ToolCallRecord(tool="t", args={"a": 1}, ok=True, round=1, duration_ms=5, summary="s"),
    ])
    assert out[0]["tool"] == "t" and out[0]["durationMs"] == 5


# ---------------------------------------------------------------- Tutor 集成（API 级）


def test_tutor_agent_flow_records_tool_trace(agent_client: TestClient, monkeypatch, db_session):
    from app.domains.concepts.service import ensure_seed_concepts

    ensure_seed_concepts(db_session)
    pid = _make_cpp_project(agent_client)
    agent_client.get(f"/api/v1/plans/{pid}")
    _put_file(agent_client, pid, "src/tasks/task1_address.cpp", "// student code")

    provider = MockProvider()
    final = {
        "intent": "hint", "hintLevel": 2, "message": "先看第 5 行的 & 运算符。",
        "targetConceptIds": ["cpp.addresses"], "explanation": "基于真实文件",
        "confidence": 0.8, "workspaceActions": [],
    }
    provider.scripted_rounds = [
        ScriptedRound(tool_calls=[{"id": "c1", "name": "list_project_files", "arguments": {}}]),
        ScriptedRound(tool_calls=[{"id": "c2", "name": "get_current_task", "arguments": {}}]),
        ScriptedRound(content=json.dumps(final, ensure_ascii=False)),
    ]
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)

    resp = agent_client.post("/api/v1/tutor/turns", json={
        "projectId": pid,
        "question": "为什么 &x 输出的是地址？",
        "extras": {"currentTaskId": "cpp-ptr-1-address"},
    })
    assert resp.status_code == 201, resp.text
    decision = resp.json()["decision"]
    # 工具轨迹来自真实后端执行记录
    assert decision["agentRounds"] == 3
    tools = [t["tool"] for t in decision["toolCalls"]]
    assert tools == ["list_project_files", "get_current_task"]
    assert all(t["ok"] for t in decision["toolCalls"])
    # 最终决策照常通过 Policy Gate
    assert decision["outcome"] == "accepted" and decision["hintLevel"] == 2


def test_tutor_agent_h4_gate_still_enforced(agent_client: TestClient, monkeypatch, db_session):
    pid = _make_cpp_project(agent_client)
    provider = MockProvider()
    provider.scripted_rounds = [
        ScriptedRound(content=json.dumps({
            "intent": "hint", "hintLevel": 4,  # 未请求答案级帮助
            "message": "完整答案……", "targetConceptIds": [],
            "explanation": "", "confidence": 0.5,
        })),
    ]
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)
    resp = agent_client.post("/api/v1/tutor/turns", json={
        "projectId": pid, "question": "给我答案", "requestAnswerLevel": False,
    })
    decision = resp.json()["decision"]
    assert decision["outcome"] == "degraded" and decision["hintLevel"] == 1
    assert "H4" in decision["outcomeReason"] or "答案级" in decision["outcomeReason"]


def test_tutor_agent_a2_patch_still_gated(agent_client: TestClient, monkeypatch, db_session):
    pid = _make_cpp_project(agent_client)
    provider = MockProvider()
    provider.scripted_rounds = [
        ScriptedRound(content=json.dumps({
            "intent": "hint", "hintLevel": 2, "message": "提示",
            "targetConceptIds": [], "explanation": "", "confidence": 0.5,
            "workspaceActions": [{"kind": "propose-patch", "reason": "r",
                                  "payload": {"path": "a.cpp", "description": "d"}}],
        })),
    ]
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)
    resp = agent_client.post("/api/v1/tutor/turns", json={
        "projectId": pid, "question": "帮我改", "requestAnswerLevel": False,
    })
    decision = resp.json()["decision"]
    assert decision["workspaceActions"] == []  # A2 未随答案级请求 → 移除


def test_tutor_backward_compat_non_tool_provider(agent_client: TestClient, monkeypatch, db_session):
    """Provider 不支持工具（supports_tools=False）→ 走原单次 chat 路径。"""
    from app.ai.provider import LLMProvider, LLMResult

    class LegacyProvider(LLMProvider):
        name = "legacy"
        supports_tools = False

        def __init__(self):
            self.calls = []

        def chat(self, system, user):
            self.calls.append(1)
            return LLMResult(
                content=json.dumps({"intent": "explain", "hintLevel": 1, "message": "旧路径"}),
                prompt_tokens=10, completion_tokens=5, model="legacy",
            )

    provider = LegacyProvider()
    monkeypatch.setattr("app.domains.tutor.router.get_provider", lambda: provider)
    pid = _make_cpp_project(agent_client)
    resp = agent_client.post("/api/v1/tutor/turns", json={"projectId": pid, "question": "q"})
    assert resp.status_code == 201
    decision = resp.json()["decision"]
    assert decision["message"] == "旧路径"
    assert decision["toolCalls"] == [] and decision["agentRounds"] == 0
    assert len(provider.calls) == 1


# ---------------------------------------------------------------- P7 稳定性修复回归


def test_structured_truncate_keeps_valid_json():
    """结构化截断：超限结果的 tool 消息仍是合法 JSON（P6 字符串截断会损坏）。"""
    import json as _json

    from app.agents.registry import structured_truncate

    big = {"files": [{"path": f"src/mod{i}/very_long_name.cpp",
                      "content": "x" * 5000} for i in range(50)]}
    out = structured_truncate(big, 200)
    dumped = _json.dumps(out, ensure_ascii=False)  # 必须可序列化
    assert len(dumped) < len(_json.dumps(big))
    assert "截断" in dumped or "截断" in dumped  # ensure_ascii 转义后按转义形式断言

    # registry.execute_tool 路径：超限结果 summary 是合法 JSON
    from app.agents.registry import ToolRegistry, execute_tool
    from app.agents.schemas import ToolSpec

    reg = ToolRegistry("test-trunc")
    reg.register(ToolSpec(
        name="big_list", description="d",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda ctx: {"items": ["x" * 4000] * 100},
        max_result_chars=1000,
    ))
    record = execute_tool(reg.get("big_list"), ToolContext(db=None, project_id="00000000-0000-4000-8000-0000000000aa"), {}, 1)
    assert record.ok
    _json.loads(record.summary)  # 不抛 = 合法 JSON


def test_agent_registries_isolated():
    """Agent 级白名单：Tutor 工具在 architect 注册表中不可见，反之亦然。"""
    from app.agents.registry import architect_registry, tutor_registry
    from app.agents.schemas import ToolSpec

    tutor_names = set(tutor_registry.names())
    arch_names = set(architect_registry.names())
    assert "read_project_file" in tutor_names
    # 尚未注册 architect 工具时为空（后续 course_generation 会注册）
    # 关键：tutor 工具不在 architect 白名单
    assert not (tutor_names & arch_names)

    # architect 注册一个工具后，tutor 看不到
    architect_registry.register(ToolSpec(
        name="get_repository_metadata", description="d",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda ctx: {"ok": True},
    ))
    assert "get_repository_metadata" in architect_registry.names()
    assert "get_repository_metadata" not in tutor_registry.names()
    import pytest as _pytest
    from app.agents.registry import UnknownToolError
    with _pytest.raises(UnknownToolError):
        tutor_registry.get("get_repository_metadata")


def test_idempotent_registration():
    from app.agents.registry import ToolRegistry
    from app.agents.schemas import ToolSpec

    reg = ToolRegistry("t")
    spec = ToolSpec(name="x", description="d",
                    parameters={"type": "object", "properties": {}, "required": []},
                    handler=lambda ctx: {})
    reg.register(spec)
    reg.register(spec)  # 幂等
    import pytest as _pytest
    with _pytest.raises(ValueError):
        reg.register(ToolSpec(name="x", description="d",
                              parameters={"type": "object", "properties": {}, "required": []},
                              handler=lambda ctx: 1))  # 同名异处理器 → 拒绝


def test_tool_timeout_and_error_recorded():
    """工具抛异常/超时 → 错误记录，不崩循环。"""
    from app.agents.registry import ToolRegistry, execute_tool
    from app.agents.schemas import ToolSpec

    reg = ToolRegistry("t")
    reg.register(ToolSpec(
        name="boom", description="d",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda ctx: (_ for _ in ()).throw(RuntimeError("db exploded")),
    ))
    record = execute_tool(reg.get("boom"), ToolContext(db=None, project_id="00000000-0000-4000-8000-0000000000aa"), {}, 1)
    assert record.ok is False and "db exploded" in record.error
    assert record.duration_ms >= 0
