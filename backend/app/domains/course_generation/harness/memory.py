"""Agent Working Memory + Loop Detector + Progress Tracker（P8.2.3.3，D51）。

Working Memory 只记录可验证工作状态（文件是否修改来自 ChangeApplier、
构建/测试来自真实沙箱），不信任模型自述。Loop Detector 以
工具+规范化参数+Revision+文件 Hash 指纹识别无增量调用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


def normalize_path_arg(path: str) -> str:
    """清理模型传入的路径参数：剥离包裹引号/空白（t4 死循环根因）。"""
    if not isinstance(path, str):
        return ""
    cleaned = path.strip().strip("`")
    while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        cleaned = cleaned[1:-1]
    return cleaned.strip()


@dataclass
class InspectedFile:
    path: str
    content_hash: str = ""
    revision: int = -1
    ranges: list = field(default_factory=list)   # [[offset, end], ...]
    reads: int = 0


@dataclass
class WorkingMemory:
    """Harness 维护的可验证工作记忆。"""

    task_id: str = ""
    goal: str = ""
    workspace_revision: int = 0
    inspected: dict[str, InspectedFile] = field(default_factory=dict)
    modified_files: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    known_problems: list[str] = field(default_factory=list)
    last_progress: str = ""
    rounds_since_progress: int = 0
    # 度量（真实计数）
    stats: dict = field(default_factory=lambda: {
        "cachedReads": 0, "repeatedReads": 0, "compactions": 0,
        "recoveries": 0, "meaningfulEdits": 0})

    def record_read(self, path: str, content_hash: str, revision: int,
                    offset: int, end: int) -> bool:
        """记录读取；返回 True=有新信息（首次/版本变化/新范围）。"""
        entry = self.inspected.get(path)
        if entry is None or entry.content_hash != content_hash \
                or entry.revision != revision:
            self.inspected[path] = InspectedFile(
                path=path, content_hash=content_hash, revision=revision,
                ranges=[[offset, end]], reads=1)
            return True
        entry.reads += 1
        # 新范围被已有区间并集完全覆盖 → 无新信息（区间合并判定）
        covered = False
        for start, stop in entry.ranges:
            if start <= offset and end <= stop:
                covered = True
                break
        if covered:
            return False
        entry.ranges.append([offset, end])
        # 合并相邻/重叠区间（保持并集最小表示）
        entry.ranges.sort()
        merged = [list(entry.ranges[0])]
        for start, stop in entry.ranges[1:]:
            if start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], stop)
            else:
                merged.append([start, stop])
        entry.ranges = merged
        return True

    def record_modification(self, path: str, step_note: str = "") -> None:
        if path not in self.modified_files:
            self.modified_files.append(path)
        self.stats["meaningfulEdits"] += 1
        self.rounds_since_progress = 0
        if step_note:
            self.last_progress = step_note

    def to_dict(self) -> dict:
        return {
            "taskId": self.task_id, "goal": self.goal,
            "workspaceRevision": self.workspace_revision,
            "inspectedFiles": [
                {"path": f.path, "contentHash": f.content_hash,
                 "revision": f.revision, "ranges": f.ranges, "reads": f.reads}
                for f in self.inspected.values()],
            "modifiedFiles": list(self.modified_files),
            "completedSteps": list(self.completed_steps),
            "knownProblems": list(self.known_problems[-6:]),
            "lastProgress": self.last_progress,
            "roundsSinceProgress": self.rounds_since_progress,
            "stats": dict(self.stats),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkingMemory":
        memory = cls(task_id=data.get("taskId", ""), goal=data.get("goal", ""))
        memory.workspace_revision = data.get("workspaceRevision", 0)
        for item in data.get("inspectedFiles") or []:
            memory.inspected[item["path"]] = InspectedFile(
                path=item["path"], content_hash=item.get("contentHash", ""),
                revision=item.get("revision", -1),
                ranges=item.get("ranges", []), reads=item.get("reads", 1))
        memory.modified_files = list(data.get("modifiedFiles") or [])
        memory.completed_steps = list(data.get("completedSteps") or [])
        memory.known_problems = list(data.get("knownProblems") or [])
        memory.last_progress = data.get("lastProgress", "")
        memory.rounds_since_progress = data.get("roundsSinceProgress", 0)
        memory.stats.update(data.get("stats") or {})
        return memory

    def summary_prompt(self) -> str:
        """Layer 3 上下文：紧凑工作记忆注入系统提示。"""
        lines = ["## 工作记忆（Harness 维护，可验证事实）"]
        if self.goal:
            lines.append(f"- 任务目标：{self.goal}")
        lines.append(f"- 当前 Workspace Revision：{self.workspace_revision}")
        if self.completed_steps:
            lines.append(f"- 已完成：{'；'.join(self.completed_steps[-5:])}")
        if self.modified_files:
            lines.append(f"- 已修改文件：{', '.join(self.modified_files[-10:])}")
        if self.inspected:
            read_list = "; ".join(
                f"{f.path}@r{f.revision}" for f in list(self.inspected.values())[-10:])
            lines.append(f"- 已读取（无需重复读取相同版本）：{read_list}")
        if self.known_problems:
            lines.append(f"- 已知问题：{'；'.join(self.known_problems[-3:])}")
        if self.last_progress:
            lines.append(f"- 最近有效进展：{self.last_progress}")
        lines.append(f"- 距上次有效进展轮数：{self.rounds_since_progress}")
        lines.append("- 路径参数不要带引号（read/apply 的 path 是裸字符串）")
        return "\n".join(lines)


class LoopDetector:
    """重复工具调用检测（指纹 = 工具 + 规范化参数 + Revision + 相关 Hash）。"""

    def __init__(self, warn_after: int = 1, hard_after: int = 3):
        self.warn_after = warn_after
        self.hard_after = hard_after
        self._history: dict[str, int] = field(default_factory=dict) if False else {}

    def fingerprint(self, tool: str, args: dict, revision: int,
                    file_hash: str = "") -> str:
        normalized = {
            "tool": tool,
            "path": normalize_path_arg(str(args.get("path", ""))),
            "offset": int(args.get("offset", 0) or 0),
            "revision": revision,
            "fileHash": file_hash,
        }
        return json.dumps(normalized, sort_keys=True)

    def observe(self, fingerprint: str) -> int:
        """记录观测，返回该指纹的第几次出现（1=首次）。"""
        self._history[fingerprint] = self._history.get(fingerprint, 0) + 1
        return self._history[fingerprint]

    def recent_repeat_ratio(self, last_n: int = 8) -> float:
        if not self._history:
            return 0.0
        repeats = sum(c - 1 for c in self._history.values())
        total = sum(self._history.values())
        return repeats / max(total, 1)
