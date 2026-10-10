# 系统架构（当前实际实现）

> 本文档只描述**已经存在并经过验证**的架构。计划中的能力见 `docs/IMPLEMENTATION_PLAN.md`，产品目标见 `docs/product-design.md`。

## 1. 总体形态

模块化单体：一个 FastAPI 后端 + 一个 React SPA + 一个关系数据库。
六大引擎中已实现：**Project Engine 基础部分**、**Learner Engine 的知识图谱、初始诊断与掌握模型**、**Curriculum Engine 的样板课程规划**、**学习事件信封**、**Tutor Engine**（DeepSeek 真实接入 + Policy Gate + H4 门控 + 介入三模式）、**Visual Interaction Engine 地基**（场景 Schema + 组件注册表 + SceneRenderer + console-timeline L1 组件）。**P2 教学闭环全部交付，P3 已启动。**

```
┌─────────────────────────┐      /api/v1 (JSON)       ┌──────────────────────────┐
│ React SPA (Vite, 5173)  │ ────────────────────────▶ │ FastAPI (uvicorn, 8000)  │
│ Monaco / Zustand / zod  │ ◀──────────────────────── │ domains/projects         │
└─────────────────────────┘   开发期 Vite 代理 /api    └───────────┬──────────────┘
                                                                    │ SQLAlchemy 2.0 (同步)
                                                                    ▼
                                                          SQLite（dev）/ PostgreSQL（目标）
```

## 2. 后端（backend/）

- **入口**：`app/main.py` — 应用工厂 `create_app()`，CORS、lifespan（启动时按 `PW_AUTO_MIGRATE` 执行 Alembic 升级）。
- **路由聚合**：`app/api.py` — `/api/v1` 前缀，挂载各领域 router 与 `/health`。
- **领域模块** `app/domains/projects/`：
  - `models.py`：`projects` 表（UUID 主键、spec 数组字段为 JSON/JSONB、spec_version、owner_id 预留）、`project_files` 表（project_id 外键 + path 唯一约束、content TEXT 内联，上限 1MB/2000 文件）、`code_snapshots` 表（覆盖保存前的旧内容 + sha256，每文件保留最近 50 份）。
  - `schemas.py` / `file_schemas.py`：Pydantic v2 契约，`to_camel` 别名（对外 camelCase），枚举 mode/status/complexity/milestone-status；快照与 codeVersion 契约。
  - `service.py`：项目确定性业务逻辑（CRUD、spec 字段变更提升 spec_version、UUID 解析、创建时种子初始脚手架文件——README.md、src/main.ts、src/main.test.ts、删除时级联清理文件）。
  - `file_service.py`：路径安全校验、文件 CRUD 与重命名（历史快照跟随）、删除（连带清理历史）、快照写入（同内容跳过 + 上限裁剪，显式 flush 适配 autoflush=False）、恢复（当前内容先入历史）、codeVersion 计算（全部文件按路径排序后整体 SHA-256，实时计算不落库）。
  - `router.py` / `file_router.py`：REST 端点，领域异常 → HTTP 404/409/422。
- **领域模块** `app/domains/concepts/`（P2.1，Learner Engine 的知识图谱部分）：
  - `models.py`：`knowledge_concepts` 表（字符串主键如 `js.closures`、domain 索引、先修/目标/评估/示例 JSONB、version）。
  - `seed.py`：17 个确定性种子概念（样板课程知识图：JS 10 / TS 2 / 浏览器 2 / 工程 3）。
  - `service.py`：`validate_graph`（DFS 检测环/悬空/自引用）、列表（domain 过滤）与详情查询、`ensure_seed_concepts`（空表幂等写入，启动 lifespan 调用）。
  - `router.py`：只读端点，见下表。
- **领域模块** `app/domains/assessments/`（P2.2，初始能力诊断）：
  - `models.py`：`assessment_sessions`（项目 FK、状态、题目快照 + 题库版本、结果 JSON）与 `assessment_answers`（逐题作答与判定）。
  - `question_bank.py`：15 道确定性单选预测题（覆盖种子概念，难度 1-3，带版本）。
  - `service.py`：选题（stack→域映射、概念拓扑深度+难度排序、每概念一题、≤8 题）、确定性判定、概念三档初判（likely-mastered/uncertain/likely-gap）。
  - `router.py`：start/submit/详情/项目历史端点。
- **领域模块** `app/domains/learner/`（P2.3，学习者掌握模型）：
  - `models.py`：`learner_mastery`（owner+concept 唯一、四维 dimensions JSONB——只写有证据的维度、model_version）与 `learning_evidence`（逐条证据：类型/结果/来源/rubric 版本）。
  - `service.py`：确定性管线 `record_evidence`（校验→估计=通过率→置信度=min(0.9, 0.3+0.2n)），证据类型→维度映射表（prediction→understanding 等，设计 6.3 词表）；诊断提交在 assessments **router 层编排**调用。
  - `router.py`：`GET /mastery`（当前 owner）。
- **领域模块** `app/domains/curriculum/`（P2.4，Curriculum Engine 的样板课程规划）：
  - `models.py`：`project_tasks`（样板任务图：依赖/知识要求/交付物/effort）与 `learning_plans`（版本化活动/跳过/原因 JSON）。
  - `templates.py`：样板课程六任务模板（附录 B 映射，确定性）。
  - `service.py`：任务图种子（幂等）、依赖拓扑排序（含环检测）、规则化规划器（知识要求→先修闭包；掌握判定复用 D19 阈值→跳过带原因/学习活动带原因；practice-task 始终保留）、replan 版本递增且历史保留。
  - `router.py`：`GET /plans/{projectId}`（无则生成 v1，返回 plan+tasks）、`POST /plans/{projectId}/replan`。
- **领域模块** `app/domains/events/`（P2.7，学习事件信封）：
  - `models.py`：`learning_events` 表（event_id 唯一幂等键、aggregate_id+sequence 复合索引、payload JSONB ≤4KB、类型白名单：file-saved/plan-generated/plan-replanned/assessment-submitted/code-run/tests-run）。
  - `service.py`：`append_event`（白名单/payload 校验、eventId 幂等跳过、aggregate 序列分配）、`server_event_id`（uuid5 确定性 id，重放自动去重）、按项目/类型查询。
  - `router.py`：`POST /api/v1/events` 批量上报（≤20 条）、`GET /api/v1/events` 查询。服务端事件由 file/curriculum/assessments 各 router 在编排层追加（D21）。
- **AI 模块** `app/ai/provider.py`（P2.5，可插拔 LLM Adapter，D22）：
  - `DeepSeekProvider`：OpenAI 兼容 chat/completions（`PW_DEEPSEEK_API_KEY` 等 .env 配置，Key 不入库；json_object 强制结构化输出；Token 用量记录；认证/限流/网络错误分类）；
  - `MockProvider`（仅测试）与 `disabled`（默认，503 明确降级不伪造）；`transport` 注入口供 MockTransport 测试。
- **领域模块** `app/domains/tutor/`（P2.5/P2.6，Tutor Engine）：
  - `models.py`：`teaching_decisions`（问题、trigger=user/auto、提案字段、Policy Gate outcome 与原因、policy_version、token/model）。
  - `service.py`：确定性上下文组装（只读各域 models：路线活动/mastery/最近事件/任务/规格）、防注入提示词（CONTEXT 分隔）、`policy_gate`（intent 白名单/hintLevel 0-4/**H4 须 requestAnswerLevel**/message 长度/概念数校验，不合规降级为安全动作）、`get_suggestion`（介入模式裁决：quiet 拒绝；连续 ≥3 次运行失败证据；60s 冷却）。
  - `router.py`：`POST /tutor/turns`（含 requestAnswerLevel）、`GET /tutor/suggestions`（拉取式主动建议）、`GET /tutor/decisions`；决策追加 `tutor-turn` 事件（payload 含 trigger/answerRequested）。
- **领域模块** `app/domains/settings/`（P2.6）：`user_settings`（owner 主键、interventionMode quiet/adaptive/guided，默认 adaptive）；`GET/PATCH /api/v1/settings`。
- **数据层**：`app/core/db.py` — 同步 engine + `get_db` 请求级会话依赖。开发/单测默认 SQLite；`PW_DATABASE_URL` 切换 PostgreSQL（docker compose 的 PG 16 映射宿主机 **5433**，已通过兼容性验证，见 D16）。
- **迁移**：Alembic，`migrations/env.py` 从应用设置读连接串；三个迁移（projects、project_files、code_snapshots）在 SQLite 与 PostgreSQL 上均验证可 upgrade/downgrade/重放。
- **测试**：`tests/` — 临时 SQLite + 依赖覆盖（111 个用例：项目 14 + 文件 19 + 快照 10 + 知识图 10 + 诊断 12 + 学习者模型 5 + 课程规划 5 + 事件 10 + AI Provider 8 + Tutor 11 + 介入模式/H4/建议 7，含 H4 未请求降级/请求放行并标记、quiet 不调 LLM、连续失败阈值、冷却）；`tests/test_postgres_compat.py` 为 PG 兼容套件（默认 skip，`PW_TEST_DATABASE_URL` 触发，4 个用例）。测试环境强制 AI disabled（不读 .env 真实 Key）。

### 已实现 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/health | 健康检查 |
| POST | /api/v1/projects | 创建项目（201，自动种子 README.md + src/main.ts） |
| GET | /api/v1/projects | 列表（按创建时间倒序） |
| GET | /api/v1/projects/{id} | 详情 |
| PATCH | /api/v1/projects/{id} | 部分更新（spec 字段变更提升版本） |
| DELETE | /api/v1/projects/{id} | 删除（204，级联删除文件） |
| GET | /api/v1/projects/{id}/files | 文件列表（扁平路径，含 size/updatedAt） |
| GET | /api/v1/projects/{id}/files/content?path= | 读取文件内容 |
| PUT | /api/v1/projects/{id}/files | 创建/整体替换文件（201，upsert；覆盖时旧内容入快照） |
| PATCH | /api/v1/projects/{id}/files | 重命名/移动（目标存在时 409，历史快照跟随） |
| DELETE | /api/v1/projects/{id}/files?path= | 删除文件（204，连带清理其快照） |
| GET | /api/v1/projects/{id}/code-version | 项目当前代码指纹（sha256 + 文件数，实时计算） |
| GET | /api/v1/projects/{id}/files/history?path= | 快照历史列表（倒序，展示哈希缩写） |
| GET | /api/v1/projects/{id}/files/history/{snapshotId} | 读取快照内容 |
| POST | /api/v1/projects/{id}/files/history/{snapshotId}/restore | 恢复快照（当前内容先入历史） |
| GET | /api/v1/concepts?domain= | 知识概念列表（可按 domain 过滤，返回全部域） |
| GET | /api/v1/concepts/{conceptId} | 概念详情（先修/目标/评估方式） |
| POST | /api/v1/assessments/start | 开始诊断（按项目 stack 选题，不下发答案） |
| POST | /api/v1/assessments/{id}/submit | 提交作答（确定性判定 + 概念三档初判；重复 409） |
| GET | /api/v1/assessments/{id} | 诊断会话详情（含结果） |
| GET | /api/v1/projects/{id}/assessments | 项目诊断历史 |
| GET | /api/v1/mastery | 当前用户的概念掌握估计（四维中仅有证据的维度） |
| GET | /api/v1/plans/{projectId} | 当前学习路线（无则生成 v1；含任务图与活动/跳过原因） |
| POST | /api/v1/plans/{projectId}/replan | 重新规划（版本递增，历史保留） |
| POST | /api/v1/events | 批量上报学习事件（类型白名单，eventId 幂等，≤20 条） |
| GET | /api/v1/events?projectId=&type=&limit= | 学习事件查询（倒序，≤200 条） |
| POST | /api/v1/tutor/turns | 教学回合（含 requestAnswerLevel 的 H4 门控；未配置 503） |
| GET | /api/v1/tutor/suggestions?projectId= | 主动建议（quiet 拒绝/连续失败证据/60s 冷却，拉取式） |
| GET | /api/v1/tutor/decisions?projectId= | 教学决策历史（含 outcome 与 token 用量） |
| GET / PATCH | /api/v1/settings | 用户 AI 偏好（interventionMode：quiet/adaptive/guided） |

OpenAPI 文档：启动后访问 `http://localhost:8000/docs`。

## 3. 前端（frontend/）

- **技术**：React 19 + TypeScript（strict）+ Vite 8 + Tailwind CSS v4（`@theme` 令牌化深色主题）+ Zustand（persist）+ zod。
- **路由**：`/`（仪表盘：项目列表 + 创建表单 + 知识图谱入口）、`/concepts`（知识图谱浏览页：域分组、先修/目标/评估方式展开、理解维掌握徽标叠加）、`/projects/:id`（详情 + 能力诊断卡片 + **学习路线卡片**：活动与原因、跳过折叠区、版本与重新规划 + 里程碑任务图）、`/projects/:id/assessment`（诊断：逐题作答 → 概念三档结果 + 逐题回顾）、`/projects/:id/ide`（教学 IDE，底部三页签真实：终端/测试/学习事件；"调试"画布 = L2 组合场景 [时间线+变量状态]，"实验"画布 = 变量状态场景）。
- **可视化引擎**（`src/viz/`，P3.1-P3.3，D24-D26）：`sceneSchema.ts`（TeachingScene zod：sourceType 三分类 runtime/static/conceptual + 来源标签；dataBinding；components；allowedInteractions）；`registry.ts`（L1 组件注册表，重复注册抛错）；`SceneRenderer.tsx`（schema 校验 + 查表渲染 + 多组件纵向组合 + **trace 头部（运行时间/指纹缩写）与过期横幅**）；组件：`consoleTimeline.tsx` 与 `variablesState.tsx`（observe() 声明式观察，D25）；场景：单组件 ×2 + L2 组合 debug-panel。
- **版本绑定（§14.3，D26）**：`lib/fingerprint.ts`（执行内容 SHA-256 指纹，无 subtle 时 FNV-1a 降级）；runStore `trace`（traceId/指纹/路径/时间）；运行时写入 trace，code-run/tests-run 学习事件携带 traceId；IdePage 持续比对草稿指纹与单文件运行指纹，不一致时画布显示"数据已过期"横幅（旧执行数据不冒充当前）。服务器 codeVersion（已保存状态）与执行指纹（草稿）两层语义并存。
- **学习事件（前端）**：`lib/eventTracker.ts` 批量缓冲（满 5 条或 30s flush，失败保留队列重试，队列上限 50）上报 code-run/tests-run；服务端事件（保存/诊断/规划）由后端产生；IDE 事件页签实时展示（类型徽标 + 摘要 + 序号，可刷新）。
- **AI Mentor 面板**：真实教学回合（发送问题 → 回复气泡带 intent/H 级徽标、目标概念与 token 用量，降级决策带标记）；**"答案级帮助（H4）"显式勾选**（勾选才可能获得 H4，事件记录 answerRequested）；历史加载；503 显示"AI 未配置"配置指引；失败错误可见。
- **AI 介入**：IDE 顶栏三模式切换（安静/自适应/引导，PATCH 持久化，失败回滚）；运行/测试失败后自动拉取 suggestions——满足条件时在编辑区顶部显示**非阻塞建议条**（可忽略），Quiet 模式后端直接返回 null。
- **API 层**：`src/api/client.ts` 统一 fetch 封装（`ApiError` 错误映射，网络失败有可读提示）；`src/api/projects.ts`、`src/api/files.ts` 所有响应过 zod 校验。
- **类型契约**：`src/types/`（project.ts、file.ts，barrel 导出）与后端 Pydantic 镜像。
- **状态**：`ideUiStore`（工作模式 + 布局锁定，锁定时 setMode 拒绝一切切换）；`runStore`（终端输出条目、运行中状态、底部面板页签，不持久化，上限 500 条）；`testStore`（测试面板结果）；文件/编辑器状态由 `src/hooks/useProjectFiles.ts` 管理（文件树、打开文件、脏状态、手动/自动保存、新建/重命名/删除、切换文件的未保存确认、reloadCurrent）；`src/hooks/useFileHistory.ts` 管理当前文件快照历史（列表/预览/恢复）。
- **浏览器运行器**（`src/lib/runner/`，P1.4/P1.5）：
  - `workerSource.ts` 生成 Worker 脚本文本：普通模式劫持 `self.console` 流式 postMessage 输出，用户代码包进 async IIFE（支持顶层 await）；测试模式（`buildTestSource`）额外注入微型测试运行时（`describe/it/test` + `expect`：toBe/toEqual/toBeTruthy/toBeFalsy/toContain/toThrow 及 `.not`，深比较），逐用例回传 `test-result`，结束发 `test-summary` + `done`；
  - `runJavaScript.ts` 以 Blob URL + module Worker 执行（无 DOM/应用状态访问），5 秒超时强制 terminate，结束时必定 terminate；`runTests` 封装收集用例与汇总；
  - `runFile.ts` 按扩展名分发：`.js/.mjs/.cjs` 直跑，`.ts/.mts/.cts` 用真实 TypeScript 编译器（`ts-compiler` 别名 = npm:typescript@5.9，懒加载 chunk）单文件转译后执行（不做类型检查，界面标注），其他类型明确拒绝；`*.test.<js|ts>` 识别为测试文件；
  - `runToTerminal.ts` 把单文件运行粘合到终端面板；`runTestSuite.ts` 拉取项目全部测试文件（当前打开文件的未保存草稿优先）逐个执行并聚合到测试面板（文件级错误如实记 error）。
- **测试面板**（`runStore`/`testStore`）：按文件分组展示用例通过/失败与失败断言消息、合计与进度、运行中状态、页签自动切换、拒绝并发。测试结果当前仅内存展示（持久化属于学习证据 P2.7）。
- **教学 IDE**（`src/pages/IdePage.tsx`）：
  - CSS Grid 三列布局，四种工作模式（编程/调试/实验/架构）切换面板组合与列宽；
  - Monaco Editor 本地打包（无 CDN，monaco 0.5x 原生 URL-worker 由 Vite 处理），按扩展名推断语言；
  - 文件树来自服务器（`project_files`），支持新建/重命名/删除；编辑器保存 = PUT 到服务器（Ctrl+S），并有 **2.5s 防抖自动保存**（停止输入后触发，失败错误可见，可按项目关闭）；“历史”页签展示当前文件的快照（时间/大小/哈希缩写、内容预览截断 5000 字符、恢复前确认）；项目详情页元信息显示当前 codeVersion；运行 = 浏览器 Worker 沙箱（Ctrl+Enter，运行草稿内容、不要求先保存；测试文件时按钮语义切换为「▶ 测试」并运行整个套件）；
  - 底部终端/测试面板为真实功能（终端：运行输出流；测试：套件结果）；学习事件页签与 AI Mentor、执行/教学/架构画布为**标注未实现阶段**的占位。
- **测试**：`src/__tests__/` — 契约、API 客户端、IDE 状态、文件 hook（含自动保存防抖/关闭）、文件历史 hook、运行器（node:vm 真实执行 Worker 脚本文本、测试运行时、FakeWorker 协议/超时、套件聚合）、仪表盘组件（98 个用例）。

## 4. 关键横切约定

- **API 契约**：JSON camelCase；时间 ISO 8601 UTC；错误结构 `{"detail": ...}`。
- **配置**：后端 `PW_` 前缀环境变量（`.env`），默认 SQLite，`PW_DATABASE_URL` 切换 PostgreSQL。
- **未实现标注**：前端统一用 `PlaceholderState` 组件标明功能名与交付阶段。
