# 技术决策记录（ADR）

格式：背景 → 决策 → 理由 → 影响。按时间倒序追加。

---

## D30 · 执行层语言无关架构：Profile + Backend 路由 + esbuild-wasm 多文件打包

**背景**：P4.2a 要求多文件 TypeScript 运行与跨文件测试，且最终必须支持 Python 和 C++。不允许把执行系统设计成 TypeScript 专用。

**决策**：
- **语言无关契约**（`lib/execution/types.ts`）：ExecutionRequest（mode/entryPoint/testPaths/files/languageId）→ ExecutionResult（ok/buildDiagnostics/runtimeDiagnostics/output/testResults/modules/buildTimeMs/runTimeMs/codeFingerprint）；Diagnostic（severity/message/file/line/source: build|runtime|test）；信任级 practice/formal 由 Backend 声明（browser=practice，remote=formal）。
- **LanguageProfile**（`lib/execution/LanguageProfile.ts`）：纯数据记录（extensions/testPattern/moduleSystem/supportedBackends），不含运行逻辑。TypeScript 完整注册；**Python/C++ Profile 已定义但 supportedBackends=[]**——execute() 会抛 UnsupportedExecutionError，不伪造运行能力。
- **ExecutionBackend**（`lib/execution/ExecutionBackend.ts`）：策略接口（backendId/capabilities/canHandle/execute/prepare?）。registry 按 Profile→Backend 路由；扩展新语言 = 注册 Profile + 实现 Backend，零修改 Curriculum/Learner/TeachingScene。
- **TypeScript BrowserBackend**（`backends/browserWorker.ts`）：适配现有 runner 基础设施——单文件 ts-compiler 转译 / 多文件 esbuild-wasm 打包（VFS 插件、路径安全、扩展名补全、npm 包拒绝、编译计时）→ Worker 沙箱执行（console/observe/test 运行时注入）。maxTrustLevel=practice。
- **Remote Backend 占位**（`backends/remoteStub.ts`）：createRemoteBackendStub() 工厂 + REMOTE_BACKEND_IDS（remote-pytest/remote-cmake/remote-sandbox）；canHandle=false → 不会被 registry 选中；实现时只需改为 true 并实现 execute()。
- **多文件打包**（`runner/bundler.ts`）：esbuild-wasm 懒加载（首次多文件运行下载 ~14MB WASM，后续复用）；虚拟 FS 插件按需返回文件内容；路径规范化禁止 `..` 越界；模块不存在时报错定位到 importer 文件。
- **单文件兼容**：`runFile.ts` 的 `prepareScript(path, content, vfs?)` 无 VFS 时始终走单文件转译（含 export 语句），旧调用零破坏。

**影响**：Python/C++ 扩展路径已铺好（Profile 定义 → 实现 Backend → 注册），无需重构执行层；esbuild-wasm 增加首次运行延迟（~10s WASM 加载），后续复用；试点课程测试文件已改为 `import { parseHeadings } from './headings'` 跨文件引用——transform.test.ts 真正导入三个模块（headings + inline + transform），transform.ts 起始代码 import 而非复制前两任务实现。

---

## D29 · 任务驱动教学闭环：试点课程 + 任务级测试绑定 + practice 信任级

**背景**：P4.1 要求"创建→诊断→路线→IDE→任务→编码→测试→AI 提示→修正→完成→下一任务"全流程真实运行。关键约束：客户端自报测试结果不可视为正式验收（设计 §6.5/§2.3 三种完成状态不可混淆）。

**决策**：
- **试点课程**（确定性，pilot_course.py）：TS Markdown 解析器 3 任务（标题→行内→模块组合），全部浏览器 Worker 单文件执行（无 import），每任务含初始代码+测试文件+验收条件；项目创建时种子全部文件到 project_files；
- **ProjectTask 模型扩展**：test_files（任务级测试绑定路径列表）、starter_files（初始代码）、acceptance_criteria（展示给学习者）；迁移 3843e18441fe（SQLite server_default='[]' 后清除，兼容已有行）；
- **评估 rubric v2（task-scoped）**：只统计任务绑定的 test_files 内的文件结果；**越界文件忽略+告警**；**防伪守卫**——无绑定测试/空文件/零断言 → needs-fix 不判通过；判定是确定性程序（非 AI）；
- **practice 信任级**：浏览器端测试运行结果始终标记 `trustLevel=practice`（客户端自报，非独立考核）；正式验收（formal）需要服务端可信执行——当前不存在，界面与 API 响应如实标注"练习（客户端自报，非正式验收）"；
- **Tutor 任务感知**：前端随请求发送 `extras`（currentTaskId / currentCode[服务端截断 2000 字符] / recentRunResult），服务端补充 helpHistory（最近 3 条求助记录）——**最小必要上下文**（§10.3），不发整个项目；
- **前端 TaskPanel**：任务列表+详情+「运行任务测试并验收」（只跑绑定的 testFiles）→ 逐用例反馈 → 验收结果卡（含 trustLevel/warnings/证据概念）→ 下一步任务引导。

**影响**：runTestSuite 返回值增加 `files` 数组（逐文件结果，向后兼容）；PlanTaskRead 扩展字段（旧客户端可忽略新字段）；正式能力认证需等远程沙箱阶段的服务端可信执行；两个后续任务（md-inline/md-module）已定义全部内容但仅 md-heading 完成真实端到端验证。

**决策**：
- **后端（提案侧）**：TeachingDecision 新增 `workspace_actions`；`validate_workspace_actions` 确定性分级（display-notice→A0 / switch-layout→A1 / propose-patch→A2）+ payload 校验（模式白名单/消息必填/path+description 必填）+ 数量封顶 3；**A2 补丁提案未随 requestAnswerLevel 时移除**（与 D23 H4 门控联动——补丁即答案级内容）；非法动作移除并记入 outcome_reason（部分降级而非整体拒绝）；系统提示词输出结构扩展 workspaceActions。
- **前端（执行侧）**：`lib/workspace/executor.ts` 确定性执行链——A0 立即通知；**A1 尊重布局锁定**（锁定→拒绝+原因+rejected 事件，AT-05；未锁定→切换+撤销栈，撤销同样受锁定约束）；**A2 一律进确认队列**（展示 path/description/风险文案，确认后仅写入编辑器草稿、绝不自动保存；目标文件未打开则如实提示不应用）；每个动作上报 `workspace-action` 审计事件（executed/rejected/needs-confirmation/confirmed/undone）。
- **挂载方式**：`WorkspaceNoticeStrip`（新组件）+ 决策回调处调用 `applyWorkspaceActions(decision, projectId)`——单行接入点已就绪，待并行前端合入后挂载（IdePage 画布顶部或 MentorPanel）。

**影响**：P3 全部条目交付（挂载为收尾一行）；A2 确认应用草稿后 H4 的独立性重测可引用 workspace-action 事件；撤销栈为会话级（不持久化，与设计 §10.2 undoToken 语义一致——token=decisionId:index）。

**端到端集成追记（同日）**：并行前端合入后完成挂载——MentorPanel 对**新决策**执行 applyWorkspaceActions（历史决策不重放，避免加载时重演布局切换）；CodeDiff 差异弹窗加确认/拒绝（`confirmPatchAction` 按动作确认，非仅队列）；IdePage 提供**脏草稿守卫**（目标文件未打开或有未保存更改 → 拒绝应用并说明原因，保护用户输入）；**自动保存承诺对齐**——应用补丁必然被 2.5s 防抖保存，故文案改为"写入草稿并随自动保存保存到服务器，应用前内容进入历史快照（D15）可恢复"，UI 承诺与实际行为一致；apply 回调签名改为 `PatchApplyResult {applied, reason?}` 以区分拒绝原因。

---

## D28 · WorkspaceAction：后端分级校验 + 前端确定性执行器（A0/A1/A2），UI 挂载避让并行开发

**背景**：P3.4 落地 §10.2 三级权限。仓库存在并行前端 Agent 正重构 IdePage/MentorPanel——本轮**不编辑这两个宿主文件**，执行器与通知条作为独立模块交付。

**决策**：
- **后端（提案侧）**：TeachingDecision 新增 `workspace_actions`；`validate_workspace_actions` 确定性分级（display-notice→A0 / switch-layout→A1 / propose-patch→A2）+ payload 校验（模式白名单/消息必填/path+description 必填）+ 数量封顶 3；**A2 补丁提案未随 requestAnswerLevel 时移除**（与 D23 H4 门控联动——补丁即答案级内容）；非法动作移除并记入 outcome_reason（部分降级而非整体拒绝）。
- **前端（执行侧）**：`lib/workspace/executor.ts` 确定性执行链——A0 立即通知；**A1 尊重布局锁定**（锁定→拒绝+原因+rejected 事件，AT-05；未锁定→切换+撤销栈，撤销同样受锁定约束）；**A2 一律进确认队列**（确认后仅写编辑器草稿）；每个动作上报 `workspace-action` 审计事件。
- **端到端集成追记**：MentorPanel 对**新决策**执行 applyWorkspaceActions（历史不重放）；CodeDiff 弹窗加确认/拒绝；IdePage 挂载 WorkspaceNoticeStrip + 脏草稿守卫（未打开/未保存 → 拒绝应用）；自动保存承诺对齐——应用补丁必然被保存，文案如实"写入草稿并随自动保存保存，应用前内容进入历史快照"。

---

## D27 · 阶段验收：浏览器测试结果提交 + 确定性 rubric（套件全绿）+ coding→application 证据

**背景**：P3.5 落地任务验收（设计 §2.3/§6.5/§13.1）。判定必须由确定性程序完成，AI 口头评价不替代测试与 rubric；测试在浏览器沙箱执行（D11），后端无法自行运行。

**决策**：
- **流程**：前端在详情页点击「测试验收」→ 浏览器运行项目全部测试（复用 runTestSuite）→ `POST /projects/{id}/tasks/{taskId}/evaluate` 提交结果（totalFiles/passed/failed/errorFiles + traceId）→ 后端确定性判定与落库；
- **rubric v1（suite-green）**：≥1 个测试文件、0 失败、0 文件级错误 → `done`；否则 `needs-fix`（新增状态值，前端徽标"需修正"）；**依赖闸门**：depends_on 未全部 done → 422（任务图语义，设计 §5.3）；
- **证据**：通过/失败均为任务每个必需概念写 `coding` 证据（D19 映射 → **application 维首次真实数据**；失败也是证据，估计如实下降）；`task-evaluated` 事件入白名单（payload 含结果摘要与 traceId，与运行可关联）；
- 任务级测试绑定（设计 §5.3 task.tests[]）留待课程内容制作——MVP 以项目套件整体为验收依据，界面 tooltip 已注明。

**影响**：mastery 的 application 维开始积累，重规划可将 application 纳入掌握判定（当前仅 understanding，扩展点已在 D19 预留）；H4 后的独立性验证可引用验收证据；rubric 版本化（suite-green-v1）供后续演进对照。

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

---

## D29 · 前端重建：实际开源控件、真实数据与按场景加载

**日期**：2026-10-10。

**决策**：复制并定制 shadcn/ui、Magic UI BlurFade、Motion Primitives AnimatedGroup 的原始源码，保留许可证；复用 Radix/cmdk 交互能力。使用 react-resizable-panels v4 管理锁定与尺寸保存，Monaco 继续编辑并新增只读 Diff，xterm 展示真实 Worker 流，React Flow + ELK 布局真实知识图。所有库映射统一 token，Motion 尊重 reduced-motion；不添业务 mock。静态分析架构/状态机与任务图、补丁应用宿主接入留到其数据与权限流程完备后。

**理由**：成熟原语提供焦点、键盘、拖动与编辑能力；增量替换展示层可保留既有文件/教学/验收逻辑。知识依赖已具备真实数据，应先验证这一个图切片；执行可视化保留现有 SceneRenderer，不把变量/时间线强行转成 React Flow。

**代价与许可**：Monaco、TS 编译器与 ELK 仍有大体积 chunk；路由、图、Diff、终端和编译器按需加载，保留构建警告。ELK 包标注 EPL-2.0 OR GPL-3.0-or-later，本项目选 EPL-2.0、未修改其代码，发行保留完整许可和源码获取声明；不能按 MIT 描述。详见 `UI_COMPONENTS.md` 与 `frontend/public/licenses/NOTICE.txt`。

**验收发现修复**：原 TS 单文件种子 export 生成全局 exports 引用，Worker 报 ReferenceError；现使用 CommonJS 输出加局部 exports 的 async 包装，await 完成后才结束，保留不支持多文件 import 的边界，并以真实 Worker 脚本执行回归。保存后 updatedAt 更新会刷新历史列表，避免 Diff 入口直到切换文件才出现。Diff 包装库默认在 widget 解绑前释放模型会抛异常；现由父 layout cleanup 先解绑、释放模型，再由库释放 widget，既不吞异常也不保留泄漏模型，3次真实开关复测通过。

**验证**：npm run verify 191 用例/typecheck/build 通过；后端 123 passed / 4 skipped；1440×900 / 1920×1080 真实浏览器编辑、保存、Diff、运行/测试、分栏/锁定与知识图验收。真实 LLM 提案仅做契约/UI fixture 验证，本轮禁用 AI Provider。

## D30 · 自由工作区使用 Dockview，稳定宿主保留编辑状态

**日期**：2026-10-10。

**背景**：用户要求编辑器各板块可自由挪动与显隐；固定分栏只能调尺寸，无法表达自由停靠/合并/悬浮。

**决策**：以 DockviewReact 8.4.1（MIT）替换 IDE 固定分栏，注册 9 个真实面板。四模式只提供预设，按项目和模式保存版本化布局；顶栏提供始终可达的显隐和重置。所有动作服从 ideUiStore 实时锁定；布局持久化校验白名单/有限树结构并剥离业务参数。使用稳定 DOM 宿主 + React portal，停靠组件只挂载宿主，使 Monaco 与导师内容在移动/隐藏/模式切换时保持；布局边界 overflow-clip 隔离屏幕外渲染内容。

**理由**：成熟开源停靠能力满足真实自由布局；保留编辑器实例可以避免用户撤销记录/导师输入在布局操作中丢失，业务 API 与 Worker 无需改造。

**取舍**：IDE 路由 JS 655.22 / gzip 166.03 kB，继续 lazy 加载并保留构建警告。只支持工作区内悬浮；未安装 Enterprise，v8 商业 keyboardNavigation 不启用，键盘用户使用 Radix 菜单完成布局操作。页面刷新恢复布局，不承诺刷新恢复 Monaco undo 或未发送导师输入。

**验证**：npm run verify 201 用例/typecheck/build 通过；新增 6 个实际库测试；浏览器拖动合并/拆分、缩放、锁定拒绝、模式/刷新恢复、Monaco 隐藏恢复后撤销与真实 Worker/2 个种子测试通过。许可完整保留于 public/licenses/dockview.txt。

## D31 · 外观浏览器存储与编辑实例实时配置

**日期**：2026-10-10。

**决策**：以独立 appearanceStore 和版本化 zod 白名单保存当前浏览器外观，复用 Radix 设置原语；共用 token 驱动页面/知识图，编辑器和终端实例更新 options 与主题，避免重建。SettingsDialog 在设置按钮位置挂载，以获取当前 IDE 布局控制器。减少动态效果取用户关闭或系统减少动态效果的并集。

**理由**：全站即时预览与可恢复默认满足高度自定义需求；与项目布局和服务端 AI 介入模式分离，避免恢复外观意外改变教学行为。稳定 Monaco 模型保留撤销和草稿。

**边界**：本机字体回退；相对字号不等同浏览器缩放；不支持任意 CSS、跨设备同步、已开标签页实时同步。存储异常明确显示，当前更改继续生效。布局重置仍服从锁定且只作用当前模式。完整选项与验证见 UI_COMPONENTS.md。

## D32 · 远程执行沙箱：统一会话协议 + Docker 一次性容器 + 诚实的信任级

**日期**：2026-10-11。

**背景**：P4.2a 只能浏览器执行 TypeScript。Python 需要 CPython 真机运行（input/traceback/pytest），必须服务端执行；用户代码绝不能进 FastAPI 主进程。

**决策**：
- **统一执行协议**（语言无关）：`POST /api/v1/executions`（202 排队）→ `GET /{id}?afterSeq=`（增量事件轮询，SSE 预留同一语义）→ `POST /{id}/cancel`（幂等）。状态机 queued→preparing→running→completed|failed|timed-out|cancelled；**completed = 执行跑完**（程序退出码非 0/断言失败是业务结果），**failed = 基础设施失败**；phases 通用阶段记录（C++ build+run 复用）。
- **隔离手段**（Docker 一次性容器）：network none、read-only 根 + noexec tmpfs（uid 10001 属主）、非 root、cap-drop ALL、no-new-privileges、memory/cpu/pids 限额、stdin tar.gz 注入（不挂宿主目录、不 docker cp）、pw.sandbox 标签追踪 + 启动清理 + 用后即毁（超时/取消 kill 整个容器）。
- **文件防线**：路径校验拒绝绝对/`..`/反斜杠/盘符/保留名/`__pw` 保留命名空间；文件数/总字节/stdin/输出全部上限截断；环境变量白名单（不透传服务端配置）。
- **诚实边界**：普通 Docker ≠ 恶意多租户可靠隔离，仅面向教学失误代码；gVisor/微 VM 未来实现同一 `SandboxManager` 协议即可。**信任级固定 practice**——服务端执行 ≠ 正式认证，正式认证需服务端受保护测试与可信快照（P5）；无 Docker/镜像 → 503 明确报错，绝不伪造。
- 沙箱流式输出经 `read1` 分块读取 + 300ms 节流落库（`read(n)` 会阻塞到读满，教训记录）。

**代价**：每次执行起一个容器（~0.3-1.5s 冷启动）；输出轮询粒度 400ms；会话行内快照使 DB 行较大（上限控制）。

**验证**：后端 162 用例（FakeSandbox 注入：生命周期/校验/上限/503/取消/增量事件/截断）+ PG 4；Docker E2E 11 个（验收 A-G/J 含超时清理、宿主文件与网络封锁、只读根、取消零遗留）；真实 uvicorn 冒烟（import+stdin、取消、容器清理）全过。

## D33 · 语言差异封装在 LanguageRunner，公共执行服务零语言逻辑

**日期**：2026-10-11。

**背景**：执行服务要同时支撑 Python（单阶段解释执行）与未来 C++（build+run 两阶段、编译器诊断、CMake 项目、DAP 调试），公共模块不能渗入语言特有命令或命名逻辑。

**决策**：`LanguageRunner` 协议承担三件事——`validate_files`（扩展名/入口约定）、`build_spec`（构造容器命令 + stdin 文件包）、`parse_result`（原始输出 → 协议化结果）；公共 `ExecutionService` 只做会话状态机、通用校验与资源上限。PythonRunner 首版：CPython 3.12 固定镜像 + 预装 pytest（不做任意 pip install，requirements 受控处理留待后续）；结果经 stdout 尾部 `===PW_RESULT===` 标记行回传（driver 内 pytest Recorder 插件给逐用例 file/line/失败消息，traceback 确定性解析映射文件行号并归一化容器绝对路径）。C++（P4.2c）= 实现 CppRunner（g++/clang 两阶段、诊断 source='build'）+ 注册 Profile，协议与服务零改动。

**取舍**：驱动随每次执行注入 tar（多 ~6KB/次，换取镜像纯净与驱动可升级）；`__pw` 为保留命名空间防用户文件覆盖驱动。

**验证**：python_runner 纯单元 13 个（tar 结构/traceback/pytest 映射/超时标记）；E2E 覆盖多文件 import、pytest 成败定位（断言行号而非 def 行）、收集错误。

## D34 · 编译型语言的可执行工作区：语言专属 exec tmpfs（服务端规格）

**日期**：2026-10-11。

**背景**：D32 的沙箱工作区是 noexec tmpfs（Python 足够）；C++ 必须执行编译产物，但 `noexec` 下二进制无法运行。

**方案比较**：
- A. **语言专属 exec tmpfs**：`SandboxSpec.exec_workspace`（服务端 Runner 构造时声明）→ C++ 挂 `/sandbox` 为 exec tmpfs（256MB）。零额外容器、零宿主中转、清理面不变；exec 范围仍限于一次性容器内。
- B. build/run 两容器：二进制经宿主临时文件/docker cp 中转。冷启动×2、需管两个容器生命周期与中转文件的清理；安全增益有限（产物本就只活在一次性容器里）。

**决策**：选 A。安全敏感策略（exec 与否、tmpfs 大小）只在服务端 `SandboxSpec` 中声明，客户端请求无法触达；Python 保持 noexec 不变；其余隔离（禁网/只读根/非 root/cap-drop/no-new-privileges/资源限额/标签清理）对 C++ 完全一致（E2E 实测 shadow 拒读、根只读、超时/取消零遗留）。

**验证**：C++ E2E 13 个（A-I/K）+ Python E2E 11 个复跑全过；两镜像下安全限制行为一致。

## D35 · CppRunner：确定性源集策略 + CMake 目标解析 + 可执行测试约定

**日期**：2026-10-11。

**决策**：
- **源集选择（driver 内纯函数，可离线测试）**：run = 入口 + 全部非测试翻译单元（多 main 交给链接器报真实错误，不拼接源文件模拟）；test = 测试文件 + 非测试且**内容启发式排除含 `int main(` 的源**（避免多 main 链接冲突——确定性正则，非 LLM）。
- **编译参数服务端固定**：`-std=c++20 -O0 -g -Wall -Wextra -fdiagnostics-color=never`，绝不拼接用户命令；无 CMakeLists 时直接 clang++ 多翻译单元链接。
- **CMake 最小支持**：存在 CMakeLists.txt → `cmake -G Ninja` 配置 + `cmake --build --target`；目标解析 = 包含入口源文件的 `add_executable`（正则解析），未命中回退"目标名=入口去扩展名"约定；配置/编译/运行失败经 phases 与诊断区分；test 模式忽略 CMake 走直接编译（不假装支持 CTest 全量语义）。
- **测试约定**：每个测试文件 = 独立可执行程序；**通过 = 退出 0 且有输出**（输出即断言痕迹）；干净退出非零 = failed（断言失败），崩溃/超时/编译失败/空输出 = error——空测试不得判通过（练习信任级下也不当证据）。
- **诊断分类**：clang 行诊断（file:line:col）与链接符号缺失（GNU ld/lld 双格式，含源位置归一化）→ `source: 'build'`；运行崩溃信号（SIGSEGV 等）→ `source: 'runtime'`；测试断言 → `source: 'test'`；编译失败时 run 阶段显式 `skipped`，绝不报告成功。
- **流式输出**：编译产物以继承 stdout/stderr 直接运行（`_run_streaming`），终端实时可见、取消即时生效（早期 capture_output 版本导致输出憋到进程结束，已修）。
- 镜像：Debian bookworm 固定版本（clang 15.0.6 / cmake 3.25.1 / ninja 1.11.1 + python3 仅驱动运行时）；GCC Profile 未来以同协议另注册。
- 教学联动：Mentor 的 recentRunResult 改为最近一次运行的真实终端摘要（编译诊断/traceback 语言无关可见），诊断带文件行号供 H1-H3 启发式辅导；executionId/指纹/DAP 预留兼容。

**验证**：cpp_runner 纯单元 18 个（诊断解析双格式/源集/目标解析/映射/buildSpec exec 声明）；C++ Docker E2E 13 个全过；前端 247（路由/胶水测试更新）。

## D36 · 交互式调试：LLDB DAP + 长生命周期调试沙箱 + 最小 seccomp 授权

**日期**：2026-10-11。

**可行性验证先行（阶段 A，真实容器实测）**：
- Docker 默认 seccomp **已允许 ptrace**（PTRACE_TRACEME 探针实证）——非 root uid 10001 可调试自有子进程（Yama ptrace_scope 允许后代）；
- 唯一阻塞点：`personality(ADDR_NO_RANDOMIZE)`（LLDB 禁 ASLR）被默认 profile **按值**拦截（允许 0/8/0x20000/0xffffffff，禁 0x40000）；`disableASLR:false` launch 参数不消除该调用（LLDB 启动路径仍调用）；
- 结论：不放宽全局策略，**调试沙箱专用 seccomp** = 上游 moby v28.0.1 默认 profile 仅移除 personality 的参数限制（27 条规则，其余一字不动，`backend/sandbox/cpp-debug/seccomp-debug.json`）；普通执行沙箱零改动。绝不使用 --privileged 或 seccomp=unconfined。普通调试沙箱面向受控开发/教学环境，非对抗恶意公网（同 D32 声明）。

**架构**：
- **DebugSession ≠ ExecutionSession**：调试是长生命周期交互会话——容器常驻（sleep infinity + `docker exec -i` 通道），状态机 CREATING→BUILDING→CONFIGURING→RUNNING⇄PAUSED→TERMINATED（end_reason 区分 completed/build-failed/debugger-error/timeout/cancelled/internal-error）；
- **DAP 通道**：`docker exec -i <容器> lldb-dap` 的 stdio 直通（调试器与被调试程序同容器）；DapClient（Content-Length 帧 + 响应按 request_seq 唤醒 + 事件回调非阻塞）；
- **线程模型防死锁**：DAP 读线程只入队；每会话一个串行线程独占全部 DAP 请求（初始化/事件快照/指令共用队列）——事件回调内绝不发请求；
- **指令白名单**：continue/pause/next/stepIn/stepOut/stop/setBreakpoints/variables——**不从客户端透传任意 LLDB 命令**；调试器不接触项目数据库与敏感路径（文件经 stdin tar 注入一次性工作区）；
- **快照**：每次 stopped 抓取（threads→stackTrace→顶帧 scopes+variables）落库供轮询；空栈短重试（步进瞬间 stackTrace 可能返回空——绝不用空数据冒充）；懒加载经 variablesReference；
- **资源回收三防线**：看门狗线程（空闲 600s/硬上限 1800s，与主循环解耦）→ 服务启动清理遗留容器（pw.debug 标签）+ 悬挂行标记终止 → DAP 通道死亡即回收；轮询即活动（浏览器断连后自然进入空闲回收）；
- 镜像：trixie 固定工具链（clang 19 / **lldb 19.1.7 + lldb-dap**/cmake 3.31/ninja 1.12；bookworm 的 lldb 14 无 lldb-dap 故升级基线），与运行镜像分离互不影响；调试构建 -O0 -g 复用 CppRunner 源集策略与诊断解析。

**代价**：调试会话独占线程+容器（并发上限受机器约束，MVP 不做池化）；DAP 轮询粒度 700ms；ASLR 未禁（LLDB 行为差异可忽略，教学场景无影响）。

**验证**：阶段 A 脚本全过（受限 flag 下 initialize→launch→断点→stopped→栈/变量→单步→terminate）；单测 14（Fake 沙箱 + 假 lldb-dap 子进程真实 DAP 帧协议）；真实 Docker E2E 6（A-H：指定行暂停/单步/真实变量/递归多帧/多文件断点/编译失败不启动调试器/停止清理/空闲超时回收）；真实 uvicorn 冒烟（跨文件断点 + continue 跨文件跳转 + 栈帧 + 零遗留）。

## D37 · 调试前端与教学集成：Monaco 断点装饰 + 真实 DebugSnapshot 进 TeachingScene/Mentor

**日期**：2026-10-11。

**决策**：
- **Monaco 断点**：glyph margin 点击切换（C++ 文件）；断点红点与暂停行高亮经 decorations collection 增量刷新——**不重建编辑器实例**（连续暂停/切换位置保撤销栈）；暂停位置变化自动打开对应文件（栈帧点击同路径）；
- **调试面板**：新增 'debug' Dockview 面板（调试模式预设含）——调用栈（点击选中/跳转）、作用域变量（复杂对象 variablesReference 懒加载展开）、线程、断点验证状态；调试工具栏嵌入编辑器顶栏（启动/继续/单步跳过/进入/跳出/停止）；
- **TeachingScene**：新增 L1 组件 `debug-snapshot`（数据绑定 debug:latest）+ 场景 runtime.debug-snapshot.v1——当前执行位置/可选中调用栈/变量值与**变化标记**（同会话内对比），明确标注"真实 lldb-dap 会话，非 AI 推测"；调试会话存在时画布自动切换该场景；**源码过期提示**（验收 K）：会话 codeFingerprint 与当前草稿指纹不一致 → 画布 stale 横幅 + 编辑器顶部警示（旧调试数据不冒充当前代码）；
- **Mentor 只读联动**：调试暂停时 recentRunResult = 真实 LLDB 快照摘要（位置/栈/局部变量，截断 900 字符）——AI 可依真实暂停数据辅导；**AI 不控制调试器**（指令仅用户 UI 发起），H0-H4 与 Policy Gate 权限不变，不调用 AI 也可完整调试；
- debugStore：断点集合维护（会话中变更同步 setBreakpoints 整文件替换语义）、700ms 轮询（终态停）、503/错误如实呈现。

**验证**：前端 261 用例（新增 14：API schema/调用路径、断点维护/启动门控/轮询收敛/懒加载缓存/setBreakpoints 同步）+ typecheck/build；后端全量 194 + 三语言 E2E 30（Python 11/C++ 13/调试 6）+ PG 4 全过，零遗留容器。

## D38 · 真实内存与指针可视化：白名单 evaluate 地址匹配 + 暂停代次数据隔离

**日期**：2026-10-11。

**数据可得性（探针实测 lldb-dap 19.1.7）**：
- variables 的 `memoryReference` **不存在**（实测全 None）——不能依赖；
- `evaluate "&<变量>"` 可靠返回局部变量地址（格式 `(int *) $0 = 0x…`，与指针变量的 value 精确一致）；
- 空指针显示 `0x0…0`；指针子项（`*p`）可读。

**决策**：
- **指针关系验证**：服务端固定白名单策略——evaluateName 必须匹配标识符/成员/下标链正则（≤3 层）才构造 `&name` 求值；**指针值与变量地址精确相等才画已验证边**；堆指针等无匹配 → 未解析（不虚构）；0x0 → 空指针显式状态。上限：变量 30、evaluate 20 次/暂停、单次 5s；失败 → unknown。不透传任意表达式（用户/AI 均不可）、不执行可能副作用的表达式。
- **暂停代次（pauseSeq）**：每次 stopped 事件递增并随快照下发；前端所有按 DAP variablesReference 的缓存（展开变量/帧变量）以 (会话， 代次) 隔离，新代次即失效——修复旧引用在 continue 后可能失效/重分配的错误复用；变量变化对比也按 (帧: 代次) 隔离，递归同名变量不串扰。
- **帧变量端点**（白名单）：`GET /debug-sessions/{id}/frames/{frameId}/variables` 返回该帧 scopes+变量+指针图（携带 pauseSeq）；切帧明确重载，不跨帧复用。
- **cpp-memory-graph L1 组件**：React Flow 固定网格布局（按名排序定位，值变化不重排整图）；四态显式区分——已验证指向（实线箭头）/未解析地址（⚠ 徽标）/空指针/数据不可用（graph=null 横条）；运行中显示"历史快照非实时"横条（不冒充）；过期沿 P4.5a 的 stale 横幅；减少动态效果时关闭箭头动画。
- **Mentor 只读**：调试上下文增加已验证边/未解析指针摘要（AI 可解释、不可创建伪装节点；H0-H4 不变）。

**验证**：指针图纯单元 10（正则白名单/地址归一/精确匹配/上限/失败态）；API 集成 3（假 DAP evaluate 路径：图随快照/代次递增/帧间同名隔离）；真实 LLDB E2E 3（A-I：x=10→*p=20 后 x=20、p→x 已验证边、np 空指针、hp 堆未解析、递归两帧 n 取不同真实值、running 不伪造代次、停止零遗留）；前端 268（组件四态 5 + store 代次/帧 2）；三语言 E2E 33 复跑零回归。

**限制（如实记录）**：不解析指向堆对象/字符串字面量的指针（地址无具名变量匹配 → 未解析）；指针的指针（int**）同理除非目标是指针变量的地址且其地址可得；不做任意地址内存扫描/堆追踪/new-delete 生命周期（本轮范围外）。

## D39 · 多语言课程适配：版本化项目/课程模板 + C++ 指针课程闭环

**日期**：2026-10-11。

**决策**：
- **版本化模板注册表**（`projects/templates.py`）：ProjectTemplate{id, version, stack_keywords, course_id, language}；创建时按技术栈解析并落库 `projects.template_id`——项目语言身份显式记录，不靠文件扩展名猜测；课程按 course_id 解耦绑定（ts-markdown-v1 / **cpp-pointers-v1** / python-starter-v1 无课程）。已有 TS 试点课程原样保留。
- **课程种子安全**：文件只在路径不存在时写入（replan/重启永不覆盖用户代码，有回归测试）；任务种子幂等（已有任务跳过）；无课程模板（Python）→ 学习路线诚实为空。
- **C++ 知识图**：7 个 cpp.* 概念（variables/functions/addresses/stack-frames/pointers/dereference/references）独立成域，先修 DAG 校验无环无悬空；**不映射 js 概念**。种子改为按 id 增量（已有库无损升级）。
- **C++ 诊断**：10 道确定性选择题（值预测/&与*/指针关系/值传递 vs 引用/递归帧）；栈→域映射：C++→{cpp}（不混 JS 域）、Python→{engineering}（无 Python 题库时不造假诊断）。
- **任务模型扩展**：ProjectTask 新增 `hints`（L1-L4 渐进提示，与 Tutor H1-H4 对应）与 `viz_suggestion`（可视化教学建议）；Tutor 上下文/系统提示接入——**优先引导预测下一步状态再单步验证**，L4 仅在显式请求答案时放行（H4 门控不变）。
- **run 源集策略修订（D35 修订）**：入口 + 非测试且**不含 int main(** 的 TU——课程各任务/脚手架是独立程序（各带 main），链接进来只会重复符号或被未完成 TODO 拖垮；无 main 的实现单元照常参与链接。确定性内容启发式，与测试模式一致。
- **变化高亮修复**（memoryGraph/debugSnapshot）：键从"帧:代次"改为"**会话:帧**"——同帧值跨暂停代次比较（单步 x: 10→20 高亮），递归帧按帧 id 隔离，换会话重置；新增回归测试。

**验证**：后端 212 全过（新增：模板选择/C++ 课程种子/Python 空课程/replan 不覆盖/cpp 概念图/cpp 诊断选题/源集策略/跨代次高亮回归）；**课程 E2E 1 个**（真实全流程：创建→诊断→路线→Task1 真实测试+验收→Task2 LLDB p→x 已验证边+单步 x 10→20→Task3 迁移练习→7 概念 application 维证据+3 事件）；三语言 E2E 复跑零回归；PG 4；前端 270 全过。
