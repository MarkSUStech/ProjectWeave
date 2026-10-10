"""指针关系图构建（P4.5b.1，真实调试数据）。

数据来源与验证策略（探针实测 lldb-dap 19，D38）：
- lldb-dap 19 的 variables 不提供 memoryReference（实测全 None）；
- 局部变量地址经 DAP evaluate 白名单表达式 `&<evaluateName>` 获取
  （服务端固定策略：evaluateName 必须匹配标识符/成员/下标链正则，
  不接受任何用户/AI 透传表达式；取地址无副作用）；
- 指针变量的 value 即所指地址（0x…）；**只有指针值与某变量地址精确
  相等才判为已验证指向**；无匹配 = 未解析（不虚构）；0x0 = 空指针；
- 上限：变量 30 个、evaluate 20 次/暂停、单次超时 5s；失败 → unknown。

输出 pointer_graph：
{
  "addresses": {变量名: "0x…" | null},          # null = 不可得
  "verifiedEdges": [{"from", "to", "address"}],  # 已验证指向
  "unresolvedPointers": [{"name", "value"}],     # 非空地址无匹配（如堆）
  "nullPointers": [{"name", "value"}],
  "evalLimitReached": bool
}
"""

from __future__ import annotations

import re

from app.domains.debugging.dap_client import DapClient, DapError

# 白名单：标识符（.成员 / ->成员 / [下标] 链，长度受限）——绝不透传任意表达式
SAFE_EVALUATE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:(?:\.|->)[A-Za-z_][A-Za-z0-9_]*|\[[0-9]{1,4}\]){0,3}$")
POINTER_VALUE = re.compile(r"^0x[0-9a-fA-F]{1,16}$")
EVAL_ADDRESS = re.compile(r"0x[0-9a-fA-F]{4,16}")
NULL_ADDRESS = "0x0000000000000000"

MAX_VARIABLES = 30
MAX_EVALUATIONS = 20
EVAL_TIMEOUT_S = 5.0


def parse_pointer_value(value: str) -> str | None:
    """解析指针显示值为地址（lldb: 0x00007fff…；不匹配返回 None）。"""
    text = value.strip()
    if POINTER_VALUE.match(text):
        return "0x" + text[2:].lower().rjust(16, "0")
    return None


def is_pointer_type(type_name: str | None) -> bool:
    if not type_name:
        return False
    return "*" in type_name or "&" in type_name


def _extract_eval_address(result: str) -> str | None:
    match = EVAL_ADDRESS.search(result)
    if match is None:
        return None
    return "0x" + match.group(0)[2:].lower().rjust(16, "0")


def build_pointer_graph(dap: DapClient, frame_id: int, variables: list[dict]) -> dict:
    """对当前帧的顶层层级变量构建已验证指针关系（全部真实调试数据）。

    只处理原始（非展开子项）变量：地址经 &name 求值，指针经 value 匹配。
    """
    graph: dict = {
        "addresses": {},
        "verifiedEdges": [],
        "unresolvedPointers": [],
        "nullPointers": [],
        "evalLimitReached": False,
    }
    top = [v for v in variables if SAFE_EVALUATE_NAME.match(v.get("evaluateName") or v.get("name") or "")]
    top = top[:MAX_VARIABLES]

    pointers: list[tuple[str, str]] = []  # (name, normalized address)
    addressable: list[str] = []  # 待求地址的候选（非指针优先）

    for var in top:
        name = var.get("name", "")
        value = str(var.get("value", ""))
        type_name = var.get("type")
        if is_pointer_type(type_name):
            addr = parse_pointer_value(value)
            if addr is not None and addr == NULL_ADDRESS:
                graph["nullPointers"].append({"name": name, "value": value})
            elif addr is not None:
                pointers.append((name, addr))
            else:
                # 指针但显示值不可解析（如被优化/复杂场景）→ 如实 unknown
                graph["unresolvedPointers"].append({"name": name, "value": value})
        else:
            addressable.append(var.get("evaluateName") or name)

    # 地址求值（上限内优先非指针变量；指针自身地址不参与匹配目标）
    evaluations = 0
    for name in addressable:
        if evaluations >= MAX_EVALUATIONS:
            graph["evalLimitReached"] = True
            break
        try:
            body = dap.send_request(
                "evaluate",
                {"expression": f"&{name}", "frameId": frame_id, "context": "repl"},
                timeout=EVAL_TIMEOUT_S,
            )
            evaluations += 1
            graph["addresses"][name] = _extract_eval_address(str(body.get("result", "")))
        except DapError:
            graph["addresses"][name] = None

    # 已验证关系：指针值与变量地址精确相等
    address_index = {addr: name for name, addr in graph["addresses"].items() if addr}
    for name, addr in pointers:
        target = address_index.get(addr)
        if target is not None:
            graph["verifiedEdges"].append({"from": name, "to": target, "address": addr})
        else:
            graph["unresolvedPointers"].append({"name": name, "value": addr})
    return graph
