"""工程上下文构建器（P8.2.1，D46）。

替代"按字母序截前 14 个文件"的策略：结构化 Manifest（全量路径+哈希+分类）
+ 按任务相关性选取完整关键文件（CMake/接口/测试注册全文进上下文）+
严格 Token 预算。摘要启发式均标记可信度，不冒充完整源码。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domains.course_generation.lessons.change_set import content_hash

# 上下文预算（字符近似 token；宁可少给全文、绝不超预算）
MAX_CONTEXT_CHARS = 56_000
CRITICAL_FILE_BONUS = {"cmakelists.txt": 100, ".cmake": 100}
HEADER_EXTS = (".hpp", ".h", ".hxx")
SOURCE_EXTS = (".cpp", ".cc", ".cxx")

_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
_FUNC_RE = re.compile(r"^[\w:<>,&*\s~]+\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const)?\s*;", re.MULTILINE)
_NS_RE = re.compile(r"\bnamespace\s+([A-Za-z_]\w*)")


def file_category(path: str) -> str:
    lower = path.lower()
    if "cmakelists.txt" in lower or lower.endswith(".cmake"):
        return "cmake"
    if lower.endswith(HEADER_EXTS):
        return "header"
    if _is_test_path(lower) and lower.endswith(SOURCE_EXTS):
        return "test"
    if lower.endswith(SOURCE_EXTS):
        return "source"
    return "other"


def _is_test_path(lower: str) -> bool:
    base = lower.rsplit("/", 1)[-1]
    return lower.startswith("tests/") or base.startswith("test_") or base.endswith("_test")


@dataclass
class FileMeta:
    path: str
    category: str
    hash: str
    size: int
    module: str          # 顶层目录（engine/tests/app/...）
    summary: str = ""    # header 的接口摘要（启发式，标可信度）


@dataclass
class ProjectContext:
    manifest: list[FileMeta] = field(default_factory=list)
    # 相关性选取后全文提供的文件（path → content）
    full_files: dict[str, str] = field(default_factory=dict)
    # 上一个已验证任务的契约（目标/测试名/manifest）
    prev_contract: dict = field(default_factory=dict)
    chars_used: int = 0
    truncated: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        lines = ["## 项目 Manifest（全部文件；★=本次已附全文）"]
        for meta in self.manifest:
            star = "★" if meta.path in self.full_files else " "
            note = f"｜摘要(启发式): {meta.summary}" if meta.summary else ""
            lines.append(f"{star} {meta.path} [{meta.category}] hash={meta.hash} {meta.size}B{note}")
        if self.prev_contract:
            lines.append("\n## 上一任务已验证契约（不得破坏）")
            lines.append(f"- buildManifest: {self.prev_contract.get('buildManifest')}")
            lines.append(f"- 验证过的测试: {self.prev_contract.get('verifiedTests')}")
        for path, content in self.full_files.items():
            lines.append(f"\n## 文件全文：{path}")
            lines.append("```")
            lines.append(content)
            lines.append("```")
        return "\n".join(lines)


def header_summary(content: str, confidence: str = "partial") -> str:
    """头文件接口启发式摘要（明确标记可信度，不冒充完整源码）。"""
    classes = _CLASS_RE.findall(content)[:8]
    funcs = _FUNC_RE.findall(content)[:12]
    namespaces = _NS_RE.findall(content)[:4]
    parts = []
    if namespaces:
        parts.append("ns:" + ",".join(namespaces))
    if classes:
        parts.append("class:" + ",".join(classes))
    if funcs:
        parts.append("methods:" + ",".join(funcs))
    return (f"[{confidence}] " + " ".join(parts))[:300] if parts else ""


def _relevance_score(meta: FileMeta, keywords: list[str], task_text: str) -> int:
    """确定性相关性评分：关键构建文件永远高分；命中任务关键词加分。"""
    score = 0
    for hint, bonus in CRITICAL_FILE_BONUS.items():
        if hint in meta.path.lower():
            score += bonus
    if meta.category == "header":
        score += 40  # 接口必读
    haystack = (meta.path + " " + (meta.summary or "")).lower()
    for keyword in keywords:
        if keyword and keyword.lower() in haystack:
            score += 30
    stem = meta.path.rsplit("/", 1)[-1].split(".")[0].lower()
    if stem and stem in task_text.lower():
        score += 25
    return score


def build_project_context(
    snapshot_files: dict[str, str],
    task_spec: dict,
    prev_contract: dict | None = None,
    budget_chars: int = MAX_CONTEXT_CHARS,
) -> ProjectContext:
    """构建任务上下文：全量 Manifest + 相关文件全文（预算内，从不静默截断文件体）。

    关键不变量：进入 full_files 的文件是**完整内容**（不再 2200 截断）；
    超预算时整文件降级为 Manifest 条目（记入 truncated，可观测）。
    """
    ctx = ProjectContext(prev_contract=prev_contract or {})
    task_text = " ".join([
        task_spec.get("title", ""), task_spec.get("description", ""),
        " ".join(task_spec.get("deliverables") or []),
        " ".join(task_spec.get("acceptanceCriteria") or []),
    ])
    # 任务关键词：词干（去复数）后 ≥3 字符
    keywords = [w.rstrip("s") for w in re.findall(r"[A-Za-z_]{3,}", task_text)]

    metas = []
    for path in sorted(snapshot_files):
        content = snapshot_files[path]
        meta = FileMeta(path=path, category=file_category(path),
                        hash=content_hash(content), size=len(content),
                        module=path.split("/", 1)[0] if "/" in path else ".")
        if meta.category == "header":
            meta.summary = header_summary(content)
        metas.append(meta)
    ctx.manifest = metas

    ranked = sorted(metas, key=lambda m: -_relevance_score(m, keywords, task_text))
    used = 0
    for meta in ranked:
        if used >= budget_chars:
            ctx.truncated.append(meta.path)
            continue
        content = snapshot_files[meta.path]
        if used + len(content) > budget_chars:
            ctx.truncated.append(meta.path)
            continue
        ctx.full_files[meta.path] = content
        used += len(content)
    ctx.chars_used = used
    return ctx
