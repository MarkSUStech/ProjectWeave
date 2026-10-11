"""课程蓝图契约（P7.1，D42）：严格 Pydantic Schema + 确定性验证结果。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domains.projects.schemas import APIModel


# ---------------------------------------------------------------- 蓝图 Schema


class SourceEvidence(APIModel):
    """结论的仓库来源依据（可回溯到快照路径）。"""

    path: str
    note: str = ""
    lines: str = ""  # 如 "10-42"


class Claim(APIModel):
    """带证据分级的事实陈述（confirmed / inferred / unknown）。"""

    statement: str
    kind: str = Field(pattern="^(confirmed|inferred|unknown)$")
    sources: list[SourceEvidence] = Field(default_factory=list)


class RepositoryAnalysis(APIModel):
    """Repository Analyzer Agent 的结构化产物。"""

    summary: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    modules: list[Claim] = Field(default_factory=list)
    behaviors: list[Claim] = Field(default_factory=list)  # 对外可观察功能
    tests_summary: str = ""
    dependencies: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)


class MilestoneSpec(APIModel):
    milestone_id: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    target_features: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(min_length=1)  # 每里程碑至少一个交付
    depends_on: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(min_length=1)  # 核心里程碑需验收
    estimated_effort_band: str = Field(default="medium", pattern="^(small|medium|large)$")


class TaskSpec(APIModel):
    task_id: str = Field(min_length=1, max_length=60)
    milestone_id: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    required_concepts: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)
    expected_files: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(min_length=1)  # 每任务至少一个交付
    acceptance_criteria: list[str] = Field(default_factory=list)
    test_strategy: str = ""
    hints_outline: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class KnowledgeRequirement(APIModel):
    concept_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    related_tasks: list[str] = Field(default_factory=list)
    # true = 现有知识图谱已有；false = 候选概念（发布前需人工审核入图）
    is_existing: bool = False


class ProjectInfo(APIModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    source_url: str
    commit_sha: str
    license: dict = Field(default_factory=dict)
    tech_stack: list[str] = Field(default_factory=list)
    final_artifact: str = ""  # 预期最终成品
    target_level: str = Field(default="beginner", pattern="^(beginner|intermediate|advanced)$")
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    goals: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    runtime_requirements: list[str] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)


class CourseBlueprint(APIModel):
    project: ProjectInfo
    milestones: list[MilestoneSpec] = Field(min_length=1)
    tasks: list[TaskSpec] = Field(min_length=1)
    knowledge_requirements: list[KnowledgeRequirement] = Field(default_factory=list)
    blueprint_version: int = 1
    generator_version: str = "course-architect-v1"
    generation_status: str = Field(default="draft", pattern="^(draft|validated|published)$")
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


# ---------------------------------------------------------------- 验证结果


class ValidationIssue(APIModel):
    code: str
    message: str
    # error = 结构不合法（阻断发布）；warning = 需人工审阅（不阻断）
    severity: str = Field(default="error", pattern="^(error|warning)$")
    path: str = ""


class ValidationResult(APIModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    checked_at: datetime


# ---------------------------------------------------------------- API 契约


class GenerationCreate(APIModel):
    repository_url: str = Field(min_length=10, max_length=500)


class GenerationCreated(APIModel):
    id: uuid.UUID
    status: str
    progress: int = 0


class GenerationRead(APIModel):
    id: uuid.UUID
    source_url: str
    status: str
    stage: str | None = None
    progress: int = 0
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    repo_owner: str | None = None
    repo_name: str | None = None
    commit_sha: str | None = None
    default_branch: str | None = None
    license: dict | None = None
    stats: dict | None = None
    repair_rounds: int = 0
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class GenerationAnalysisRead(APIModel):
    id: uuid.UUID
    status: str
    analysis: RepositoryAnalysis | None = None
    tool_calls: list[dict] = Field(default_factory=list)


class GenerationBlueprintRead(APIModel):
    id: uuid.UUID
    status: str
    blueprint: CourseBlueprint | None = None
    validation: ValidationResult | None = None


class GenerationPublishRead(APIModel):
    id: uuid.UUID
    status: str
    published_at: datetime | None = None
    task_count: int = 0
    milestone_count: int = 0
