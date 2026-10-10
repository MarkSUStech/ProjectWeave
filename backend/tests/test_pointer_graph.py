"""指针图构建纯单元测试：白名单正则、地址解析、验证匹配、上限、失败态。"""

import pytest

from app.domains.debugging.dap_client import DapError
from app.domains.debugging.pointer_graph import (
    build_pointer_graph,
    is_pointer_type,
    parse_pointer_value,
)


class FakeDap:
    """只支持白名单 evaluate 的假客户端。"""

    def __init__(self, addresses: dict[str, str], fail_for: set[str] | None = None):
        self.addresses = addresses
        self.fail_for = fail_for or set()
        self.calls: list[str] = []

    def send_request(self, command, arguments=None, timeout=15.0):
        assert command == "evaluate", f"非白名单命令：{command}"
        expr = arguments["expression"]
        self.calls.append(expr)
        if expr in self.fail_for:
            raise DapError(f"evaluate failed: {expr}")
        if expr in self.addresses:
            return {"result": f"(void *) $0 = {self.addresses[expr]}", "type": "void *"}
        raise DapError(f"not allowed: {expr}")


def var(name, value, type_, evaluate_name=None):
    return {"name": name, "value": value, "type": type_, "evaluateName": evaluate_name or name}


# ---------------------------------------------------------------- 解析


def test_parse_pointer_value_normalizes():
    assert parse_pointer_value("0x7fffec48") == "0x000000007fffec48"
    assert parse_pointer_value("0x00007fffffffec48") == "0x00007fffffffec48"
    assert parse_pointer_value("0x0000000000000000") == "0x0000000000000000"
    assert parse_pointer_value("(null)") is None
    assert parse_pointer_value("10") is None
    assert parse_pointer_value("summary") is None


def test_is_pointer_type():
    assert is_pointer_type("int *") is True
    assert is_pointer_type("int **") is True
    assert is_pointer_type("char &") is True
    assert is_pointer_type("int") is False
    assert is_pointer_type(None) is False


# ---------------------------------------------------------------- 构建


def test_verified_edge_only_on_exact_address_match():
    dap = FakeDap({"&x": "0x0000000000000100"})
    variables = [var("x", "10", "int"), var("p", "0x0000000000000100", "int *")]
    graph = build_pointer_graph(dap, frame_id=1, variables=variables)
    assert graph["verifiedEdges"] == [{"from": "p", "to": "x", "address": "0x0000000000000100"}]
    assert graph["unresolvedPointers"] == []
    assert graph["nullPointers"] == []
    assert graph["addresses"]["x"] == "0x0000000000000100"


def test_heap_pointer_unresolved_not_faked():
    dap = FakeDap({"&x": "0x0000000000000100"})
    variables = [var("x", "10", "int"), var("hp", "0x000055555556b2b0", "int *")]
    graph = build_pointer_graph(dap, 1, variables)
    assert graph["verifiedEdges"] == []
    assert graph["unresolvedPointers"] == [{"name": "hp", "value": "0x000055555556b2b0"}]


def test_null_pointer_is_explicit_state():
    dap = FakeDap({})
    variables = [var("np", "0x0000000000000000", "int *")]
    graph = build_pointer_graph(dap, 1, variables)
    assert graph["nullPointers"] == [{"name": "np", "value": "0x0000000000000000"}]
    assert graph["verifiedEdges"] == []
    assert graph["unresolvedPointers"] == []


def test_evaluate_failure_yields_unknown_address():
    dap = FakeDap({}, fail_for={"&x"})
    variables = [var("x", "10", "int"), var("p", "0x0000000000000100", "int *")]
    graph = build_pointer_graph(dap, 1, variables)
    assert graph["addresses"]["x"] is None
    # 地址不可得 → 不画边；指针如实进未解析（不虚构，验收 F）
    assert graph["verifiedEdges"] == []
    assert graph["unresolvedPointers"] == [{"name": "p", "value": "0x0000000000000100"}]


def test_unparseable_pointer_value_is_unresolved():
    dap = FakeDap({})
    variables = [var("weird", "<parent is NULL>", "int *")]
    graph = build_pointer_graph(dap, 1, variables)
    assert graph["unresolvedPointers"] == [{"name": "weird", "value": "<parent is NULL>"}]


def test_unsafe_evaluate_names_are_skipped():
    dap = FakeDap({})
    variables = [
        var("ok", "1", "int", "ok"),
        var("bad", "1", "int", 'x; system("rm")'),  # 恶意 evaluateName
        var("deep", "1", "int", "a.b.c.d.e"),  # 超过 3 层链
    ]
    graph = build_pointer_graph(dap, 1, variables)
    assert "&ok" in dap.calls
    assert not any("system" in c for c in dap.calls)
    assert "&a.b.c.d.e" not in dap.calls


def test_evaluation_cap_enforced():
    dap = FakeDap({f"&v{i}": f"0x{i:016x}" for i in range(40)})
    variables = [var(f"v{i}", str(i), "int") for i in range(40)]
    graph = build_pointer_graph(dap, 1, variables)
    # 两个独立上限：变量截断 30；evaluate 上限 20（达到即标记）
    assert len(dap.calls) == 20
    assert graph["evalLimitReached"] is True
    assert len(graph["addresses"]) == 20


def test_pointer_to_pointer_no_self_address_eval():
    # 指针变量本身不求地址（其 value 即目标地址）；指向指针的匹配仍可经
    # 显式变量地址建立（如 int** q = &p：q.value == addr(&p)——&p 不在
    # 白名单求值集合内，故此处如实未解析）
    dap = FakeDap({"&x": "0x0000000000000100"})
    variables = [var("x", "10", "int"), var("p", "0x0000000000000100", "int *"), var("q", "0x00000000000000f0", "int **")]
    graph = build_pointer_graph(dap, 1, variables)
    assert [e["from"] for e in graph["verifiedEdges"]] == ["p"]
    assert graph["unresolvedPointers"] == [{"name": "q", "value": "0x00000000000000f0"}]
