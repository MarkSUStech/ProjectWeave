# 进度记录

更新时间：2026-10-11（P4.2a 多文件 TypeScript 运行与跨文件测试，含语言无关执行架构）

## 已完成（经过验证）

### 前端视觉与开源组件重建（增量切片）

- [x] 统一深色设计 token、shadcn/Radix 基础控件与真实命令搜索；文件操作/快照恢复使用 Dialog，文件菜单使用 DropdownMenu，Tabs 支持方向键与面板关联。
- [x] Monaco 主题与只读 Diff（真实历史快照 / Tutor 返回的代码提案）；原文件保存、自动保存、运行、测试、教学证据与 Policy Gate 保留。保存后快照列表立即刷新；TS 种子 export 在单文件 Worker 中可真实执行，不承诺跨文件 import。Diff 关闭时先解除模型绑定再释放，3次浏览器开关复测无错误。
- [x] 初次重建使用 react-resizable-panels v4 + shadcn Resizable；现已由下述 Dockview 自由布局替换。
- [x] xterm + FitAddon 展示真实 Worker 输出；明确远程 Shell 未连接（P4）；React Flow + ELK 展示知识库真实先修图与掌握证据（17 节点 / 21 边本机验收）。
- [x] Motion 页面/模式/画布/折叠/思考状态动画；Motion Primitives Mentor 消息淡入；Magic UI 项目卡片 BlurFade；减少动态效果分支及公共组件交互单测。
- [x] `docs/UI_COMPONENTS.md` 记录实际使用、版本、来源、许可证（ELK 选择 EPL-2.0）、设计系统、性能限制和后续范围；完整许可证与源码获取声明随 public 发布。
- [x] 验证：`npm run verify`（32 文件 / 191 用例、typecheck、build）通过；后端 pytest 123 passed / 4 skipped（本轮未跑可选 PG）；1440×900 和 1920×1080 浏览器验收，真实编辑保存、Diff、输出、2 个种子测试、observe 变量、菜单/命令/布局与知识图。
- [x] 视觉细化：按用户确认的石墨灰＋柔紫统一首页/知识页/工作区、Monaco/xterm/知识图配色；扩大标题与代码字号、减少描边和整块高亮、统一 Mentor 输入框；场景采用中文标题并保留模板/交互详情。再次 `npm run verify` 191 用例全过；1440/1920 工作区与390px 首页无横向溢出、真实运行正常；未改后端。
- [ ] 架构/任务/状态机图、行内教学高亮、课程状态反馈动画、远程 Shell、大图性能优化仍为后续；WorkspaceAction 宿主应用确认已在 P3.4 切片接入；没有业务 mock 或伪造成功结果。

### 编辑器自由视图（增量切片）

- [x] DockviewReact 8.4.1（MIT）替换固定分栏；9 个真实面板独立拖动停靠、边缘拆分/中央标签合并、缩放、页内悬浮、隐藏/显示；菜单支持四边移动/指定合并，停靠组可专注。
- [x] 顶栏「视图」与命令搜索提供面板恢复和当前模式重置入口，全部隐藏后仍可恢复；按项目与模式自动保存/刷新恢复；只持久化布局结构，损坏回退并可见报错。
- [x] 实时布局锁定覆盖显隐/拖动/缩放/移动/合并/悬浮/专注/重置；稳定 portal 保持 Monaco 撤销与导师输入，防止焦点把顶栏滚出视口；保留文件 API、Worker、教学管线及 P3.4 补丁安全流程。
- [x] `npm run verify`：33 文件 / 201 用例、typecheck、build 全过；新增 6 个实际 Dockview 测试；浏览器中央合并、边缘拆分、缩放、锁定、切换模式与刷新恢复通过，Monaco 隐藏恢复后可撤销，导师输入保持，真实运行与 2 个种子测试通过。
- [x] 许可证随 public 发布；未引入 Enterprise，Radix 菜单提供键盘操作；悬浮在工作区内，不创建浏览器弹出窗口。下载体积与具体边界记录在 UI_COMPONENTS.md；本轮未改后端。

### 界面设置与外观自定义（增量切片）

- [x] 首页/知识页等全站顶栏与 IDE 顶栏增加「设置」，Ctrl/Cmd+K 提供同一入口；复用 Radix Dialog/Tabs/RadioGroup/Switch，支持键盘与焦点返回。
- [x] 3 种主题、自定义强调色（色板/颜色选择/十六进制输入）、界面相对字号、密度、圆角、背景纹理、卡片阴影与动效；默认保持石墨灰＋柔紫，开启动效仍尊重系统减少动态效果。
- [x] Monaco/只读 Diff 字体、字号、行高、换行、行号、缩略图、连字及 xterm 字号实时更新；主题切换不重建编辑器，保留撤销与真实运行输出。浅色终端日志使用可读前景色。
- [x] 工作区设置连接真实 9 面板显隐/布局锁定/当前模式恢复，所有布局调整遵守锁定；恢复外观不重置布局与 AI 偏好。
- [x] 版本化 `pw-appearance-v1` 仅在当前浏览器保存，经 zod 白名单/范围校验；损坏或存储不可用显式提示并回退；不提供任意 CSS 注入或跨设备同步。
- [x] 设置/实际 Dockview/公共 UI 定向测试 25 个通过；`npm run verify` typecheck、34 文件 / 212 用例、build 全过。浏览器主题、代码/终端选项、刷新恢复、Monaco 撤销、显隐与锁定、390px 首页与 120% 字号检查通过；体积与边界见 UI_COMPONENTS.md 本切片记录。
- [x] 修复首页整屏最小高度叠加 64px 顶栏造成的多余滚动：AppShell 固定为 100dvh，导航/顶栏保持，正文 flex 剩余高度独立滚动。1920×1080 单项目无滚动；展开长表单、390×844 手机正文可用键盘滚至页尾，document 不滚动；再次 `npm run verify` 212 用例/typecheck/build 全过。

### P0 基础

- [x] 设计文档基线确认与工程结构规划
- [x] 后端基础工程：FastAPI 应用工厂、CORS、lifespan 自动迁移、健康检查
- [x] projects 领域：ProjectSpec 核心字段建模（UUID/JSON 列/枚举/spec_version）
- [x] projects REST API：POST/GET 列表/GET 详情/PATCH/DELETE，camelCase 契约
- [x] Alembic 初始迁移（projects 表，SQLite + PostgreSQL 兼容写法）
- [x] 前端基础工程：Vite + React 19 + TS 严格模式 + Tailwind v4 令牌主题 + 路由
- [x] 前端 API 层：fetch 封装、ApiError 映射、zod 响应校验
- [x] 仪表盘页：项目列表、创建表单（校验/错误/空态）
- [x] 项目详情页：规格字段展示、里程碑空态（明确标注未实现）
- [x] 教学 IDE：Monaco（本地打包）、四种工作模式布局切换、布局锁定（有单测）
- [x] 开发文档体系：AGENTS.md、IMPLEMENTATION_PLAN、ARCHITECTURE、DECISIONS、PROGRESS、README

### P1 编程内核（进行中）

- [x] **P1.1 服务器端文件系统**：project_files 表（唯一约束 + 外键级联）、
      文件 API（列表/读/写 upsert/重命名/删除）、路径安全校验（拒绝绝对路径、
      `..`、反斜杠、空段、非法字符、Windows 保留名、首尾空格；上限 1MB/2000 文件）、
      新建项目自动种子 README.md + src/main.ts、删除项目级联清理文件
- [x] **P1.2 编辑器接入真实文件**：IDE 文件树（目录折叠、新建/重命名/删除）、
      打开文件加载服务器内容、脏状态指示、Ctrl+S / 保存按钮（PUT 持久化）、
      切换文件未保存确认、打开慢请求的代次保护；移除 P0 的 localStorage 草稿
- [x] **P1.4 浏览器内 JS 运行器 + 终端面板**：Blob module Worker 沙箱执行
      （console 流式捕获与序列化、5s 超时强杀、异常统一上报）、`.js` 直跑 /
      `.ts` 真编译器转译执行（TS5.9 懒加载 chunk，标注不做类型检查）/ 其他类型
      明确拒绝；终端面板真实输出（时间戳、级别着色、自动滚动、清空、500 条上限）；
      编辑器「▶ 运行」按钮 + Ctrl+Enter，运行草稿内容、拒绝并发
- [x] **P1.5 测试运行器 + 测试面板**：Worker 注入微型测试运行时
      （describe 嵌套前缀 / it / test / expect：toBe、toEqual 深比较、toBeTruthy、
      toBeFalsy、toContain、toThrow、`.not`），逐用例回传结果 + 汇总；
      `*.test.<js|ts>` 约定；套件编排拉取全部测试文件（当前文件草稿优先）、
      `.ts` 同样真转译；测试面板按文件分组展示用例/失败断言消息/合计/进度；
      测试文件时编辑器按钮语义切换「▶ 测试」；种子新增自包含示例测试
      `src/main.test.ts`（新项目开箱可跑）
- [x] **P1.3 代码快照 + codeVersion + 自动保存**：`code_snapshots` 表（覆盖前
      旧内容 + sha256，同内容跳过，每文件保留 50 份）；恢复前当前内容先入历史
      （任何路径不丢数据）；重命名历史跟随、删除连带清理（D15）；
      `GET /code-version` 实时计算项目内容指纹；IDE 左侧「历史」页签
      （列表/预览/恢复确认）；详情页显示 codeVersion；编辑器 2.5s 防抖自动保存
      （默认开启、autoSaveMs 可关，失败错误可见）
- [x] **P1.8 PostgreSQL 切换验证**：docker compose PG 16（宿主机 5433，避开本机
      5432 服务）；psycopg2-binary 正式启用；`test_postgres_compat.py` 兼容套件
      （默认 skip）：迁移重放、列类型断言（uuid/JSONB/timestamptz）、CRUD 冒烟、
      路径校验；真实服务冒烟通过（createdAt 带 Z 时区）；附带修复 alembic.ini
      path_separator（D16）
- [x] 修复：alembic.ini 中文注释在 zh-CN Windows（GBK locale）下导致启动失败，
      改为 ASCII 并记录（D13）；文档更正 venv 实际为 Python 3.13
### P2 教学闭环（进行中）

- [x] **P2.1 知识图谱种子 + 知识图 API + 浏览页**：`knowledge_concepts` 表
      （字符串主键如 js.closures、先修/目标/评估 JSONB、version，D17）；
      17 个确定性种子概念（样板课程：JS 10 / TS 2 / 浏览器 2 / 工程 3）；
      `validate_graph` DFS 校验无环/无悬空/无自引用；启动 lifespan 空表幂等种子；
      `GET /concepts`（domain 过滤）与 `GET /concepts/{id}`；
      前端 `/concepts` 知识图谱浏览页（域分组、先修徽标、展开目标/评估方式/示例），
      仪表盘入口
- [x] **P2.2 初始能力诊断**：`assessment_sessions`/`assessment_answers` 表；
      15 道确定性单选预测题（题库带版本）；选题规则（stack→域映射、概念拓扑
      深度+难度排序、每概念一题、≤8 题）；start 不下发答案、submit 确定性判定
      + 概念三档初判（likely-mastered/uncertain/likely-gap）落库；重复提交 409、
      缺题/多题/越界 422；前端 `/projects/:id/assessment` 诊断页（逐题作答、
      进度条、结果三档徽标 + 逐题回顾含正确答案）与详情页诊断卡片（最新摘要）；
      根治 autogenerate 迁移缺 Text import（mako 模板，D18 附带）
- [x] 验证（P2.1 轮）：SQLite 53 + PG 4 + 前端 106 用例、冒烟（启动种子 17 概念、重启幂等）全过
- [x] **P2.3 learner_mastery + 学习证据**：`learner_mastery`（owner+concept 唯一，
      四维 dimensions JSONB——**只写有证据的维度，其余保持缺失**）与
      `learning_evidence`（逐条证据）两表；确定性管线 record_evidence
      （校验→估计=通过率→置信度=min(0.9, 0.3+0.2n) 封顶，model_version=rule-v1）；
      证据类型→维度映射（prediction→understanding，coding→application 等）；
      诊断提交在 router 层编排写入（领域 service 不互相 import）；`GET /mastery`；
      知识图谱页叠加理解维掌握徽标（证据 <2 条显示"尚不确定"）
- [x] **P2.4 Curriculum Engine**：`project_tasks`（样板课程六任务，附录 B 的
      依赖/知识映射/交付物）与 `learning_plans`（版本化）两表；规则化规划器
      （任务拓扑排序含环检测、知识要求→先修闭包、掌握判定复用 D19 阈值：
      已掌握跳过带原因、未达标生成学习活动带原因、实践任务始终保留）；
      `GET /plans/{id}` 幂等生成 v1、`POST /plans/{id}/replan` 版本递增历史保留；
      前端详情页"学习路线"卡片（活动+原因、跳过折叠、版本、重新规划按钮）与
      里程碑任务图卡片（M1-M6 状态）；D20 记录规划器决策
- [x] **P2.7 学习事件信封**：`learning_events` 表（eventId 幂等键 + aggregateId/
      sequence 复合索引 + payload ≤4KB 只存摘要）；类型白名单六类（file-saved/
      plan-generated/plan-replanned/assessment-submitted/code-run/tests-run）；
      服务端事件在 router 编排层追加（确定性 eventId=uuid5 → 重放自动去重）；
      `POST /events` 批量上报（≤20 条）+ `GET /events` 过滤查询；前端
      eventTracker（满 5 条或 30s 批量 flush，失败保留队列=至少一次投递）上报
      code-run/tests-run；IDE"学习事件"页签真实化（类型徽标+摘要+序号+刷新）；
      D21 记录"非严格同事务 outbox"的取舍
- [x] **P2.5 Tutor Engine 骨架**：可插拔 LLM Provider（DeepSeek 真实接入：
      OpenAI 兼容 API、json_object 结构化输出、Token 用量记录、Key 走 .env
      不入库；Mock 仅测试；disabled 默认明确降级 503）；教学回合
      `POST /tutor/turns`：确定性上下文组装（路线活动/mastery/最近事件/任务/
      规格，只读各域 models）→ 防注入提示词（CONTEXT 分隔声明）→ LLM 结构化
      TeachingDecision → **确定性 Policy Gate**（intent/hintLevel/message/概念数
      校验，不合规降级为安全动作并记原因）→ teaching_decisions 落库 +
      tutor-turn 事件；`GET /tutor/decisions` 历史；前端 AI Mentor 面板真实化
      （对话气泡 + intent/H 级徽标 + 目标概念 + token + 降级标记 + 503 配置
      指引）；D22 记录决策；测试环境强制 AI disabled 防真实 Key 泄入
- [x] **P2.6 H4 门控 + AI 介入三模式**：`user_settings` 表（quiet/adaptive/
      guided，默认 adaptive，GET/PATCH /settings）；H4 双防线（提示词自律 +
      Gate 强制"hintLevel=4 未请求→降级 H1"），`requestAnswerLevel` 显式勾选，
      事件记录 answerRequested；主动建议 `GET /tutor/suggestions`（拉取式：
      quiet 不调 LLM 直接拒绝；adaptive/guided 需最近连续 ≥3 次运行失败事件；
      同项目 60s 冷却，trigger=auto 落库 + 事件）；前端顶栏三模式切换
      （PATCH 持久、失败回滚）、失败后非阻塞建议条（可忽略）、Mentor 面板
      H4 勾选框；D23 记录决策
### P3 可视化与工作台（进行中）

- [x] **仓库版本控制**：git init（main）、首次提交全部代码（.env/Key 扫描
      确认未入库，唯一命中为测试桩假 Key sk-test）、推送
      https://github.com/MarkSUStech/ProjectWeave（README 冲突保留本地版）
- [x] **P3.1 Visual Engine 地基**：TeachingScene Schema（zod：sourceType 三分类
      + 来源标签、dataBinding、components、allowedInteractions）；组件注册表
      （元数据 + 重复注册抛错）；SceneRenderer（schema 校验 + 查表渲染，
      未注册/不合法显式错误面板）；**首个 L1 组件 console-timeline**（真实
      运行输出时间线：相对毫秒 + 级别色 + 本地点击详情，零 LLM）；IDE"调试"
      与"实验"画布从占位替换为真实场景（runtime.console-timeline.v1，
      无数据诚实空态）；D24 记录决策
- [x] 验证（P2.6 轮）：SQLite 111 + PG 4 + 前端 140 用例、真实 DeepSeek 冒烟
      （H4 双防线：无请求 H2 / 请求后 H3）全过
- [x] **P3.2 变量状态组件 + L2 组合场景**：Worker 注入声明式观察 API
      `observe(name, value)`（值复用运行器序列化，`observed` 消息流式回传，
      D25）；runner onObserved 转发；runStore observations（上限 200）；
      L1 组件 `variables-state`（按变量名分组：当前值/变化次数/展开历史，
      本地交互零 LLM，空态引导 observe 用法）；场景
      `runtime.variables-state.v1`（实验模式）与 **L2 组合场景
      `runtime.debug-panel.v1`**（调试模式：时间线+变量状态纵向平分，
      §9.1 组合协议）；SceneRenderer 多组件布局
- [x] 验证（P3.1 轮）：前端 150 + dev 冒烟全过；git 推送 GitHub 成功
- [x] **P3.3 运行数据版本绑定（§14.3）**：`lib/fingerprint.ts` 执行内容指纹
      （SHA-256(path\0content)，无 subtle 环境降级 FNV-1a）；runStore `trace`
      （traceId/指纹/路径/时间），code-run 与 tests-run 均在运行时写入；
      学习事件携带 traceId；SceneRenderer 头部显示运行时间 + 指纹缩写；
      IdePage 持续比对草稿指纹与单文件运行指纹 → **画布"数据已过期"横幅
      （旧执行数据不冒充当前）**；D26 记录服务器 codeVersion（已保存）与
      执行指纹（草稿）的两层语义
- [x] 验证（P3.2 轮）：前端 155 + 后端 111 全过；推送 GitHub（05b2319）
- [x] 验证：前端 vitest 165 个用例全过（新增 10：指纹确定性/多文件顺序参与/
      缩写、trace 写入与 traceId 返回/新运行新 trace/不支持类型不写 trace、
      过期横幅与 trace 头部、旧用例适配新返回形状）；typecheck/build 通过；
      后端 111+PG4 零改动无回归
- [x] **P3.5 阶段验收流程**：`POST /projects/{id}/tasks/{taskId}/evaluate`
      ——前端「测试验收」按钮跑浏览器套件→提交结果（含 traceId）→后端
      确定性 rubric（suite-green-v1：全绿→done，否则 needs-fix）+ 依赖闸门
      （未完成 422）；**coding 证据 → application 维首次真实数据**（失败也
      是证据）；task-evaluated 事件；详情页任务徽标含"需修正"；D27 记录
      决策（任务级测试绑定待课程内容制作）
- [x] **P3.4 WorkspaceAction 权限等级**：后端 TeachingDecision 增加
      workspace_actions（Gate 分级 A0/A1/A2 + payload 校验 + 数量封顶 +
      **A2 与 H4 门控联动**：补丁未随 requestAnswerLevel 一律移除）；
      前端 `lib/workspace/executor.ts` 确定性执行链（A0 通知 / **A1 布局
      锁定联防 [AT-05] + 撤销栈 [撤销亦受锁定约束]** / A2 确认队列→
      仅写草稿不自动保存）；`WorkspaceNoticeStrip` 通知条组件（新文件）；
      每动作上报 workspace-action 审计事件
- [x] **P3.4 端到端集成（本轮）**：MentorPanel 收到新决策即执行
      applyWorkspaceActions（历史决策不重放）；差异弹窗（并行 Agent 的
      CodeDiff）加"应用到编辑器草稿/拒绝"（confirmPatchAction 按动作确认）；
      IdePage 挂载 WorkspaceNoticeStrip + **脏草稿守卫**（目标文件未打开或
      有未保存更改时拒绝应用，防覆盖用户输入）；**自动保存承诺对齐**——
      应用文案改为"写入草稿并随自动保存保存，应用前内容进入历史快照"
      （与 2.5s 防抖实际行为一致，D28 追记）；场景 A-E 测试覆盖
- [x] 验证（P3.5 轮）：SQLite 117 + PG 4 + 前端 170 全过；推送（6b4b78f）
- [x] 验证：SQLite pytest 123 个用例全过（workspace 6：分级分类/A2 需答案级
      请求/五类非法移除/非列表与封顶/端到端携带动作与原因落库/H4 联动
      [未请求降级+动作移除，请求后消息与 A2 均放行]）；PG 4 全过；前端
      vitest 195 个全过（workspace 10 + mentorPanel 场景 A-E 5：
      A 未锁定切换+撤销恢复/B 锁定拒绝布局不变/C 未确认源码不变/
      D 差异弹窗确认后才 applyPatch/拒绝清队列；executor 测试适配
      PatchApplyResult 签名）；npm run verify 全过；后端 API 契约零改动

### P4 任务驱动教学闭环（进行中）

- [x] **P4.1 试点课程：TypeScript Markdown 解析器**（三个任务由简到繁，
      全部浏览器 Worker 单文件执行，无 import）
  - **后端模型扩展**：ProjectTask 新增 test_files/starter_files/
    acceptance_criteria 三列（迁移 3843e18441fe，SQLite server_default
    兼容）；试点课程模板 pilot_course.py（确定性内容，含逐任务初始
    代码与测试文件定义）
  - **种子**：项目创建时自动种子 3 个任务 + 6 个文件（初始代码 3 + 测试
    3）到 project_files
  - **任务级评估（rubric v2 task-scoped）**：evaluate 只统计任务绑定的
    test_files（越界文件忽略+告警）；**防伪守卫**：无绑定测试/空文件列表/
    零断言 → needs-fix 不判通过；**practice 信任级**——客户端自报结果
    始终标记 practice，不授予正式能力认证（服务端可信执行未建成前，
    界面与文档如实标注）；学习证据按任务 requiredConcepts 写 coding/
    application 维；task-evaluated 事件含 trustLevel + scopedFiles
  - **Tutor 任务感知**：build_context 接受前端 extras（currentTaskId/
    currentCode[截断 2000 字符]/recentRunResult），服务端补充最近 3 条
    求助记录（helpHistory）；MentorPanel 发送时携带——最小必要上下文，
    不发整个项目
  - **前端 TaskPanel**（IDE 左侧"任务"页签）：任务列表（进度/徽标）、
    当前任务详情（说明/交付目标/验收条件/涉及知识点/测试文件）、
    「运行任务测试并验收」按钮（只跑任务绑定的测试文件）→ 逐用例
    反馈（✔/✘ + 失败消息）→ 验收结果卡（通过/需修正 + trustLevel +
    warnings + 证据概念）→ 下一步任务引导按钮
  - **runTestSuite 增强**：返回值增加逐文件 files 结果（P4.1 任务级
    评估需要），不改变原有 totalXxx 字段（向后兼容）
- [x] 验证：后端 pytest 126 个全过（任务评估 9：试点课程种子/任务级全绿
  done+practice/越界忽略/失败 needs-fix/零断言不通过/无绑定测试/
  依赖闸门/证据 application 维/事件含 trustLevel）；PG 4 全过；前端
  vitest 211 个全过（1 失败为并行 Agent 未跟踪的 appearance 测试，
  非本轮改动）；typecheck/build 全过；**真实端到端冒烟**通过（创建项目
  → 3 任务+6 文件自动种子 → 测试文件含 describe/it → 全绿 done[practice] →
  失败 needs-fix → 越界警告 → js.strings application 维 estimate=0.67 →
  事件 trustLevel=practice）

- [x] **P4.2a 多文件 TypeScript 运行 + 跨文件测试 + 语言无关执行架构**（D30）
  - **执行层**（`lib/execution/`）：语言无关契约（ExecutionRequest/Result/
    Diagnostic/TrustLevel）+ LanguageProfile（TS/Python/C++ 注册表，Python/
    C++ supportedBackends=[] 不伪造）+ ExecutionBackend 接口 + registry
    路由（UnsupportedExecutionError 处理不支持语言）
  - **TypeScript BrowserBackend**：单文件 ts-compiler 转译 / 多文件
    esbuild-wasm 打包 → Worker 沙箱；maxTrustLevel=practice
  - **esbuild-wasm 多文件打包**（`runner/bundler.ts`）：VFS 插件 + 路径
    规范化（禁越界）+ 扩展名补全 + npm 包拒绝 + 编译计时；WASM 懒加载
    （~14MB，部署 public/esbuild.wasm，首次运行后复用）
  - **Remote Backend 占位**：remote-pytest/remote-cmake 接口已定义，
    canHandle=false 不被选中；实现时改为 true 并实现 execute()
  - **试点课程跨文件测试**：headings.test.ts `import { parseHeadings }
    from './headings'`；transform.test.ts 导入三个模块；transform.ts
    起始代码 import 前两任务实现（不复制）；**单文件模式兼容**（无 VFS
    时 prepareScript 始终走单文件转译，旧调用零破坏）
  - **IdePage 接入**：runTaskTests 通过 execute() 统一入口 → 构建 VFS →
    路由到 browser-worker 后端 → 跨文件 import 解析 → 逐用例反馈
- [x] 验证：前端 vitest **227 全过**（新增 execution 15：Profile 注册/
  路由/多文件执行[验收 A]/模块不存在[D]/npm 包[H]/跨文件测试[B/E]；
  单文件 runFile 测试零回归——export 语句无 VFS 时正确单文件转译）；
  后端 pytest **126 全过** + PG 4 全过；typecheck/build 全过；**E2E 冒烟**
  全通（创建项目 → 生成计划种子 6 个 parser 文件 → headings.test.ts 含
  import → transform.test.ts 3 个 import → transform.ts import 前两模块
  → 任务评估 done+practice → 学习证据 application 维）

### P1 验证汇总

- [x] 验证（P1.3 轮）：后端 43 + 前端 98 用例、typecheck/build、快照恢复冒烟全过
- [x] 验证：SQLite pytest 43 个用例全过（PG 套件默认 skip 4 个）；PG 兼容套件
      4 个用例全过（容器 PG 16）；真实服务冒烟（uvicorn+PG）通过

## 未实现（明确标注，禁止伪装）

- [ ] 任务级测试绑定（task.tests[] 与 per-task rubric）— 课程内容制作阶段
- [ ] H4 之后的独立性迁移验证（验收证据已可引用，验证流程待设计）— P3.5+
- [ ] 重规划将 application 维纳入掌握判定（当前仅 understanding）— P2.4 扩展
- [ ] trace 落库（execution_traces 表）与服务器 codeVersion 双向关联 — 远程沙箱阶段
- [ ] 调用栈标准组件（需真实调试器/插桩，不假装——D25 记录取舍）— P3.2+/P4
- [ ] Guided 的阶段性检查/主动推进教学（需会话状态与更丰富证据）— P3+
- [ ] 推送式建议（WebSocket）与忽略/暂停按钮的持久化 — P1.6+/P3
- [ ] Tutor 只读工具调用（get_relevant_code/diagnostics 等）与流式输出 — P2.5+/P3
- [ ] 掌握变化自动触发重规划（事件已可查询，消费方待接入）— P2.4+/Tutor
- [ ] 严格同事务 outbox（当前服务端事件为业务 commit 后独立事务，崩溃窗口可能丢事件，D21）— 随 P1.7 事务边界重构
- [ ] 前端 pagehide 兜底 flush（刷新可能丢失未满批事件，已知限制，D21）
- [ ] 任务状态流转与验收（tasks/{id}/evaluate + rubric，当前任务均为 pending）— P3.5
- [ ] 重规划 diff 展示（当前仅保留历史版本）— P2.4+
- [ ] application / debugging / independence 维度的估计（需编码任务、测试运行、迁移任务等证据类型接入）— P2.4+/P3
- [ ] 解释题 / 小编码任务的诊断评分（依赖 Tutor Engine 与运行数据）— P2.5+
- [ ] 自适应诊断（根据作答追问或停止，当前为固定 ≤8 题）— P2.3+ 评估
- [ ] Curriculum Engine（任务-知识双图规划、LearningPlan）— P2.4
- [ ] Tutor Engine（LLM Adapter、TeachingDecision、Policy Gate、渐进提示、三模式）— P2.5/2.6
- [ ] 学习事件信封与 outbox — P2.7
- [ ] 编辑器多文件标签页（当前单文件打开 + 切换确认）— P1
- [ ] codeVersion 与执行 trace / 教学场景的版本绑定（消费方在 P3 可视化）— P3
- [ ] 测试结果持久化 / 学习证据上报（当前测试结果仅内存展示）— P2.7
- [ ] 任务验收流程（rubric + /tasks/{id}/evaluate）— P3.5
- [ ] WebSocket 会话事件流 — P1.6
- [ ] 身份认证与多用户（owner_id 占位 dev-user，**待用户确认方案**）— P1.7
- [ ] 运行器/测试的 stdin 输入、多文件 import（Worker 单文件模式）、.tsx JSX — P1+ 按需评估
- [ ] 远程隔离执行沙箱（真正的网络/资源限制，当前浏览器 Worker 为便利级隔离）— P4/14.2
- [ ] Visual Interaction Engine（Scene Schema、组件注册表、标准组件）— P3.1-3.3
- [ ] WorkspaceAction 权限等级与撤销栈 — P3.4
- [ ] GitHub 导入、REA、导出、可观测性 — P4+/V1.1+

## 已知问题与债务

- ~~SQLite 下时间戳序列化无时区后缀~~（已验证：PG 上为 ISO 带 Z，兼容套件覆盖，D16）。
- ~~仓库尚未 git init~~（已推送 GitHub：MarkSUStech/ProjectWeave，main 分支）。
- PG 兼容套件默认 skip，需手动带 `PW_TEST_DATABASE_URL` 运行；接入 CI 后可强制执行。
- 本机开发环境注意：5432 与 8000 常被本机服务占用——PG 容器固定 5433，冒烟请用空闲端口。
- 前后端契约手工镜像（Pydantic ↔ zod），改字段需双侧同步；考虑 openapi-typescript 代码生成（D4）。
- 仓库尚未 git init（等待用户确认初始化与远端策略）。
- Monaco 使 dist 约 14MB；TS 转译器懒加载 chunk 约 3.3MB（仅首次运行 .ts 时下载）；后续可继续拆 chunk。
- 文件内容内联存 DB（1MB 上限）；快照/对象存储在 P1.3 引入（D9）。
- 文件重命名/删除与快照恢复已使用 Radix Dialog；切换文件未保存确认仍沿用原 hook 的浏览器确认。
- 浏览器 Worker 隔离为便利级（无 DOM/应用状态访问，但同源 fetch 理论可行）；真实网络隔离待远程沙箱（D11）。
- 运行器/测试尚无 stdin；多文件 import 不支持（Worker 单文件模式，种子示例已自包含并注明）；`.tsx` 不支持运行。
- 自研断言 API 是 jest 子集（toBe/toEqual/toBeTruthy/toBeFalsy/toContain/toThrow/.not），不承诺语法全集兼容（D14）。
- 快照内联存 DB（每文件 50 份 × 1MB 上限）；多用户/大项目场景再评估内容寻址 + 对象存储（D15）。
- 自动保存固定 2.5s 防抖且默认开启（代码级可关）；设置面板提供开关属后续 UI 工作。
