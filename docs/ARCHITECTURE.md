# 系统架构（当前实际实现）

> 本文档只描述**已经存在并经过验证**的架构。计划中的能力见 `docs/IMPLEMENTATION_PLAN.md`，产品目标见 `docs/product-design.md`。

## 1. 总体形态

模块化单体：一个 FastAPI 后端 + 一个 React SPA + 一个关系数据库。
六大引擎中已实现：**Project Engine 基础部分**、**Learner Engine 的知识图谱、初始诊断与掌握模型**（understanding + application 两维有真实证据）、**Curriculum Engine 的样板课程规划与阶段验收**、**学习事件信封**、**Tutor Engine**（DeepSeek 真实接入 + Policy Gate + H4 门控 + 介入三模式）、**Visual Interaction Engine**（场景 Schema + 组件注册表 + SceneRenderer + 时间线/变量状态组件 + 版本绑定）。**P2 教学闭环与 P3.1-3.3/3.5 已交付。**

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
  - `service.py`：任务图种子（幂等）、依赖拓扑排序（含环检测）、规则化规划器（知识要求→先修闭包；掌握判定复用 D19 阈值→跳过带原因/学习活动带原因；practice-task 始终保留）、replan 版本递增且历史保留、**`evaluate_task` 阶段验收**（依赖闸门 422 + 确定性 rubric suite-green-v1：套件全绿→done / 否则→needs-fix）。
  - `router.py`：`GET /plans/{projectId}`（无则生成 v1，返回 plan+tasks）、`POST /plans/{projectId}/replan`、**`POST /projects/{id}/tasks/{taskId}/evaluate`**（router 编排：coding 证据→application 维 + task-evaluated 事件）。
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
  - `router.py`：`POST /tutor/turns`（含 requestAnswerLevel）、`GET /tutor/suggestions`（拉取式主动建议）、`GET /tutor/decisions`；决策追加 `tutor-turn` 事件（payload 含 trigger/answerRequested）。决策可携带 **workspace_actions**（Gate 分级 A0/A1/A2 + payload 校验 + H4 联动，D28）。
- **工作台动作执行（前端，P3.4/D28）**：`lib/workspace/executor.ts` 确定性执行链（A0 通知 / A1 布局切换×锁定联防+撤销栈 / A2 确认队列→草稿）；`stores/workspaceStore.ts`（通知/撤销栈/待确认补丁）；`WorkspaceNoticeStrip` 自包含通知条组件（挂载点待并行前端合入，D28）；每动作上报 `workspace-action` 审计事件。
- **领域模块** `app/domains/settings/`（P2.6）：`user_settings`（owner 主键、interventionMode quiet/adaptive/guided，默认 adaptive）；`GET/PATCH /api/v1/settings`。
- **领域模块** `app/domains/executions/`（P4.2b，远程执行沙箱，D32/D33）：
  - `models.py`：`execution_sessions` 表（状态机 queued→preparing→running→completed|failed|timed-out|cancelled、文件快照 JSONB、stdout/stderr/事件流/诊断/测试结果/阶段、沙箱引擎与镜像、排队/开始/结束时间）。
  - `sandbox/`：`SandboxManager` 协议（available/run/cleanup_stale）+ `DockerSandboxManager`——一次性容器：`--network none`、`--read-only` + tmpfs（属主 10001；**工作区执行策略语言专属 D34**：Python `noexec`，C++ `exec` 由服务端 `SandboxSpec.exec_workspace` 声明，客户端不可控）、非 root、cap-drop ALL、no-new-privileges、memory/cpu/pids 限额、stdin gzip-tar 注入、`pw.sandbox` 标签追踪 + 启动清理 + 用后即毁；gVisor/微 VM 未来同协议接入。
  - `languages/`：`LanguageRunner` 协议（validate_files / build_spec / parse_result——语言差异全部在此，公共服务零语言逻辑）+ `PythonRunner`（CPython 3.12 + pytest 镜像；driver 随执行注入 tar；pytest Recorder 插件逐用例 file/line/失败消息；traceback 确定性解析）+ **`CppRunner`（P4.2c/D35：Clang 15 / C++20，多翻译单元真实编译链接[源集策略见 D35]，编译参数服务端固定，clang 行诊断与 GNU ld/lld 链接错误解析为 file:line:col，CMakeLists 存在时 cmake -G Ninja 构建包含入口的目标，测试=独立可执行程序[通过=退出 0 且有输出，空测试不判通过]，编译失败 run 阶段显式 skipped）**。
  - `service.py`：会话编排（通用路径校验拒绝绝对/`..`/反斜杠/盘符/保留名/`__pw`、文件数/总字节/stdin/超时/输出上限）、线程池执行（并发上限）、300ms 节流流式落库、终态写入 + `execution-finished` 服务端事件（幂等）；**信任级固定 practice**（服务端执行 ≠ 正式认证）；沙箱不可用 503。
  - `router.py`：`POST /executions`（202）、`GET /executions/{id}?afterSeq=`（增量事件，SSE 预留）、`POST /executions/{id}/cancel`（幂等）。
  - 镜像：`backend/sandbox/python/Dockerfile` 与 `backend/sandbox/cpp/Dockerfile`（构建命令与隔离参数表见 `backend/sandbox/README.md`）。
- **数据层**：`app/core/db.py` — 同步 engine + `get_db` 请求级会话依赖。开发/单测默认 SQLite；`PW_DATABASE_URL` 切换 PostgreSQL（docker compose 的 PG 16 映射宿主机 **5433**，已通过兼容性验证，见 D16）。
- **迁移**：Alembic，`migrations/env.py` 从应用设置读连接串；全部迁移（projects/files/snapshots、concepts、assessments、mastery、tasks/plans、events、decisions/settings、任务测试列、execution_sessions）在 SQLite 与 PostgreSQL 上均验证可 upgrade/downgrade/重放。
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
| POST | /api/v1/projects/{id}/tasks/{taskId}/evaluate | 阶段验收（套件全绿→done，否则 needs-fix；依赖未完成 422；写 coding 证据与事件） |
| POST | /api/v1/events | 批量上报学习事件（类型白名单，eventId 幂等，≤20 条） |
| GET | /api/v1/events?projectId=&type=&limit= | 学习事件查询（倒序，≤200 条） |
| POST | /api/v1/tutor/turns | 教学回合（含 requestAnswerLevel 的 H4 门控；未配置 503） |
| GET | /api/v1/tutor/suggestions?projectId= | 主动建议（quiet 拒绝/连续失败证据/60s 冷却，拉取式） |
| GET | /api/v1/tutor/decisions?projectId= | 教学决策历史（含 outcome 与 token 用量） |
| GET / PATCH | /api/v1/settings | 用户 AI 偏好（interventionMode：quiet/adaptive/guided） |
| POST | /api/v1/executions | 创建远程执行（202 排队；Python run/test；沙箱不可用 503；校验失败 422） |
| GET | /api/v1/executions/{id}?afterSeq= | 执行会话查询（状态/输出/诊断/测试结果/phases；afterSeq 增量事件轮询） |
| POST | /api/v1/executions/{id}/cancel | 取消执行（幂等；终态返回当前状态） |
| （前端上报） | workspace-action 事件 | 工作台动作执行结果审计（executed/rejected/needs-confirmation/confirmed/undone） |

OpenAPI 文档：启动后访问 `http://localhost:8000/docs`。

## 3. 前端（frontend/）

- **技术**：React 19 + TypeScript（strict）+ Vite 8 + Tailwind CSS v4（`@theme` 令牌化深色主题）+ Zustand（persist）+ zod。
- **执行层（`src/lib/execution/`，P4.2a/D30 + P4.2b/D32 + P4.2c/D34/D35）**：语言无关的执行契约层——`types.ts`（ExecutionRequest[含 stdin]/Result/Diagnostic/TestFileOutcome，信任级 practice/formal）；`LanguageProfile.ts`（TS/Python/C++ 注册表：TS→browser-worker，**Python→remote-pytest（P4.2b）**，**C++→remote-cpp（P4.2c 真实支持）**）；`ExecutionBackend.ts`（后端策略接口）；`registry.ts`（路由：请求 → 可处理后端，不支持则 UnsupportedExecutionError）；`backends/browserWorker.ts`（TypeScript 浏览器 Worker：单文件转译 / 多文件 esbuild-wasm 打包，practice）；**`backends/remoteShared.ts`（P4.2c 共享远程传输层：创建会话 → 400ms 轮询增量事件流式回传 → 终态映射[build/runtime/test 诊断分类] → 取消；503/超时明确报错不模拟成功；`createRemoteBackend` 工厂）**；remotePython/remoteCpp 为工厂薄封装。扩展新语言 = 注册 Profile + 一行工厂调用，零修改 Curriculum/Learner/TeachingScene。
- **远程运行终端胶水**：`src/lib/runner/runRemote.ts`——`runRemoteInTerminal`/`runRemoteTestsInTerminal`（语言自动检测、状态行、流式输出、trace 绑定含 executionId/backend、stdin 取自终端面板、构建诊断带 file:line:col 呈现、错误显式呈现）；`canRunPath`/`isAnyTestPath`/`isRemoteExecutable`（按 Profile 声明自动覆盖新语言；test_*.py / *_test.cpp 识别为测试）；IdePage 运行按钮按语言分发（TS→浏览器 Worker，Python/C++→远程沙箱），任务测试与测试面板按语言路由；TaskPanel 验收提交携带 source(browser/remote)+executionId 溯源；终端面板含 stdin 输入与远程执行"停止"按钮；**Mentor 的 recentRunResult = 最近一次运行的真实终端摘要（编译诊断/traceback 语言无关，AI 依真实错误辅导）**。
- **多文件模块执行**：`src/lib/runner/bundler.ts`——esbuild-wasm（懒加载 ~14MB WASM，部署于 public/esbuild.wasm）+ 虚拟文件系统插件；路径规范化（禁 `..` 越界）+ 扩展名补全（.ts/.tsx/.js/.jsx 等）+ 外部 npm 包明确拒绝；编译时间记录；`hasRelativeImports()` 检测（单文件 export 不触发打包路径）。`runFile.ts` 无 VFS 时始终单文件模式（兼容旧调用）。
- **路由**：`/`（仪表盘）、`/concepts`（知识图谱 + 掌握徽标）、`/projects/:id`（详情 + 诊断 + 学习路线 + **里程碑任务卡：状态徽标（含"需修正"）与「测试验收」按钮**——浏览器跑套件→提交→状态刷新）、`/projects/:id/assessment`、`/projects/:id/ide`（终端/测试/事件页签 + 调试/实验画布 + AI Mentor）。
- **可视化引擎**（`src/viz/`，P3.1-P3.3，D24-D26）：`sceneSchema.ts`（TeachingScene zod：sourceType 三分类 runtime/static/conceptual + 来源标签；dataBinding；components；allowedInteractions）；`registry.ts`（L1 组件注册表，重复注册抛错）；`SceneRenderer.tsx`（schema 校验 + 查表渲染 + 多组件纵向组合 + **trace 头部（运行时间/指纹缩写）与过期横幅**）；组件：`consoleTimeline.tsx` 与 `variablesState.tsx`（observe() 声明式观察，D25）；场景：单组件 ×2 + L2 组合 debug-panel。
- **版本绑定（§14.3，D26）**：`lib/fingerprint.ts`（执行内容 SHA-256 指纹，无 subtle 时 FNV-1a 降级）；runStore `trace`（traceId/指纹/路径/时间）；运行时写入 trace，code-run/tests-run 学习事件携带 traceId；IdePage 持续比对草稿指纹与单文件运行指纹，不一致时画布显示"数据已过期"横幅（旧执行数据不冒充当前）。服务器 codeVersion（已保存状态）与执行指纹（草稿）两层语义并存。
- **学习事件（前端）**：`lib/eventTracker.ts` 批量缓冲（满 5 条或 30s flush，失败保留队列重试，队列上限 50）上报 code-run/tests-run；服务端事件（保存/诊断/规划）由后端产生；IDE 事件页签实时展示（类型徽标 + 摘要 + 序号，可刷新）。
- **AI Mentor 面板**：真实教学回合（发送问题 → 回复气泡带 intent/H 级徽标、目标概念与 token 用量，降级决策带标记）；**"答案级帮助（H4）"显式勾选**（勾选才可能获得 H4，事件记录 answerRequested）；历史加载；503 显示"AI 未配置"配置指引；失败错误可见；Motion Primitives 消息进入；服务端真实 propose-patch 含代码且目标已打开时，可用 Monaco DiffEditor 只读比较，不自动应用。
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
  - DockviewReact 8.4.1（MIT）提供自由停靠：文件/任务/历史/编辑器/画布/导师/终端/测试/学习事件 9 个独立面板，拖动拆分/标签合并、缩放、页内悬浮、显隐、停靠组专注、恢复预设；四模式与每个项目独立 localStorage 保存。`WorkspaceLayoutContext` 提供菜单/命令/文件打开/运行入口共用控制器，动作读取 ideUiStore 实时锁定；锁定阻止拖动/缩放及布局改变。`lib/dockLayout.ts` 校验存储面板白名单/树结构并剥离业务参数，存储错误明示；稳定 portal 宿主避免模式切换/移位/隐藏卸载 Monaco 和导师输入。屏幕外渲染内容以 overflow-clip 隔离，避免焦点滚动顶栏；未接入 Enterprise 键盘模块；
  - Monaco Editor 本地打包（无 CDN，monaco 0.5x 原生 URL-worker 由 Vite 处理），按扩展名推断语言；
  - 文件树来自服务器（`project_files`），支持新建/重命名/删除；编辑器保存 = PUT 到服务器（Ctrl+S），并有 **2.5s 防抖自动保存**（停止输入后触发，失败错误可见，可按项目关闭）；“历史”页签展示当前文件的快照（时间/大小/哈希缩写、内容预览截断 5000 字符、恢复前确认）；项目详情页元信息显示当前 codeVersion；运行 = 浏览器 Worker 沙箱（Ctrl+Enter，运行草稿内容、不要求先保存；测试文件时按钮语义切换为「▶ 测试」并运行整个套件）；
  - 底部 xterm + FitAddon 展示真实浏览器 Worker 输出（远程 Shell 明确未连接 / P4）；测试套件结果、学习事件和 AI Mentor 已接真实管线；调试/实验画布渲染真实执行时间线/变量与指纹；架构图仍为明确未实现的占位。
- **前端组件层**：shadcn 原组件源码位于 `components/ui/upstream/`，`Button/Card/PanelTabs` 提供业务兼容包装；Radix/cmdk 负责通用交互；统一 `index.css` token。AppShell 提供真实页面导航；路由、终端、Diff、知识图懒加载。AppearanceProvider/MotionConfig/useUiReducedMotion 结合用户与系统偏好管理动效；Magic UI BlurFade 仅用于项目卡片。
- **界面设置**：`appearanceStore` 保存经过 zod 校验的版本化浏览器外观，与服务器 AI 偏好、项目 Dockview 布局分离；`lib/appearance.ts` 映射共享 CSS token、字号/密度与可读强调色，`AppearanceProvider` 在 layout effect 应用。SettingsButton 在 AppShell/IDE 内挂载 Radix SettingsDialog，IDE 内自然获取 WorkspaceLayoutContext，显隐/重置服从实时锁定。Monaco 定义稳定主题并订阅配色；Editor/Diff 选项和 xterm 实例 options 实时更新、不更换模型或丢失缓冲。设置打开期间暂停文件保存/运行全局组合键；字体使用本机安装字体与回退，不下载字体。
- **页面滚动边界**：非 IDE 的 AppShell 使用固定 100dvh；侧栏与顶栏不随正文滚动，`app-page-content` 占剩余高度，以有名称、可键盘聚焦的 region 承载 overflow-y-auto。短内容不制造整页溢出，长内容/手机可滚动正文；外层 overflow-clip 避免焦点带动整页，保留其他工作区和弹窗各自滚动。
- **知识图**：ConceptsPage 的列表/图切换；ConceptGraph 用 React Flow 和按需 ELK layered 布局真实概念/先修关系，掌握证据无则明确标注；Controls/MiniMap、拖动、缩放、节点详情定位；不编辑知识库。知识图与 runtime Visual Engine 分工，后者仍使用已有 SceneRenderer。
- **快照与单文件转译补充**：历史 hook 随已保存 updatedAt 刷新，Monaco Diff 只读；TS 编译为 CommonJS 后包进局部 exports 的 async 函数并 await，支持种子 export 与完成顺序，不提供跨文件模块解析。
- **测试**：`src/__tests__/` — 契约、API、状态与权限、文件/快照 hook、Worker 真实脚本执行、页面与公共控件交互；本轮 32 个文件 / 191 个用例。组件/许可证/性能与浏览器验收记录见 `UI_COMPONENTS.md`。

## 4. 关键横切约定

- **API 契约**：JSON camelCase；时间 ISO 8601 UTC；错误结构 `{"detail": ...}`。
- **配置**：后端 `PW_` 前缀环境变量（`.env`），默认 SQLite，`PW_DATABASE_URL` 切换 PostgreSQL。
- **未实现标注**：前端统一用 `PlaceholderState` 组件标明功能名与交付阶段。
