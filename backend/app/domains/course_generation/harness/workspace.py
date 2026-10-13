"""Course Workspace（P8.2.3，D48）：Agent 的版本化隔离工作区。

逻辑结构（DB JSON 快照，非磁盘目录）：
- reference_files：当前任务候选参考工程（累积基线 + 本任务变更）
- starter_overlay：挖空覆盖（待实现部分）
- manifest / instructions / hints：课程材料
- revisions：每次变更的不可变记录（可回滚、可审计）

所有修改经确定性 ChangeApplier；Agent 无法触碰验收规则/隐藏材料。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domains.course_generation.lessons.change_set import (
    FileChange,
    content_hash,
)


def workspace_hash(files: dict[str, str]) -> str:
    from app.domains.course_generation.lessons.consistency_validator import (
        snapshot_hash_of,
    )

    return snapshot_hash_of(files)


@dataclass
class WorkspaceSnapshot:
    """某一 Revision 的完整工作区状态。"""

    revision: int
    reference_files: dict[str, str] = field(default_factory=dict)
    starter_overlay: dict[str, str] = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    instructions: dict = field(default_factory=dict)
    hints: list = field(default_factory=list)
    change_log: list = field(default_factory=list)   # 本 Revision 的变更清单


class CourseWorkspace:
    """内存态工作区（持久化由 session 行的 JSON 字段承载）。"""

    def __init__(self, data: dict | None = None):
        data = data or {}
        self.revision: int = int(data.get("revision", 0))
        self.reference_files: dict[str, str] = dict(data.get("referenceFiles") or {})
        self.starter_overlay: dict[str, str] = dict(data.get("starterOverlay") or {})
        self.manifest: dict = dict(data.get("manifest") or {})
        self.instructions: dict = dict(data.get("instructions") or {})
        self.hints: list = list(data.get("hints") or [])
        self.revisions: list[dict] = list(data.get("revisions") or [])
        self.base_snapshot: dict = dict(data.get("baseSnapshot") or {})  # 已验证基线

    def to_dict(self) -> dict:
        return {
            "revision": self.revision,
            "referenceFiles": self.reference_files,
            "starterOverlay": self.starter_overlay,
            "manifest": self.manifest,
            "instructions": self.instructions,
            "hints": self.hints,
            "revisions": self.revisions,
            "baseSnapshot": self.base_snapshot,
        }

    # ---------------- 读 ----------------

    def list_files(self, prefix: str = "") -> list[dict]:
        out = []
        for path in sorted(self.reference_files):
            if prefix and not path.startswith(prefix):
                continue
            content = self.reference_files[path]
            category = ("starter:" if path in self.starter_overlay else "ref:")
            out.append({
                "path": path, "size": len(content),
                "hash": content_hash(content),
                "category": category + _category(path),
            })
        return out

    def read_file(self, path: str, offset: int = 0, limit: int = 400) -> dict:
        content = self.reference_files.get(path)
        if content is None:
            return {"error": f"文件不存在：{path}"}
        lines = content.splitlines()
        window = lines[offset:offset + limit]
        starter_version = self.starter_overlay.get(path)
        return {
            "path": path, "revision": self.revision,
            "totalLines": len(lines), "offset": offset,
            "content": "\n".join(window),
            "starterVersionExists": starter_version is not None,
            "starterVersionPreview": (starter_version or "")[:400] or None,
        }

    # ---------------- 写（确定性，原子） ----------------

    def apply_changes(self, changes: list[FileChange]) -> dict:
        """应用文件变更（reference/starter 两组），原子推进 Revision。

        starter 组的基线 = 当前参考版（服务端权威回填，D47 两阶段关系）；
        reference 组严格校验 baseHash。任何冲突整体失败，不改当前状态。
        """
        from app.domains.course_generation.lessons.change_applier import (
            apply_file_changes,
        )

        ref_changes = [c for c in changes if c.target != "starter"]
        starter_changes = [c for c in changes if c.target == "starter"]

        ref_result = apply_file_changes(self.reference_files, ref_changes)
        if not ref_result.ok:
            return {"ok": False, "conflicts": ref_result.conflicts}

        new_reference = ref_result.files
        normalized_starter = []
        for change in starter_changes:
            ref_version = new_reference.get(change.path)
            if (change.change_category == "source" and ref_version is not None
                    and change.operation in ("create", "update")):
                normalized_starter.append(change.model_copy(update={
                    "operation": "update",
                    "base_hash": content_hash(ref_version)}))
            else:
                normalized_starter.append(change)

        new_overlay = dict(self.starter_overlay)
        starter_files = {**new_reference, **new_overlay}
        starter_result = apply_file_changes(starter_files, normalized_starter)
        if not starter_result.ok:
            return {"ok": False, "conflicts": starter_result.conflicts}
        new_overlay = {p: c for p, c in starter_result.files.items()
                       if new_reference.get(p) != c or p in self.starter_overlay}
        # 清理与参考一致的 overlay 项（无意义覆盖）

        self.reference_files = new_reference
        self.starter_overlay = new_overlay
        self.revision += 1
        entry = {
            "revision": self.revision,
            "hash": workspace_hash(new_reference),
            "applied": [*ref_result.applied, *starter_result.applied],
            "at": _now_iso(),
        }
        self.revisions.append(entry)
        return {"ok": True, "revision": self.revision,
                "applied": entry["applied"], "workspaceHash": entry["hash"]}

    def update_material(self, *, manifest=None, instructions=None, hints=None) -> None:
        """更新课程材料元数据（manifest/instructions/hints）——同样推进 Revision。"""
        if manifest is not None:
            self.manifest = manifest
        if instructions is not None:
            self.instructions = instructions
        if hints is not None:
            self.hints = hints
        self.revision += 1
        self.revisions.append({
            "revision": self.revision,
            "hash": workspace_hash(self.reference_files),
            "applied": [{"path": "<material>", "operation": "update"}],
            "at": _now_iso(),
        })

    def rollback_to_revision(self, revision: int) -> dict:
        """回滚到历史 Revision（不删除历史：追加回滚记录）。"""
        # 重建：基线 + 依次重放到目标 revision 的变更
        target = next((r for r in self.revisions if r["revision"] == revision), None)
        if target is None:
            return {"ok": False, "error": f"Revision 不存在：{revision}"}
        replay = CourseWorkspace({
            "revision": 0,
            "referenceFiles": self.base_snapshot.get("referenceFiles", {}),
            "starterOverlay": self.base_snapshot.get("starterOverlay", {}),
            "manifest": self.base_snapshot.get("manifest", {}),
            "instructions": self.base_snapshot.get("instructions", {}),
            "hints": self.base_snapshot.get("hints", []),
            "revisions": [],
            "baseSnapshot": self.base_snapshot,
        })
        for rev in self.revisions:
            if rev["revision"] > revision:
                break
            for applied in rev.get("applied", []):
                path = applied.get("path", "")
                if not path or path == "<material>":
                    continue
                # 材料修订无法从 change_log 完整重放——回滚仅恢复文件层，
                # 材料以当前为准（如实记录限制）
                continue
        # 简化实现：文件级回滚需要完整内容快照；记录目标并标记待重放。
        # MVP 采用"重放不可行即拒绝"的诚实语义，防止半恢复状态。
        return {"ok": False,
                "error": "文件级回滚需要内容快照重放；MVP 请用 rollback_to_checkpoint"}

    def material_dict(self) -> dict:
        """→ 验证器材料形状（starterFiles/testFiles/referenceFiles 全量）。"""
        starter_all = dict(self.reference_files)
        starter_all.update(self.starter_overlay)
        starters, tests = _split(starter_all)
        ref_starters, ref_tests = _split(self.reference_files)
        return {
            "instructions": self.instructions or {"title": "任务"},
            "starterFiles": starters,
            "testFiles": tests,
            "referenceFiles": [*ref_starters, *ref_tests],
            "buildManifest": self.manifest,
            "hints": self.hints,
        }


def _category(path: str) -> str:
    lower = path.lower()
    if "cmakelists.txt" in lower or lower.endswith(".cmake"):
        return "cmake"
    if lower.startswith("tests/") or "test" in lower.rsplit("/", 1)[-1]:
        return "test"
    if lower.endswith((".hpp", ".h")):
        return "header"
    return "source"


def _split(files: dict[str, str]):
    starters = [{"path": p, "content": c} for p, c in sorted(files.items())
                if _category(p) != "test"]
    tests = [{"path": p, "content": c} for p, c in sorted(files.items())
             if _category(p) == "test"]
    return starters, tests


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
