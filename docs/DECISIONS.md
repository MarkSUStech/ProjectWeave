# 技术决策记录（ADR）

格式：背景 → 决策 → 理由 → 影响。按时间倒序追加。

---

## D26 · 运行数据版本绑定：客户端执行指纹 + 过期横幅（§14.3 MVP）

**背景**：可视化数据必须与产生它的代码版本绑定（设计 §14.3）；代码变更后画布不得把旧执行数据冒充当前执行。服务器 codeVersion 描述"已保存状态"，但浏览器运行执行的是**编辑器草稿**——两者语义不同。

**决策**：
- **两层指纹**：服务器 codeVersion（已保存状态，详情页显示，已有）+ **客户端执行指纹**（浏览器运行时对被执行内容计算 `SHA-256(path\0content)`，多文件 \n 连接；无 crypto.subtle 环境降级 FNV-1a 仅供测试）；
- 每次运行（code-run/tests-run）生成 **traceId**（uuid），与执行指纹、路径、时间一起写入 runStore 的 `trace`；**code-run/tests-run 学习事件携带 traceId**（事件与运行可关联）；
- **过期判定**：IdePage 对当前草稿持续计算指纹，与最近一次单文件运行 trace 的指纹不一致 → 画布（SceneRenderer）顶部显示"数据已过期：代码在运行后已修改，以下显示的是旧执行数据"（§14.3 原则：允许查看但不冒充当前）；测试套件 trace（多文件联合指纹，runPath=null）不参与单文件比对，其消费方是测试面板（非场景画布）；
- SceneRenderer 头部显示运行时间 + 指纹缩写（悬停见完整 traceId/指纹）。

**影响**：trace 目前存于前端（易失）；远程沙箱接入后 trace 落库并与服务器 codeVersion 双向关联（§12.2 execution_traces 表已规划）；Tutor 可引用 traceId 定位"哪次运行"的上下文。

---

## D25 · 变量状态采集：声明式 observe() API 而非自动插桩

**背景**：FR-07 要求变量状态类可视化端到端。真实调用栈/变量跟踪需要 debugger 协议或 AST 插桩（工程重）；浏览器 Worker 中无 DAP。

**决策**：Worker 注入**声明式观察 API** `observe(name, value)`——学生在代码中主动上报关心的变量，值复用运行器序列化（对象 JSON/循环引用等）后作为 `observed` 消息流式回传；runStore 维护观察序列（上限 200）。L1 组件 `variables-state` 按变量名分组渲染当前值 + 变化次数 + 可展开的历史序列（本地交互零 LLM）。
- 新增场景：`runtime.variables-state.v1`（实验模式）；**L2 组合场景** `runtime.debug-panel.v1`（调试模式 = 时间线 + 变量状态纵向平分画布，共享同一运行数据，§9.1 组合协议）；SceneRenderer 支持多组件布局。

**理由**：观察点由学习者选择本身就是教学行为（对应附录 B M2"解释状态与 DOM 的区别"）；数据是真实执行采集（runtime 标签），不伪造调试器能力。调用栈组件待远程调试器接入再做（不假装）。

**影响**：P3.3 的 codeVersion 绑定将同时覆盖 entries 与 observations；自动插桩（每语句快照）可作为后续增强。

---

## D24 · Visual Engine 地基：结构化场景 + 注册表渲染，禁止 LLM 生成 React 代码

**背景**：P3.1 落地 Visual Interaction Engine（设计 §9）。核心红线：不让 LLM 每次生成新的可视化代码；数据来源必须可信标注。

**决策**：
- **TeachingScene Schema**（zod，§9.5 字段子集）：sceneId/templateId（版本化）/objectiveId/sourceType（runtime/static/conceptual）/dataBinding/components/allowedInteractions；来源三分类与 UI 标签（真实执行/静态结构/概念模拟）由 schema 强制；
- **组件注册表**（§9.3）：L1 组件登记 componentId/version/supportedConcepts/dataSources/renderCapabilities/accessibilityDescription/View；重复注册抛错；**SceneRenderer 只渲染已注册组件——未注册或 schema 不合法显式错误面板**，不静默伪装；
- **首个 L1 组件 `console-timeline`**：渲染最近一次浏览器运行的真实输出为时间线（相对毫秒偏移 + 级别颜色 + 点击展开详情的**本地交互**，零 LLM 调用，§9.1）；数据绑定 `run:latest`；无数据诚实空态；
- IDE"调试"与"实验"模式画布从占位替换为 SceneRenderer + 内置标准场景 `runtime.console-timeline.v1`；"架构"画布保持占位（static 来源组件未实现）。

**影响**：P3.2 的第二类组件（调用栈/变量状态）按注册表模式追加；L2 动态组合（AI 产出 SceneSpec JSON 经 schema 严格校验）与 P3.3 codeVersion 绑定在其上扩展；L3 按需生成保持未实现。

---

## D23 · H4 门控与三模式：Gate 强制 + 提示词自律双防线，建议为拉取式

**背景**：P2.6 落地设计 §8.2/§8.3。H4（答案级帮助）必须用户明确请求；三模式要有真实行为差异而非摆设。

**决策**：
- **H4 双防线**：系统提示词声明"默认启发、不代写"（第一道，冒烟证实真实模型自律给出 H2 而非 H4）；Policy Gate 强制"hintLevel=4 且未请求 → 降级 H1 + 固定安全文案"（第二道，单测用 Mock Provider 强制 H4 提案验证降级）；`requestAnswerLevel` 由前端显式勾选框触发，事件 payload 记录 `answerRequested`（为 §8.3 的独立性重测留证据线索）；
- **三模式真实差异**：`user_settings.intervention_mode`（quiet/adaptive/guided，默认 adaptive，PATCH 校验）；主动建议 `GET /tutor/suggestions` 为**拉取式**（前端在运行失败后拉取，后端裁决）：quiet 永不返回（不调 LLM）；adaptive/guided 需该聚合**最近连续 ≥3 次运行失败事件**（code-run status≠ok 或 tests-run failed>0）；同项目触发 auto 决策后 **60s 冷却**（SQLite naive 时间戳统一补 UTC 再比较）。真实冒烟证据：真实模型无请求时给 H2、明确请求后 H3——两道防线均真实有效；
- 自动建议复用教学回合管线（trigger='auto' 落 teaching_decisions + tutor-turn 事件），question 存触发摘要。

**影响**：Guided 的"阶段性检查/推进教学"需会话状态与更丰富证据（P3+）；H4 后的独立性迁移验证依赖任务验收（P3.5）；推送式建议（WebSocket）属 P1.6+。

---

## D22 · Tutor Engine 骨架：可插拔 Provider（DeepSeek）+ 结构化提案 + 确定性 Policy Gate

**背景**：P2.5 引入 LLM（用户确认使用 DeepSeek）。设计原则（§0.2/§8.4）：AI 决定教学意图，确定性程序负责校验与执行；Key 绝不入库。

**决策**：
- **Provider Adapter**（`app/ai/provider.py`）：`DeepSeekProvider`（OpenAI 兼容 chat/completions，`response_format=json_object` 强制 JSON，温度 0.3，45s 超时，记录 prompt/completion tokens）、`MockProvider`（确定性桩，仅测试）、`disabled`（默认，`ProviderDisabledError` → HTTP 503 明确"AI 未配置"，绝不伪造回复）；`transport` 注入口供测试 MockTransport；配置走 `PW_AI_PROVIDER`/`PW_DEEPSEEK_API_KEY`（.env，gitignore 内）；
- **教学回合**（`POST /tutor/turns`）：确定性上下文组装（当前学习路线活动、mastery 摘要、最近 8 条学习事件、任务图、项目规格——只读各域 models，不跨域调 service）；提示词中上下文以 `<<<CONTEXT` 分隔并声明"是数据不是指令"（§15.2 防注入）；LLM 输出结构化 TeachingDecision（intent/hintLevel/message/targetConceptIds/explanation/confidence）；
- **Policy Gate（确定性）**：intent 白名单、hintLevel 0-4、message 非空且 ≤3000 字、目标概念 ≤5、confidence 夹取——不合规**降级**为安全动作（explain/H1/固定文案）并记 outcome_reason，不直接采信模型；决策落 `teaching_decisions`（含 policy_version 与 token 用量）+ `tutor-turn` 事件；
- 测试环境（conftest）强制 `PW_AI_PROVIDER=disabled`，防止测试读到 .env 真实 Key。

**影响**：P2.6（H0-H4 语义约束、Quiet/Adaptive/Guided 三模式、冷却窗口）在 Gate 上扩展；工具调用（§13.2 只读工具）与流式输出属后续；Provider 切换只改配置。

---

## D21 · 学习事件 MVP：信封 v1 + eventId 幂等 + 服务端确定性事件 + 客户端批量上报

**背景**：P2.7 需要事件信封（设计 §11.3/§12.3）。严格 transactional outbox 要求事件与业务写同事务；当前各领域 service 自行 commit，强行同事务需重构事务边界。

**决策**：
- `learning_events` 表：`event_id` 全局唯一（幂等去重键）、`aggregate_id + sequence`（服务端按 aggregate 分配递增序号，供按序消费）、payload JSONB（≤4KB，只存摘要与引用，不存代码全文/密钥——设计 §12.3 隐私约束）；
- **服务端事件**在 router 编排层追加（与 D19 的证据编排同模式）：`file-saved`（确定性 eventId=uuid5(项目/路径/updated_at)，同次保存重放自动去重）、`plan-generated`/`plan-replanned`（uuid5(plan.id)，重复 GET 幂等）、`assessment-submitted`（含三档计数摘要）；暂为业务 commit 后独立事务——**非严格同事务 outbox**，崩溃窗口内可能丢事件而状态已变更，界面与文档如实标注；
- **客户端事件**（`code-run`/`tests-run`）由前端 eventTracker 批量上报（满 5 条或 30s flush，失败保留队列重试=至少一次；服务端去重兜底）；刷新丢失未 flush 事件是已知限制；
- 类型白名单 + 批量 ≤20 条 + payload 上限，防滥用（键击/鼠标永不入事件，设计 §11.3）。

**影响**：严格同事务 outbox 随 P1.7（身份/会话）事务边界重构时落地；事件消费方（自动重规划触发、Tutor 决策依据）按 (aggregate_id, sequence) 幂等回放；IDE 事件页签直接展示日志。

---

## D20 · 课程规划 MVP：样板任务模板 + 规则化规划器（先修闭包 + 掌握跳过）

**背景**：P2.4 需要任务-知识双图规划（设计 §7）。任意目标自动生成任务图依赖 AI 且风险高（设计非目标：不承诺任意目标都能自动生成课程）；样板课程（附录 B）是 MVP 固定路线。

**决策**：
- `project_tasks` 由**确定性模板**种子（样板课程六任务，附录 B 的依赖/知识映射/交付物/effort），首次生成 plan 时播种；界面标注"样板课程模板"；
- 规划器为纯规则（无 LLM）：任务按依赖拓扑排序；每个任务的知识要求扩展为**先修闭包**（依赖浅者先学）；掌握判定复用 D19 阈值（估计 ≥0.75 且置信 >0.5）——已掌握跳过并记原因，未达标生成 learn-concept 活动并记原因（"未诊断/证据不足/估计偏低/先修补课"），practice-task 始终保留（掌握知识 ≠ 完成交付物，设计 §2.3 三种完成状态）；
- `learning_plans` 版本化：GET 幂等返回最新，replan 显式递增版本、历史保留；reason 记录生成依据（累计证据数与阈值）。

**影响**：设计 §7.2 的优先级公式（dependency_urgency × knowledge_gap × …）留待有多活动类型与时间预算后引入；重规划 diff 展示属后续；路线对 mastery 变化不自动触发（需用户点击重新规划），自动触发与 P2.7 事件挂钩。

---

## D19 · 学习者模型 MVP：四维结构 + 逐维证据驱动更新，无证据的维度保持 null

**背景**：P2.3 落地设计 6.2/6.3/6.5。四维（理解/应用/调试/独立）中，当前只有诊断预测题能产生可信证据。

**决策**：
- `learner_mastery.dimensions` 为 JSONB 字典，**只写有证据的维度**——prediction/explanation 证据更新 understanding，coding→application，debugging→debugging，transfer→independence（映射表即设计 6.3 词表）；其余维度保持缺失，界面显示"尚不确定"，绝不编造估计（设计 6.2："估计值是系统推断，不能直接写作客观测量分数"）；
- 估计 = 该维度全部证据通过率；置信度 = min(0.9, 0.3+0.2×证据数)（保守递增封顶）；`model_version=rule-v1` 随记录保存；
- 证据逐条落 `learning_evidence`（来源 assessment、item、rubric 版本），诊断提交在 **router 层编排**写入（领域 service 互不 import，遵循 AGENTS 边界规则）；
- `GET /mastery` 按当前 owner 返回；知识图谱页叠加显示理解维徽标（证据 <2 条显示"尚不确定"）。

**影响**：P2.4 课程规划可直接消费 mastery（null/低置信 = 需诊断或补课）；测试运行、任务编码等新证据类型按映射表接入即可扩展其余维度；BKT/IRT 等概率模型属后续实验（设计 6.4）。

---

## D18 · 能力诊断 MVP：客观预测题 + 确定性判定 + 概念三档初判

**背景**：P2.2 需要初始能力诊断（设计 6.4、FR-02）。解释题评分与小编码任务判定依赖 Tutor Engine 与运行数据，尚不存在；且设计明确"MVP 使用清晰的规则与保守的概率更新"。

**决策**：
- 题库为**确定性种子**（15 道单选预测题，覆盖 15 个种子概念，带难度 1-3 与版本号），不是 AI 生成；
- 选题规则：项目 stack 关键词映射诊断域（前端栈→js/ts/browser/engineering，其他→js/engineering），按概念图**拓扑深度 + 难度**排序、每概念一题、上限 8 题（呼应"诊断范围由项目需求反推，不做通用语言考试"）；
- `POST /assessments/start` 下发的题目**绝不包含 answerIndex**；`submit` 与题库确定性比对，逐题写 `assessment_answers`，概念级三档初判（likely-mastered / uncertain / likely-gap，按答对比例）存于会话 `results` JSON（含题目快照与题库版本，历史可追溯）；
- 重复提交 409、缺题/多题/越界选项 422，均有测试；三档是**初判**，置信度与证据模型属 P2.3（界面已标注）。

**影响**：P2.3 把 results 转写为 learner_mastery（四维 + 置信度）与 learning_evidence；解释题/编码任务诊断在 Tutor Engine 接入后扩展；题库扩充只追加不改 id（同 D17 惯例）。

**附带**：script.py.mako 模板补 `from sqlalchemy import Text`，根治 autogenerate 迁移反复缺 import 的问题。

---

## D17 · 知识图：字符串主键 + 启动幂等种子 + 服务端 DAG 校验

**背景**：P2.1 建立知识图谱（设计文档 6.1/12.2）。ConceptId 是贯穿诊断、任务关联、掌握度记录的稳定标识。

**决策**：
- `knowledge_concepts.id` 用人类可读字符串主键（如 `js.closures`）而非 UUID——知识 ID 要出现在课程 JSON、诊断题目、证据引用中，可读性优先；
- 先修关系存为 id 数组（JSONB）；`validate_graph` 在种子写入与测试中强制**无环、无悬空引用、无自引用**（设计 5.3"不得产生不可解释的循环先修"）；
- 种子是**确定性模板**（17 个概念，围绕样板课程附录 B：JS 10 / TS 2 / 浏览器 2 / 工程 3），启动 lifespan 空表时幂等写入；概念带 `version` 字段供后续内容演进；
- 评估方式取自设计 6.3 的证据类型词表（prediction/explanation/coding/debugging/transfer）。

**影响**：诊断（P2.2）与课程规划（P2.4）按 id 引用概念；种子扩充只追加不改 id；内容管理后台（编辑概念）不在近期范围。

---

## D16 · PostgreSQL 切换验证完成：双库兼容由可重复套件保障，容器端口固定 5433

**背景**：D2 自 P0 起以 SQLite 为开发默认、PostgreSQL 为目标库，"双库兼容"一直未被验证。本机 5432 已被既有 PostgreSQL 占用、8000 也常被本机服务占用。

**决策与结论**：
- docker compose 的 PG 16 映射宿主机 **5433**（不动本机 5432 服务）；psycopg2-binary 正式列入 requirements；
- 新增 `tests/test_postgres_compat.py`：默认 skip，设置 `PW_TEST_DATABASE_URL` 后启用（自动创建/清理 `projectweave_pytest` 库），覆盖迁移 upgrade→downgrade→upgrade 重放、列类型断言（projects 主键为原生 uuid、spec 数组字段为 **JSONB**、时间为 timestamptz）、项目/文件/快照 CRUD 冒烟（中文、JSONB 数组、快照恢复、codeVersion）、路径校验；
- 真实服务级验证通过：uvicorn 以 PG 为库启动，lifespan 自动迁移 3 个版本，CRUD 正常；**SQLite 下时间戳无时区后缀的已知差异（D2/D16）在 PG 上消除**（`createdAt` 带 Z）。

**附带修复**：alembic.ini 补 `path_separator = os`（否则其 DeprecationWarning 会被 pytest 的 error 过滤器升级为失败）。

**影响**：CI/本地可随时跑 PG 套件防止兼容性回退；SQLite 仍是默认开发/单测路径。

---

## D15 · 快照模型：覆盖前旧内容入历史，文件级保留 50 份，删除文件连带清理

**背景**：P1.3 需要代码快照与 codeVersion（设计文档 12.2/14.3）。对象存储与内容寻址是远期方案，当前文件已内联 DB（D9）。

**决策**：
- 快照在 `write_file` 覆盖旧内容时产生（**同内容跳过**），快照存的是"历史版本"，当前态在 project_files；每文件按 (created_at, id) 倒序保留最近 50 份（写入后显式 flush 再裁剪，适配 autoflush=False 会话）；
- `restore` 先把当前内容入快照再写回，任何路径不丢数据；恢复相同内容不产生空快照；
- 重命名时快照 path 跟随；**删除文件时连带清理其快照**（避免孤儿数据与"恢复已删文件"的语义歧义，恢复被删文件可先从历史复制内容再新建）；
- `codeVersion` = 全部文件按路径排序后对 `path + content` 整体 SHA-256，**实时计算不落库**（快照历史不影响指纹）；
- 自动保存为前端 2.5s 防抖（默认开启、可关），失败错误可见。

**影响**：codeVersion 的消费方（执行 trace、教学场景绑定、学习证据引用）在 P2/P3 接入；多用户/大项目下快照内联存储的容量再评估（届时引入内容寻址 + 对象存储）。

---

## D14 · 测试运行时自研并注入 Worker（describe/it/expect），文件级执行

**背景**：P1.5 需要断言式测试（任务验收的第一个自动化依据）。现成方案（vitest/jest）无法在 Blob Worker 里运行；把测试文件当普通脚本跑则没有用例级结果。

**决策**：在 `buildTestSource` 里向 Worker 注入约百行的微型测试运行时：`describe`（嵌套前缀）/`it`/`test` 注册、`expect` 断言（toBe/toEqual（深比较）/toBeTruthy/toBeFalsy/toContain/toThrow 与 `.not`），逐用例顺序执行并回传 `test-result`，结束后 `test-summary` + `done`（复用 P1.4 的结束协议与超时机制）。文件级聚合由 `runTestSuite` 完成：拉取全部 `*.test.<js|ts>`，当前打开文件用未保存草稿优先。

**理由**：教学场景需要的断言集合小而稳定；自研运行时保持零外部依赖、消息协议简单、失败信息可教学化（如 `expected 1 to be 2`）。测试文件为单文件模式（Worker 无法解析 import），种子示例已自包含并注明。

**影响**：断言 API 是本产品子集，不承诺兼容 jest/vitest 语法全集；后续如需 watch/覆盖率再评估。

---

## D13 · alembic.ini 必须保持 ASCII（Windows locale 编码陷阱）

**背景**：zh-CN Windows 上 Python configparser 以系统 locale（GBK）读取 ini。alembic.ini 中的中文注释在 UTF-8 字节流下触发 `UnicodeDecodeError`，导致 uvicorn 启动失败（此前某次环境变更后暴露；venv 实际基于 Python 3.13 而非最初记录的 3.10）。

**决策**：alembic.ini 注释改用英文并在文件头注明"保持 ASCII"；Python 源码不受影响（默认 UTF-8）。文档同步更正 venv 版本记录。

---

## D12 · TS 运行时转译使用 `ts-compiler` 别名（npm:typescript@~5.9），而非工具链的 TS 7

**背景**：`.ts` 文件要在浏览器运行前转译。仓库的 TypeScript 工具链（tsc 类型检查）已是 7.0.2——原生编译器移植版，**不再提供经典 JS API**（无 `transpileModule`、无 `ScriptTarget` 枚举），无法在浏览器中调用；npm 也不允许同一包在 dependencies/devDependencies 中解析为两个版本。

**决策**：以 npm 别名安装 `ts-compiler@npm:typescript@~5.9.3` 作为运行时依赖（提供完整 JS API），通过 `await import('ts-compiler')` 动态加载——Vite 将其拆为独立懒加载 chunk（约 3.3MB），仅在首次运行 .ts 文件时下载。工具链继续用 TS 7 的 tsc。

**影响**：两份 TS 版本并存（工具链 7.x / 运行时转译 5.9）；转译为单文件模式（`ModuleKind.None`），代码中的 `import` 语句在 Worker 里会因无法解析模块而报错——这符合“浏览器运行器无外部依赖”的定位，错误信息如实呈现。

---

## D11 · 浏览器运行器：Blob URL + module Web Worker，主线程持有终止权

**背景**：设计文档 14.1 规定浏览器内运行适合 JS 学习任务，且禁止在应用服务器进程执行不可信代码。

**决策**：用户代码在 `new Worker(blobURL, { type: 'module' })` 中执行：
- Worker 内劫持 `self.console`，输出经 postMessage 流式回主线程（对象 JSON 序列化、循环引用标记 `[Circular]`、函数/bigint/Symbol 特殊处理）；
- 用户代码包进 async IIFE，支持顶层 await，同步/异步异常统一上报；
- 主线程 5 秒超时强制 `terminate()`（防死循环），任何结束路径都 terminate；
- 不 revoke Blob URL（模块 Worker 异步加载存在竞态，KB 级泄漏可接受）。

**边界（诚实标注，非伪装）**：Worker 隔离是“便利级”而非安全边界——同源 Worker 理论上可发起 fetch。真正的网络/资源限制属于后续远程隔离沙箱（P4/设计文档 14.2），终端面板已标注“无 DOM/应用状态访问”。测试通过 `node:vm` 隔离全局真实执行 Worker 脚本文本（沙箱对象即全局，与 Worker 语义一致）。

---

## D10 · 文件模块放在 projects 领域内，而非独立 files 领域

**背景**：AGENTS.md 规定领域模块之间不横向 import 其他领域的 service。文件操作强依赖项目存在性校验（404 语义）。

**决策**：文件作为 projects 领域的一部分（`file_models/file_schemas/file_service/file_router` 均在 `app/domains/projects/` 下），路由挂在 `/projects/{id}/files`。将来若文件能力膨胀（快照、对象存储、执行环境编排），再评估拆分为独立 workspace 领域。

---

## D9 · 文件内容内联存数据库（TEXT，上限 1MB），不做对象存储

**背景**：设计文档规划 code_snapshots + 对象存储，但那是为版本快照与执行轨迹准备的；当前只有“当前态”文件。

**决策**：P1.1 阶段 `project_files.content` 直接以 TEXT 存储，单文件 ≤1MB、单项目 ≤2000 文件。P1.3 引入快照时再评估内容寻址与分离存储。

**理由**：教学项目的源码文件体积小、数量少；内联存储让读写路径最简单，避免过早引入对象存储依赖。

---

## D8 · 新建项目自动种子 README.md + src/main.ts

**背景**：IDE 已接入服务器文件系统，空项目会让文件树/编辑器无内容可操作，首次体验断裂。

**决策**：`create_project` 在同一事务内写入两个确定性模板文件（README 含项目标题与描述、src/main.ts 为带说明的入口草稿）。前端进入 IDE 时默认打开 README.md。

**理由**：模板由确定性代码生成（非 AI、非伪造数据）；设计文档中任务的 starterState 未来接入 Curriculum Engine 后可替换此默认行为。API 层面若调用方不想要脚手架，可创建后删除。

---

## D7 · Monaco 0.5x 的 worker 不做手动 `?worker` 导入

**背景**：Vite 8 (rolldown) 构建时 `monaco-editor/esm/vs/editor/editor.worker?worker` 解析失败——monaco-editor 0.57 的 package.json `exports` 映射（`./*` → `./esm/vs/*.js`）会把深层子路径加倍，静态深导入全部失效。

**决策**：不在代码中手动导入任何 worker、不配置 `MonacoEnvironment.getWorker`。monaco 0.5x 在打包器环境下通过 `new Worker(new URL('xxx.worker.js', import.meta.url), { type: "module" })` 自建语言 worker，基础 worker 走 `esmModuleLocationBundler` 描述符，两者由 Vite 原生转换；`@monaco-editor/react` 通过 `loader.config({ monaco })` 使用本地实例，全程无 CDN。

**影响**：构建产物包含全部 worker（约 14MB dist）；升级 monaco 主版本时需重新验证 worker 加载方式。

---

## D6 · 编辑器内容 P0 阶段使用浏览器本地草稿

> **状态更新（P1.2）**：本地草稿已被服务器端文件系统取代（保存 = PUT 持久化）；本文仅保留历史记录。

**背景**：服务器端文件系统（project_files 表、保存 API、快照）属于 P1；但 IDE 骨架若完全不能输入则没有演示价值。

**决策**：Monaco 内容存入 `editorDraftStore`（Zustand persist → localStorage），按项目 ID 隔离；UI 上明确标注「本地草稿 · 未同步到服务器（P1 提供文件持久化）」。

**理由**：既保证刷新不丢失的体验，又不伪造“已保存到服务器”的假象，符合“不伪装完成”原则。

---

## D5 · spec 数组字段暂存 JSON 列，里程碑不建独立表

**背景**：设计文档 §12.2 规划了 project_tasks 等独立表，但 P0 只有项目规格 CRUD，没有课程生成。

**决策**：`target_features / non_goals / stack / milestones / acceptance_criteria` 以 `JSON().with_variant(JSONB(), "postgresql")` 存在 projects 表内。待 Curriculum Engine 阶段（P2）再把任务图拆为 project_tasks 表并做迁移。

**理由**：避免为尚无消费方的结构过早建模；JSONB variant 保证将来 PostgreSQL 上可用 GIN 索引。

---

## D4 · API 对外 JSON 使用 camelCase

**决策**：后端 Pydantic 契约统一 `alias_generator=to_camel, populate_by_name=True`；前端 zod 契约同名字段。前端手工镜像契约并用 zod 校验响应。

**理由**：前端 TS 生态以 camelCase 为惯例；`populate_by_name` 同时兼容 snake_case 调试请求。
**未来改进**：考虑从 FastAPI 的 openapi.json 用 `openapi-typescript` 生成前端类型，消除手工镜像（P1+）。

---

## D3 · 后端使用同步 SQLAlchemy

**决策**：SQLAlchemy 2.0 同步引擎 + `def` 端点（FastAPI 自动线程池执行）。

**理由**：P0-P1 的负载（项目 CRUD、文件读写）下更简单可靠，测试也简单；WebSocket 端点（P1 的会话事件流）与同步 DB 不冲突。待出现真实高并发 IO 需求（多路执行沙箱编排）时再评估 async。

---

## D2 · 开发/测试默认 SQLite，生产目标 PostgreSQL

**决策**：`PW_DATABASE_URL` 默认 `sqlite:///./projectweave.db`；测试用临时 SQLite 文件 + `Base.metadata.create_all`。docker-compose.yml 预置 PostgreSQL 服务供联调切换。

**理由**：设计文档指定 PostgreSQL 为目标库；但第一阶段要求零外部依赖即可启动与测试（Windows 本机无 Postgres 也能跑通全流程）。通过 SQLAlchemy + JSON variant + `render_as_batch` 保持双库兼容，P1.8 做切换验证。
**代价**：SQLite 下 `DateTime(timezone=True)` 返回 naive UTC（序列化无时区后缀）、无数组/JSONB 高级索引——均在切换 PG 时消除。

---

## D1 · P0 不引入认证，owner_id 预留占位

**决策**：单用户开发模式，`owner_id` 列固定 `dev-user`；不实现注册/登录。

**理由**：第一阶段验收目标是“创建-持久化-展示”纵向切片；认证方案（自建 vs OAuth）值得与用户确认后单独立项（P1.7）。所有查询已带 owner_id 过滤钩子（service 层参数），接入认证时只改入参来源。

---

## D0 · monorepo 布局 backend/ + frontend/ + docs/

**决策**：单仓库、双工程、共享 docs/；不引入 pnpm workspace/nx 等工具。

**理由**：两工程技术栈不同（Python/Node），无共享包；保持启动命令最简。
