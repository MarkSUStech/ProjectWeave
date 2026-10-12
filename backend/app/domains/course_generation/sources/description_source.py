"""描述驱动的课程源（P7.3 补充）：从项目规格生成课程（不依赖 GitHub）。

与 GitHub Adapter 同构——产出相同的 RepoSnapshot 结构，下游流水线
（analyzer → scoper → generator → verifier）完全复用。
区别：来源不是仓库代码，而是用户描述的项目规格（标题/描述/功能/栈）。
"""

from __future__ import annotations

from app.domains.course_generation.sources.github_adapter import RepoSnapshot


def build_description_source(project_spec: dict) -> RepoSnapshot:
    """从项目规格构造合成快照：README 含完整规格，供 AI 理解要做什么。"""
    stack = project_spec.get("stack") or []
    features = project_spec.get("target_features") or project_spec.get("targetFeatures") or []
    non_goals = project_spec.get("non_goals") or project_spec.get("nonGoals") or []
    mode = project_spec.get("mode", "rebuild")
    complexity = project_spec.get("complexity", "medium")

    readme = (
        f"# {project_spec.get('title', 'Untitled Project')}\n\n"
        f"## 项目描述\n{project_spec.get('description', '')}\n\n"
        f"## 技术栈\n{', '.join(stack) if stack else '未指定（由课程设计者选择）'}\n\n"
        f"## 目标功能\n" + ("\n".join(f"- {f}" for f in features) if features else "- 未指定") + "\n"
    )
    if non_goals:
        readme += f"\n## 非目标\n" + "\n".join(f"- {ng}" for ng in non_goals) + "\n"
    readme += (
        f"\n## 项目模式\n{mode}\n\n## 复杂度\n{complexity}\n\n"
        "> 这是一个由用户描述的项目。没有现有代码仓库——"
        "你需要从零设计并实现这个项目的核心功能。\n"
    )

    primary_lang = _detect_language(stack)

    return RepoSnapshot(
        owner="projectweave",
        repo="user-project",
        default_branch="main",
        commit_sha="d" * 40,
        meta={
            "description": project_spec.get("description", ""),
            "language": primary_lang,
            "topics": stack,
            "stars": None,
        },
        tree=[
            {"path": "README.md", "type": "blob", "size": len(readme)},
        ],
        files={"README.md": readme},
        license={"spdx": None, "source": None, "needs_review": False,
                 "note": "用户原创描述，不涉及第三方许可"},
        stats={"treeEntries": 1, "textFiles": 1, "totalBytes": len(readme),
               "source": "description"},
    )


def _detect_language(stack: list[str]) -> str:
    joined = " ".join(stack).lower()
    if any(k in joined for k in ("c++", "cpp", "clang")):
        return "C++"
    if any(k in joined for k in ("typescript", "javascript", "react", "vue", "node")):
        return "TypeScript"
    return "Python"
