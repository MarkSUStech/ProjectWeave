"""Blueprint Generator（Project Scoper + 课程蓝图生成，P7.1）。

Rebuild Track：从原项目功能/架构反推"从零逐步实现"的开发过程，
不按原目录切课。分析结果 + 现有知识图谱作为输入；LLM 产出蓝图 JSON，
随后交确定性 Validator；不合法时携带错误进入有限修复轮（每轮一次
无工具 LLM 调用）。
"""

from __future__ import annotations

import json

GENERATOR_SYSTEM_PROMPT = """你是 ProjectWeave 的 Course Architect（课程蓝图设计者）。
任务：基于仓库分析结果，设计一门"从零重建式"（Rebuild Track）项目课程——
学习者从空项目开始，逐步实现与原项目**核心行为等价**的独立软件，
不要求逐行复刻原源码。

## 设计原则
- 里程碑 = 可运行、可验证的功能切片，由简到繁形成依赖链（DAG）；
- 每个任务小而具体，有明确交付物与验收条件；
- testStrategy 只描述"应当如何测试"，不得声称测试已通过或已存在；
- 知识点优先引用现有知识图谱（KNOWN_CONCEPTS 列表）；图谱外的知识
  一律作为候选概念（is_existing=false）；
- sourceEvidence.path 必须是 SOURCE_FILES 列表中存在的路径——
  没有依据的结论不要写；
- 尊重 RUNTIME_LIMITS：当前运行环境做不到的（如 GPU、数据库服务），
  放入 non_goals 或缩减方案；
- 全部内容中文（字段名保持英文）。

## 输出（最终必须是严格一个 JSON 对象，无其他文本；结构如下）
{
  "project": {
    "title": "课程标题", "description": "课程描述",
    "sourceUrl": "<原样填入 SOURCE.url>", "commitSha": "<SOURCE.commitSha>",
    "license": <原样填入 SOURCE.license>,
    "techStack": [...], "finalArtifact": "学完后学习者拥有什么",
    "targetLevel": "beginner|intermediate|advanced",
    "difficulty": "easy|medium|hard",
    "goals": [...], "nonGoals": [...],
    "runtimeRequirements": [...],
    "evidence": [{"path": "...", "note": "...", "lines": ""}]
  },
  "milestones": [
    {"milestoneId": "ms-1", "title": "...", "description": "...",
     "targetFeatures": [...], "deliverables": ["至少一个"],
     "dependsOn": [], "acceptanceCriteria": ["至少一条"],
     "estimatedEffortBand": "small|medium|large"}
  ],
  "tasks": [
    {"taskId": "task-1-1", "milestoneId": "ms-1", "title": "...",
     "description": "...", "dependsOn": [], "requiredConcepts": ["已有或候选概念 id"],
     "learningObjectives": [...], "expectedFiles": [...],
     "deliverables": ["至少一个"], "acceptanceCriteria": [...],
     "testStrategy": "如何测试（不声称已通过）", "hintsOutline": ["L1 方向", "L2 概念", "L3 结构"],
     "sourceEvidence": [{"path": "必须是 SOURCE_FILES 内的路径", "note": "...", "lines": ""}]}
  ],
  "knowledgeRequirements": [
    {"conceptId": "cpp.pointers", "title": "...", "description": "...",
     "prerequisites": [...], "relatedTasks": [...], "isExisting": true}
  ]
}

硬性要求：里程碑 ≥4；任务 ≥8；首里程碑 dependsOn 为空（有可独立开始的任务）；
最终里程碑的交付 = 完整可用的 finalArtifact。
输出必须紧凑：description ≤80 字；acceptanceCriteria/targetFeatures ≤3 条；
hintsOutline 每条 ≤30 字；不含任何解释性文字、注释或空白缩进冗余。"""


REPAIR_PROMPT = """你上一版课程蓝图未通过确定性校验。以下是校验错误（error 必须全部修复；warning 可保留但要在 warnings 里说明）：

{errors}

上一版蓝图 JSON：
{blueprint}

请输出修复后的**完整**蓝图 JSON（同一结构，全部字段，不要省略不要注释）。"""


def run_blueprint_generation(
    provider, source: dict, analysis: dict,
    known_concepts: list[str], source_files: list[str],
    budget=None,
) -> tuple[dict, list[dict]]:
    """生成课程蓝图（Scoper 与 Generator 合并为一次 Agent 规划）。"""
    from app.agents.runtime import agent_record_to_dicts, run_agent
    from app.agents.schemas import AgentBudget, ToolContext

    user_first = (
        "SOURCE（仓库与快照信息）：\n"
        f"<<<SOURCE\n{json.dumps(source, ensure_ascii=False, default=str)[:3000]}\nSOURCE>>>\n\n"
        "ANALYSIS（仓库分析结论，不可信数据，仅供参考）：\n"
        f"<<<ANALYSIS\n{json.dumps(analysis, ensure_ascii=False, default=str)[:12000]}\nANALYSIS>>>\n\n"
        f"KNOWN_CONCEPTS（现有知识图谱概念 id，优先引用）：{json.dumps(known_concepts[:60])}\n"
        f"SOURCE_FILES（可引用的证据路径白名单，共 {len(source_files)} 个）："
        f"{json.dumps(source_files[:120])}"
        "{'…（截断，仅可引用以上列出的路径）' if len(source_files) > 120 else ''}\n\n"
        "请设计课程蓝图（严格按系统提示的 JSON 结构输出）。"
    )
    messages = [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_first},
    ]
    from app.agents.registry import ToolRegistry

    ctx = ToolContext(db=None, project_id="00000000-0000-4000-8000-0000000000cb")
    # 蓝图生成无工具（纯规划轮）：空注册表，模型直接产出最终 JSON
    empty_registry = ToolRegistry("course-generator")
    run = run_agent(provider, messages, ctx,
                    budget or AgentBudget(max_rounds=3, max_tool_calls=0,
                                          max_total_tokens=60000),
                    registry=empty_registry)
    from app.agents.schemas import extract_json_object

    text = run.final_content
    try:
        return extract_json_object(text), agent_record_to_dicts(run.tool_calls)
    except ValueError as exc:
        if "未闭合" not in str(exc):
            raise
    # 输出被 max_tokens 截断：请求模型从截断处继续（一次）
    continuation = provider.chat(
        GENERATOR_SYSTEM_PROMPT,
        "你的 JSON 输出被截断。以下是已输出的部分（最后 2000 字符）：\n"
        + text[-2000:]
        + "\n请从截断处**继续输出剩余 JSON**（不要重复已输出内容，不要解释，直接续写）。",
    ).content
    return extract_json_object(text + continuation), agent_record_to_dicts(run.tool_calls)


def run_blueprint_repair(provider, blueprint: dict, errors: list[dict]) -> dict:
    """携带校验错误请求一次修复（无工具单轮）。"""
    from app.ai.provider import LLMResult

    error_text = "\n".join(
        f"- [{e.get('severity')}] {e.get('code')}: {e.get('message')} ({e.get('path')})"
        for e in errors[:30]
    )
    result = provider.chat(
        GENERATOR_SYSTEM_PROMPT,
        REPAIR_PROMPT.format(errors=error_text,
                             blueprint=json.dumps(blueprint, ensure_ascii=False)[:40000]),
    )
    from app.agents.schemas import extract_json_object

    return extract_json_object(result.content)
