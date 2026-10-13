"""确定性变更应用器（P8.2.1，D46）。

把 LessonChangeSet 应用到已验证的工程快照：路径校验、baseHash 乐观锁、
重复操作检测、删除保护（测试/CMake 注册/先前实现不可无据删除）、
原子性（失败不改原快照）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domains.course_generation.lessons.change_set import (
    LessonChangeSet,
    content_hash,
)

# 受保护路径类别：删除需谨慎（防绕过验证）
_PROTECTED_DELETE_HINTS = ("tests/", "cmakelists.txt", ".cmake")


@dataclass
class ApplyResult:
    ok: bool = False
    files: dict[str, str] = field(default_factory=dict)      # 应用后的完整快照
    applied: list[dict] = field(default_factory=list)        # {path, operation, hash}
    conflicts: list[dict] = field(default_factory=list)      # 结构化冲突


def _conflict(code: str, path: str, expected: str, actual: str,
              scope: str = "") -> dict:
    return {"errorCode": code, "filePath": path, "expected": expected,
            "actual": actual, "suggestedRepairScope": scope or path}


def apply_file_changes(base_files: dict[str, str], changes,
                       allow_deletions: bool = False) -> ApplyResult:
    """把一组 FileChange 应用到基线快照（原子：任一冲突即失败，不改基线）。"""
    result = ApplyResult(files=dict(base_files))
    seen: dict[str, str] = {}

    for change in changes:
        path = change.path
        if path in seen:
            result.conflicts.append(_conflict(
                "duplicate-change", path,
                f"每文件至多一个操作（已见 {seen[path]}）",
                f"重复请求 {change.operation}", ""))
            continue
        seen[path] = change.operation

        base_content = base_files.get(path)

        if change.operation == "create":
            if base_content is not None:
                result.conflicts.append(_conflict(
                    "create-exists", path, "新文件（基线中不存在）",
                    f"基线已存在（hash={content_hash(base_content)}）", path))
                continue
            result.files[path] = change.content

        elif change.operation == "update":
            if base_content is None:
                result.conflicts.append(_conflict(
                    "update-missing", path, "基线存在该文件",
                    "基线中不存在（应使用 create）", path))
                continue
            # 严格乐观锁（P8.2.2 恢复）：baseHash 缺失或不匹配一律拒绝。
            # LLM 抄错哈希由服务端「程序化回填」确定性修复
            # （repair_base_hashes），绝不静默覆盖。
            actual_hash = content_hash(base_content)
            if not change.base_hash:
                result.conflicts.append(_conflict(
                    "missing-base-hash", path, "update 必须提供 baseHash",
                    f"未提供（实际={actual_hash}）", path))
                continue
            if change.base_hash != actual_hash:
                result.conflicts.append(_conflict(
                    "base-hash-mismatch", path,
                    f"baseHash={change.base_hash}", f"实际={actual_hash}", path))
                continue
            result.files[path] = change.content

        else:  # delete
            if base_content is None:
                result.conflicts.append(_conflict(
                    "delete-missing", path, "基线存在该文件", "基线中不存在", path))
                continue
            protected = any(hint in path.lower() for hint in _PROTECTED_DELETE_HINTS)
            if protected and not allow_deletions:
                result.conflicts.append(_conflict(
                    "protected-delete", path, "删除测试/CMake 注册需显式许可与理由",
                    f"请求删除（reason={change.reason[:80]}）", path))
                continue
            if not change.base_hash or change.base_hash != content_hash(base_content):
                result.conflicts.append(_conflict(
                    "base-hash-mismatch", path, "delete 必须提供正确 baseHash",
                    f"实际={content_hash(base_content)}", path))
                continue
            del result.files[path]

        result.applied.append({
            "path": path, "operation": change.operation,
            "hash": content_hash(change.content) if change.operation != "delete" else None,
            "reason": change.reason, "changeCategory": change.change_category,
        })

    if result.conflicts:
        return ApplyResult(ok=False, files=dict(base_files),
                           applied=[], conflicts=result.conflicts)
    result.ok = True
    return result


def _merge_change_groups(primary, secondary) -> list:
    """reference/test 两组变更合并：同路径内容一致 → 取一；不一致 → 抛冲突。"""
    by_path: dict[str, object] = {}
    for change in primary:
        by_path.setdefault(change.path, change)
    result = list(primary)
    for change in secondary:
        existing = by_path.get(change.path)
        if existing is None:
            result.append(change)
            continue
        if existing.operation == change.operation and existing.content == change.content:
            continue  # 完全一致：去重（不产生 duplicate-change）
        raise _GroupConflict(
            f"组间冲突@{change.path}：reference={existing.operation}"
            f"/{content_hash(existing.content)}，test={change.operation}"
            f"/{content_hash(change.content)}（内容不一致）")
    return result


class _GroupConflict(RuntimeError):
    pass


def compose_project_files(base_files: dict[str, str], change_set: LessonChangeSet):
    """从已验证基线合成参考工程与 starter 工程。

    - reference = 基线 + referenceChanges + testChanges（测试属于工程）
    - starter   = 参考 + starterChanges（starter 声明的文件覆盖参考版本——
      通常是同一实现文件的挖空版；也支持新增纯 starter 文件）
    返回 (reference_result, starter_result)；两者共享冲突语义。
    """
    # 组间去重：LLM 常把测试文件同时归入 reference 与 test 两组——
    # 同一文件内容一致时合并（test 语义优先），不一致才是真冲突。
    try:
        merged = _merge_change_groups(change_set.reference_changes,
                                      change_set.test_changes)
    except _GroupConflict as exc:
        conflict = _conflict("cross-group-mismatch", str(exc).split("@")[-1].split("：")[0],
                             "reference/test 两组同文件内容一致", str(exc), "")
        return (ApplyResult(ok=False, files=dict(base_files), conflicts=[conflict]),
                ApplyResult(ok=False, files=dict(base_files), conflicts=[conflict]))
    reference = apply_file_changes(base_files, merged)
    if not reference.ok:
        return reference, ApplyResult(ok=False, files=dict(base_files),
                                      conflicts=reference.conflicts)
    # starter 组重复同上：与合成参考版比对由 update 语义处理（见下）
    # Starter Overlay Base（两阶段快照关系，D47）：starter 变更的基线是
    # 本轮服务端合成的参考版本——由服务端权威回填 baseHash（create-on-
    # existing 规范化为 update；update 的哈希以参考版为准重写）。挖空语义
    # 本就是"基于参考版修改"，不依赖 LLM 抄写哈希。
    starter_changes = []
    for change in change_set.starter_changes:
        ref_version = reference.files.get(change.path)
        if (change.change_category == "source" and ref_version is not None
                and change.operation in ("create", "update")):
            starter_changes.append(change.model_copy(update={
                "operation": "update",
                "base_hash": content_hash(ref_version),
            }))
        else:
            starter_changes.append(change)
    starter = apply_file_changes(reference.files, starter_changes)
    return reference, starter


def hash_only_conflicts(conflicts: list[dict]) -> bool:
    """冲突是否全部为哈希类（可安全程序化回填）。"""
    return bool(conflicts) and all(
        c.get("errorCode") in ("base-hash-mismatch", "missing-base-hash")
        for c in conflicts)


def repair_base_hashes(base_files: dict[str, str], changes):
    """确定性哈希回填：update/delete 的 baseHash 以服务端当前内容为准重写。

    仅当冲突全部为哈希类时由调用方使用（变更内容本身未被判有问题）。
    返回新的 FileChange 列表（原列表不变）。
    """
    repaired = []
    for change in changes:
        if change.operation in ("update", "delete") and change.path in base_files:
            actual = content_hash(base_files[change.path])
            if change.base_hash != actual:
                repaired.append(change.model_copy(update={"base_hash": actual}))
                continue
        repaired.append(change)
    return repaired
