# 进度记录

更新时间：2026-10-12（P7.3 学生学习生命周期，D43）

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

### P4.2b 远程执行沙箱与 Python 支持（D32/D33）

- [x] **统一远程执行协议**（语言无关，D32）：`POST /executions`（202）→
      `GET /executions/{id}?afterSeq=`（增量事件轮询，SSE 预留同一语义）→
      `POST /executions/{id}/cancel`（幂等）；状态机
      queued→preparing→running→completed|failed|timed-out|cancelled；
      completed=执行跑完（退出码/断言失败是业务结果）、failed=基础设施失败；
      phases 通用阶段记录（C++ build+run 复用同一形状）
- [x] **SandboxManager 最小实现**（Docker 一次性容器）：network none、
      read-only 根 + noexec tmpfs（uid 10001 属主）、非 root、cap-drop ALL、
      no-new-privileges、memory/cpu/pids 限额、stdin gzip-tar 注入（不挂
      宿主目录）、pw.sandbox 标签追踪、启动后台清理 + 用后即毁（超时/取消
      kill 整个容器并 rm）；gVisor/微 VM 同协议预留；普通 Docker 不是
      恶意多租户可靠边界的诚实声明（backend/sandbox/README.md）
- [x] **Python Profile + RemotePythonBackend + PythonRunner**（D33）：
      CPython 3.12-slim + pytest 预装镜像（backend/sandbox/python/Dockerfile，
      非 root、无密钥）；driver 随执行注入（run 子进程 + pytest Recorder
      插件逐用例 file/line/失败消息 + 看门狗）；traceback 确定性解析映射
      文件行号（归一化容器绝对路径）；结果经 stdout 标记行回传；
      `__pw` 保留命名空间防覆盖；语言差异全部封装在 LanguageRunner，
      公共执行服务零语言逻辑
- [x] **教学系统集成**：traceback→诊断（文件:行号，Mentor 可读）；
      测试结果进 TaskPanel/测试面板；evaluate 契约增加 source
      (browser/remote) + executionId 溯源；trace 扩展 executionId/backend；
      `execution-finished` 服务端事件（幂等）；**信任级固定 practice**
      （服务端执行 ≠ 正式认证，P5 再建可信快照）
- [x] **前端接入**：pythonProfile→remote-pytest 真实路由；remotePython
      后端（400ms 轮询 + 增量事件流式回传 + 取消 + 503/超时明确报错）；
      runRemote 终端胶水（状态行/流式输出/trace/并发拒绝）；
      IdePage 运行按钮按语言分发（TS 浏览器 / Python 远程）；
      canRunPath/isAnyTestPath（.py 可执行、test_*.py 识别为测试）；
      终端 stdin 输入框 + 远程执行"停止"按钮；测试面板 Python 路由
- [x] **安全与清理验证**：路径校验拒绝绝对/`..`/反斜杠/盘符/保留名/
      `__pw`；文件数/总字节/stdin/超时/输出全上限；环境变量白名单；
      超时/取消后 `docker ps -a --filter label=pw.sandbox=1` 零遗留
- [x] 验证：后端 pytest **162 全过**（新增 38：FakeSandbox 注入的 API
      生命周期/校验/上限/503/取消/增量事件/截断 + python_runner 纯单元
      13）+ PG 4 全过；**Docker E2E 11 个全过**（PW_SANDBOX_E2E=1 选入：
      验收 A hello/B import/C stdin/D pytest 成/E 断言行号定位/收集错误/
      F 无限循环超时清理/G 宿主文件+网络封锁+只读根/J 取消零遗留）；
      前端 vitest **246 全过**（新增 19：executions API/远程后端映射/
      runRemote 胶水/路由更新）+ typecheck/build 全过；真实 uvicorn 冒烟
      （import+stdin 912ms、取消、容器清理）通过；TS 原路径零回归

### P4.2c C++20 多文件编译与执行（D34/D35）

- [x] **沙箱工作区策略（D34）**：`SandboxSpec.exec_workspace`/`tmpfs_size_mb`
      服务端声明（客户端不可触达）；C++ 挂 exec tmpfs（256MB）执行编译产物，
      Python 保持 noexec 不变；其余隔离（禁网/只读根/非 root/cap-drop/
      no-new-privileges/资源限额/标签清理）对 C++ 完全一致（E2E 实测）；
      方案比较（语言专属 exec tmpfs vs build/run 两容器）记录于 ADR
- [x] **C++ 工具链镜像**：`backend/sandbox/cpp/Dockerfile`——Debian
      bookworm 固定版本（clang 15.0.6 / cmake 3.25.1 / ninja 1.11.1 /
      libstdc++ 12 + python3 仅驱动运行时），非 root、无密钥
- [x] **CppRunner + cpp_driver**（遵守 LanguageRunner 协议，公共服务零改动）：
      - 源集策略（确定性纯函数）：run = 入口 + 全部非测试翻译单元（多 main
        交链接器报真实错误，不拼接源文件）；test = 测试 + 非测试且内容启发式
        排除含 `int main(` 的源（避免多 main 链接冲突）
      - 编译参数服务端固定 `-std=c++20 -O0 -g -Wall -Wextra`（不拼接用户命令）
      - 诊断解析：clang 行诊断（file:line:col）+ 链接符号缺失（GNU ld/lld
        双格式，/sandbox/work 前缀归一化）→ source='build'；运行崩溃信号
        （SIGSEGV 等）→ source='runtime'；编译失败 run 阶段显式 skipped
      - CMake 最小支持：CMakeLists 存在 → cmake -G Ninja 配置+构建包含入口
        源文件的目标（解析 add_executable，回退目标名=入口去扩展名约定）；
        配置/编译/链接/运行失败经 phases 与诊断区分；test 模式忽略 CMake
        走直接编译（不假装支持 CTest 全量语义）
      - 测试约定：每测试文件=独立可执行程序；通过=退出 0 且有输出；干净退出
        非零=failed（断言失败）；崩溃/超时/编译失败/空输出=error（空测试
        不判通过）；测试元数据（名称/退出码/时长/失败信息/文件）完整
      - 产物以继承 stdout/stderr 流式运行（终端实时可见、取消即时生效）
- [x] **前端**：远程传输层抽为 `remoteShared.ts`（create/poll/cancel/映射 +
      createRemoteBackend 工厂，诊断按 build/runtime/test 分类映射）；
      remotePython 薄封装 + 新 remoteCpp（一行工厂调用）；cppProfile→
      remote-cpp；运行/测试按 Profile 自动语言分发（canRunPath/
      isRemoteExecutable 泛化）；Monaco 补 .cpp/.hpp 语言映射；
      **Mentor recentRunResult 改为最近运行的真实终端摘要**（编译诊断/
      traceback 语言无关可见，H0-H4 机制不变，区分编译/链接/运行/测试/超时）
- [x] 验证：后端 pytest **180 全过**（新增 cpp_runner 纯单元 18：诊断双格式
      解析/源集选择/CMake 目标解析/映射/buildSpec exec 声明）；**C++ Docker
      E2E 13 个全过**（A 单文件/B 多翻译单元/C 缺头文件诊断 file:line:col/
      D 链接错误符号/D 运行崩溃 SIGSEGV/E stdin/F 无限循环超时清理零遗留/
      G 测试成败+空测试+编译失败/H CMake+Ninja 多文件+配置失败区分/I 编译
      失败不报成功[K 复测]）；Python E2E 11 复跑全过（无回归）；PG 4 全过；
      前端 **247 全过**（路由/胶水测试更新：C++ 路由 remote-cpp）+ typecheck/
      build 全过；TS 浏览器路径零回归

### P4.5a C++ 交互式调试系统（D36/D37）

- [x] **阶段 A 可行性验证（先行，真实容器实测）**：ptrace 默认 seccomp 已允许
  （非 root 10001 可调试自有子进程）；唯一阻塞 personality(禁ASLR) 按值拦截 →
  **调试专用 seccomp**（上游 moby v28.0.1 默认 profile 仅放开 personality 参数
  限制，其余一字不动）；disableASLR 参数无效、绝不 --privileged/unconfined、
  普通执行沙箱零改动；受限 flag 下完整 DAP 脚本全过
- [x] **DebugSession 基础设施**：debug_sessions 表 + 状态机
  （creating→building→configuring→running⇄paused→terminated + end_reason）；
  DapClient（Content-Length 帧、按 seq 唤醒、事件非阻塞入队）；每会话串行
  线程独占 DAP 请求（防死锁）；长生命周期容器（sleep infinity + docker exec
  通道）；看门狗（空闲 600s/硬 1800s，独立线程）+ 启动清理 + DAP 死亡回收；
  快照抓取空栈重试（不冒充）；指令白名单（无任意 LLDB 命令透传）
- [x] **C++ LLDB DAP 适配**：trixie 调试镜像（clang 19 + lldb-dap 19.1.7 +
  cmake/ninja，bookworm lldb 14 无 lldb-dap 故升基线）；调试构建 -O0 -g 复用
  CppRunner 源集策略与编译诊断解析（编译失败不启动调试器，run 阶段不执行）；
  断点经项目路径→容器路径映射，栈帧/位置归一化回项目相对路径
- [x] **前端调试工作台**：Monaco glyph margin 断点 + 暂停行装饰（增量刷新不
  重建编辑器）；调试工具栏；DebugPanel（调用栈跳转/变量懒加载/线程/断点
  验证）；暂停自动定位文件；stdin/停止按钮复用现有终端面板模式
- [x] **TeachingScene 集成**：L1 组件 debug-snapshot（数据绑定 debug:latest，
  标注真实 lldb-dap 来源）+ 场景 runtime.debug-snapshot.v1（执行位置/可选中
  调用栈/变量值与变化标记）；调试会话期间画布自动切换；**源码过期提示**
  （会话指纹 vs 草稿指纹，验收 K）；Mentor 暂停时读取真实快照摘要（只读，
  AI 不控制调试器，H0-H4 不变）
- [x] 验证：后端 **194 全过**（新增 20：调试 API 单测 14[假 lldb-dap 子进程
  真实 DAP 帧协议] + runner 归一化等）+ **调试 Docker E2E 6 个**（验收 A-H：
  指定行暂停/单步行更新/真实局部变量/递归多帧/多文件断点[main.cpp+math.cpp
  各停一次]/编译失败不启动调试器/停止零遗留/空闲超时回收）+ Python E2E 11 +
  C++ E2E 13 复跑零回归 + PG 4；前端 **261 全过**（新增 14）+ typecheck/build；
  真实 uvicorn 冒烟（跨文件断点、continue 跨文件跳转、真实变量 x=40/y=0、
  栈帧 add←main、停止零遗留）通过

### P4.5b.1 C++ 真实内存与指针关系可视化（D38）

- [x] **数据一致性修复（先行）**：暂停代次 pauseSeq（每次 stopped 递增，
      随快照下发）；前端所有按 variablesReference 的缓存以（会话，代次）
      隔离——修复 continue 后 DAP 引用失效/重分配的错误复用；变量变化
      对比按（帧:代次）隔离，递归同名变量不串扰；新帧变量端点返回携带
      pauseSeq，切帧明确重载
- [x] **真实指针数据（探针先行）**：实测 lldb-dap 19 的 memoryReference
      不存在、evaluate "&var" 可靠（地址与指针 value 精确一致）→ 服务端
      白名单策略（evaluateName 正则、变量 30/求值 20 次/单次 5s 上限、
      失败 unknown）；**只有地址精确相等才画已验证边**；堆指针未解析、
      空指针显式状态，绝不虚构连线
- [x] **cpp-memory-graph L1 组件**：React Flow 固定网格稳定布局（值变化
      不重排）；四态区分（已验证/未解析/空指针/数据不可用）+ 运行中
      "历史快照非实时"横幅 + 过期提示 + 减少动效支持；场景
      runtime.cpp-memory-graph.v1，调试会话期间画布自动切换
- [x] **同步与清理**：continue/单步/跳帧后按新代次刷新；程序运行不冒充
      实时；会话结束释放全部代次缓存（store 测试覆盖）
- [x] **Mentor 只读图摘要**：已验证边 + 未解析指针进调试上下文（AI 不
      能创建伪装节点；H0-H4 不变）
- [x] 验证：后端 **207 全过**（新增 13：指针图纯单元 10 + API 集成 3）；
      **真实 LLDB 内存 E2E 3 个**（验收 A-I）；三语言 E2E 33 复跑零回归；
      PG 4；前端 **268 全过**（新增 7）+ typecheck/build；零遗留容器

### P5.1 多语言课程适配与 C++ 指针教学实验（D39）

- [x] **语言感知项目初始化**：版本化 ProjectTemplate 注册表（cpp-pointers-v1 /
      python-starter-v1 / ts-markdown-v1），创建时落库 template_id（不靠扩展名
      猜语言）；C++ 项目自动获得《理解 C++ 指针》课程，Python 项目获得正确
      脚手架 + 空学习路线（不展示 TS 课程）；课程文件种子只在路径不存在时
      写入——**replan 永不覆盖用户代码**（回归测试）
- [x] **C++ 知识图谱**：cpp.{variables,functions,addresses,stack-frames,
      pointers,dereference,references} 7 概念（独立域不映射 JS；DAG 校验
      无环无悬空）；概念种子改按 id 增量（已有库无损获得新域）
- [x] **C++ 初始诊断**：10 道确定性题（值预测/& 与 */指针关系/值传递 vs
      引用传递/递归帧）；栈→域映射 C++→{cpp}（不混 JS）、Python→通用工程
- [x] **《理解 C++ 指针》课程 3 任务**：变量与地址 → 指针与解引用 → 函数
      参数与间接修改（含独立迁移练习 my_swap，不含完整解答）；每任务带
      初始代码/测试/验收条件/hints（L1-L4 渐进提示）/可视化教学建议/
      证据概念；验收全部真实编译执行（沙箱），调试环节真实 LLDB + 内存图
- [x] **Tutor 任务感知增强**：上下文携带任务 hints 与 vizSuggestion；系统
      提示要求优先引导**预测**再单步验证、引导学生用真实调试器观察；
      L4/H4 门控不变
- [x] **修复**：run 源集策略排除其他独立程序 TU（含 int main 的任务文件
      不再拖垮入口编译/重复 main）；内存图变化高亮跨暂停代次比较（键改
      会话:帧；递归帧隔离保持），debugSnapshot 同步修复 + 回归测试
- [x] 验证：后端 **212 全过**（新增 15：模板/课程/概念/诊断/源集/高亮）；
      **C++ 课程 E2E 1 个全流程**（创建→诊断→路线→3 任务真实验收→LLDB
      p→x 已验证边→单步 x 10→20→迁移练习→7 概念 application 证据+3 事件，
      真实 Docker 沙箱）；三语言 E2E 复跑零回归；PG 4；前端 **270 全过** +
      typecheck/build；`docs/CPP_TRIAL_GUIDE.md` 试用指南

### P6 AI Teaching Agent（D40）

- [x] **Agent Runtime**（`app/agents/`）：后端控制多轮循环（LLM 提议 →
      白名单执行 → 结果回填 → 续轮/收尾）；预算强制（轮 4/调用 8/Token
      12k）；工具失败可恢复；耗尽安全收尾；完整调用轨迹
- [x] **6 个只读工具**：项目文件列表/读文件（截断）/当前任务/真实诊断
      （编译 file:line:col、运行 stderr、失败测试）/掌握状态/调试快照
      （含已验证指针边）——全部复用已有业务；ToolContext 服务端注入
      project_id，路径穿越与跨项目在 DB 行级即被拒绝
- [x] **Provider 升级**：chat() 不变；chat_with_tools() 用 DeepSeek 原生
      function calling（含完整 OpenAI 协议消息回填）；Mock 支持脚本化多轮
- [x] **Tutor 接入**：能力检测分支（不支持工具的 Provider 走原路径，
      零破坏）；决策照常过 Policy Gate（H4/A2 门控实测不变）；轨迹落库
      teaching_decisions（tool_calls/agent_rounds 列 + 迁移）
- [x] **前端轨迹**：MentorPanel 显示真实工具调用记录（✓/✗ + 参数 +
      耗时；数据来自后端，无模拟动画）
- [x] 验证：后端 **232 全过**（+20 Agent 专项：单次/连续/按结果决策/
      坏参/穿越/跨项目/失败恢复/轮数/调用/Token 预算/未知工具/H4 门控/
      A2 门控/轨迹/降级兼容）；**真实 DeepSeek E2E** 通过（Agent 主动
      取诊断+读文件，回复引用真实行号与真实错误，H1 先预测提示）；
      前端 **271 全过** + typecheck/build

### P7.1 Course Architect Agent + P6 稳定性（D41）

- [x] **P6 修复（先行）**：结构化截断（工具结果永远合法 JSON）；多 Agent
      注册表（tutor/architect 实例隔离 + 幂等）；执行超时/异常记录；
      DeepSeek max_tokens（长蓝图不再截断）
- [x] **course_generation 域**：GitHub Adapter（SHA 锚定/限额/二进制
      过滤/LICENSE 人工审查/raw+API 双通道）；Repository Analyzer Agent
      （7 个绑定快照的 architect 工具 + P6 Runtime + confirmed/inferred/
      unknown 证据分级 + 分层分析）；Scoper+Generator（Rebuild Track +
      知识图谱优先 + 候选概念不污染）；确定性 Validator（11 项：DAG/
      证据回溯/测试声明/结构底线…；error 阻断发布 + ≤2 修复轮）；
      发布（draft→published，不标记为已验证可运行课程）
- [x] **后台流水线 + API**：状态落库可轮询（进度/阶段/错误/中间产物）；
      6 端点（create/get/analysis/blueprint/validate/retry/publish）
- [x] **前端**：/courses/new 生成页（URL 输入/进度条/分析摘要含证据
      分级徽标/里程碑/任务列表点击详情/来源证据/验证问题/发布按钮）；
      全部数据来自真实后端记录
- [x] 验证：后端 **261 全过**（+25 课程生成专项）；前端 **274 全过**
  （+3 页面交互）；真实 E2E（micrograd + DeepSeek + GitHub）见交付报告

### P7.2 可执行课程生成（D42）

- [x] **Lesson Builder**：每任务一次 LLM 产出四类材料（说明/starter/
      tests/reference/hints）+ 前任务参考实现传递（累积工程）+ 修复轮
      （真实 stdout/stderr 反馈）
- [x] **Course Verifier（真实沙箱）**：PythonRunner + Docker 沙箱真实执行
      参考实现测试；starter 期望失败验证（防答案泄露/测试空转）；防伪守卫
      （TODO/泄露/空断言）；最终集成（全部任务测试在最终参考上通过）
- [x] **CourseRelease**：版本化不可变；参考实现受保护存储（API 剥离）；
      蓝图快照冻结；重启恢复（卡住标 failed 可重试）
- [x] **instantiate**：ready release → 学习项目（首任务 starter+全部任务
      +hints；course-release 模板标记；不复用默认种子）
- [x] **API 5 端点 + 前端**：build-lessons/releases/lessons/release/
      instantiate；生成页课程内容进度 + "开始学习"进 IDE
- [x] 验证：后端 **268 全过**（+7：守卫四类违规/合并/真实沙箱 3 个/
      流水线/恢复）；前端 **274 全过**；**真实全链 E2E**（micrograd：
      GitHub→蓝图→材料→沙箱验证→发布→实例化→IDE 首任务测试）

### P7.3 学生学习生命周期（D43）

- [x] **缺陷修复**：E2E 虚假断言（or True→真实集成报告断言）；H4 服务端
      剥离（公开 API 只给 H1-H3）；starter 收集失败≠预期失败；候选概念
      安全降级（图谱外概念不崩溃）
- [x] **任务生命周期**：locked→available→active→needs-fix→completed
      （服务端权威 DAG 传播）；activate（依赖闸门+安全合并+幂等+原子）；
      three_way_merge（学生代码不覆盖 + 冲突报告）；最终验收报告
- [x] **API**：course-progress / activate / final-report；evaluate 联动
      解锁提示
- [x] **前端**：TaskPanel 生命周期徽标 + locked 显示依赖 + available
      「开始任务」按钮
- [x] 验证：后端 **282 全过**（+14）；前端 **274 全过**

### P7.2 补充：课程内容重试反馈环（D42 增补）

- [x] **失败重试**：release failed 卡片新增「重新生成课程内容（vN+1）」
      按钮（无需刷新页面）
- [x] **失败上下文注入**：重试生成时收集同一 generation 此前所有 failed
      release 的逐任务问题（守卫错误 + 修复轮未解决项 + release 级兜底，
      兼容 camel/snake 两种 artifact 键），以 PRIOR_FAILURES 块注入该任务
      的生成提示词（系统提示同步声明），LLM 针对性规避上次失败原因
- [x] 验证：后端 **284 全过**（+2：重试提示携带失败原因 / _prior_failures
      单元）；前端 **275 全过**（+1：失败卡片重试按钮触发 v2）

### P7.2 修复：防伪守卫语言化 + 不支持语言如实拒绝（D42 增补 2）

**根因**：C++ 课程（线上 v3/v4）被 Python-only 守卫误拒——TODO 检查只读
`.py`、测试检查只认 `def test_`，而 C++ 材料的 TODO 在 CMakeLists.txt、
测试为 assert 可执行程序（完全符合课程自身 ENV 约定）；3 轮修复 ×
多版本全部撞死在同一误报上。且 `run_in_sandbox` 非 Python 返回 skipped，
流水线也无前置语言闸门——C++/TS 课程注定失败却反复烧 LLM。

- [x] **guard_starter 语言化**（`language` 参数）：TODO 检查按语言读正确
      文件（cpp 含 CMakeLists/.cmake；ts 读 .ts/.tsx）；裸 `TODO` 无描述
      不算有效标记；泄露判定语言化
- [x] **Python 结构化校验（AST）**：测试文件必须可解析（pytest 可收集）、
      `test_` 函数非空转（无 assert/raises/approx → 报函数名）、
      `assert True` 恒真断言拒绝；starter 无 TODO 但有空壳函数
      （pass/.../raise NotImplementedError）也算有效待实现区域
- [x] **C++/TS 守卫规则**：cpp 要求测试为含 main 的可执行程序 + 真实
      断言（assert/EXPECT_*/ASSERT_*）；ts 要求 it/test 用例 + expect 断言
- [x] **不支持语言提前拒绝**：`SANDBOX_VERIFIED_LANGUAGES=("python",)`；
      build_lessons 对 cpp/ts 直接 422（不创建 release、零 LLM 调用），
      `_run_build_inner` 对历史行防御性标 failed；错误信息如实说明限制
- [x] **修复轮反馈增强**：守卫拒绝时附带文件清单（路径+行数）与
      starter/test 头 12 行摘要；REPAIR_SYSTEM_PROMPT 明确禁止删测试/
      恒真断言/补全 starter/移除 TODO 等伪造成功手段
- [x] **契约修复**：`VerifyOutcome.to_dict()` 键对齐 SandboxVerification
      （total_tests 等；此前 total/passed/failed 被 schema 静默丢弃）
- [x] **前端**：失败卡片新增「修复尝试记录」折叠列表（逐轮实际原因）；
      artifactSchema verifications 字段名对齐后端契约
- [x] 验证：后端 **290 全过**（+6：py 结构化/线上 C++ 样本回归/cpp 三类
      违规/ts 规则/未知语言/unsupported 422 零 LLM）；前端 **275 全过**；
      **真实 Docker E2E**（PW_SANDBOX_E2E=1，新 test_lesson_docker_e2e.py）：
      micrograd 9 任务全链真沙箱 ready——参考实现真跑 pytest（totalTests>0）、
      starter 期望失败（failedTests>0）、最终集成、实例化全部通过

### P8.1 CMake Project Runtime（D44）

**根因修复**：删除目标猜测（`resolve_cmake_target` 正则解析）与 direct 模式的
自动 CMake 分支；CMake 成为显式 profile。

- [x] **契约**：`ExecutionCreate` 增 `buildSystem/cmakeAction/targetName/
      selectedTests`（默认 direct，旧客户端零改动）；`ExecutionRead.cmake`
      目标列表/测试发现/产物路径/生成器版本；`DiagnosticRead.stage` 阶段
      细分；`cmake_info` 列 + Alembic 迁移（server_default 兼容存量行）
- [x] **File API 目标发现**：沙箱内写 codemodel-v2 query → 真实
      `cmake -S -B -G Ninja -DCMAKE_BUILD_TYPE=Debug` → 解析 reply
      （index 字典 → codemodel → target 文件）；六类目标类型识别；
      EXECUTABLE+产物声明 = runnable；缺回复明确报错不伪造
- [x] **Build/Run**：`cmake --build --target X --parallel 2`（参数数组）；
      run 产物路径来自 File API 且 realpath 必须在 build 目录内；构建失败
      → run skipped；未知目标报错并列出已发现目标；非 EXECUTABLE 拒绝运行
- [x] **CTest**：configure → 全量构建 → `--show-only=json-v1` 发现 →
      `--output-on-failure --output-junit` 执行 → JUnit 解析（2MB 上界；
      failure message 为空时回退 system-out）；**0 执行/JUnit 缺失/Not Run
      一律不判通过**；选择执行 `-R` 逐名转义
- [x] **诊断**：configure 错误定位 CMakeLists 行号（stage=configure）；
      编译错误 file:line:col（stage=build，Ninja 输出走 stdout 已合并捕获）；
      链接错误符号级；阶段序列 configure→build→run/test 如实记录
- [x] **资源 profile**：`PW_EXECUTION_CMAKE_*`（180s/1GB/2CPU/256pids/
      512MB tmpfs）服务端限定；全部在既有受限一次性容器内执行
- [x] **前端**：executions 契约 + cmake schema（skipped 进入契约）；
      `runCmake.ts` 终端粘合（操作与目标名进终端日志）；IDE `CMakeControls`
      （Configure/刷新目标、目标选择器按类型标注可运行性、构建/运行/CTest，
      仅根 CMakeLists.txt 项目显示）；测试面板 skipped（○）独立呈现
- [x] **验收工程**：`tests/fixtures/sample-cmake-project`（多级子目录 +
      engine 静态库 + target_include_directories/target_link_libraries +
      game/inspect 两个可执行 + 2 个 CTest，其中 test_terrain 故意失败）
- [x] 验证：后端 **303 全过**（+13：File API 解析/契约校验/诊断/各阶段
      marker/0 执行不通过/未运行标 skipped/build-only 无 run 阶段）；
      前端 **282 全过**（+7：cmake 契约/discover 目标/选择触发构建运行/
      库目标禁运行）；**真实 Docker E2E**：cmake **10/10**（多目录 Configure、
      File API 真实目标、engine 被 game 链接、双可执行目标运行、CTest
      发现执行、故意失败显示 failed、编译错误行号、configure/build 错误
      区分、无遗留容器、目标选择执行）+ 旧 C++ **13/13** + LLDB **6/6**
      不回归

### P8.1.1 CTest 选择执行修复 + P8.2 C++ AI Course Builder（D45）

**P8.1.1 修复**（ctest -R 为 POSIX ERE 的实测发现）：
- [x] `-R` 全锚点 `^(a|b)$`（`(?:)` 不被 ERE 支持且 ctest 编译失败仍退出 0——
      已加"发现非空却 0 执行"显式报错防线）；`test_world` 不再误匹配 `test_world_extra`
- [x] 通过条件只覆盖本次要求执行的测试（选择=选中项；全量=全部发现）；
      未选择的 skipped（"未在本次选择范围"）不影响成功
- [x] 显式选择的测试不存在 → 明确报错并列出实际发现（不静默）
- [x] 要求执行的 Not Run/DISABLED/JUnit skipped → 不判通过（requiredMissing）
- [x] E2E +2：未知测试名报错、前缀不误运行（fixture 增 test_world_extra）

**P8.2**：
- [x] **执行档案**：`execution_profile.py` 评分式语言判定（混合仓库不误判）+
      VERIFIED_PROFILES 门控 + 外部依赖检测；build_lessons 接入（cpp/cmake 解禁）
- [x] **CppCMakeLessonBuilder**：分语言提示词（演化工程/engine 库/头实现分离/
      add_test/buildManifest 真实声明/无 pytest）；与 Python 共享修复流程
- [x] **CppCMakeCourseVerifier 八步**（复用 P8.1 Runner）：守卫（expectedFiles
      精确泄露判定 + CMakeLists 认可为测试注册）→ Configure → File API 目标
      校验 → 构建+参考测试（∪回归）→ starter 预期失败（坏工程拒绝；
      expectedFailurePhase 仅限修复构建类任务）→ final：全量 CTest + demo 运行
- [x] **流水线接入**：`_process_cpp_task`（有限修复轮 + 真实诊断回灌 +
      PRIOR_FAILURES）；最终集成在末任务验证内完成（python 尾部逻辑跳过）
- [x] **生命周期**：ProjectTask.verification 列（迁移 425f18ba32e6）+
      instantiate 写入 + `evaluate_task_cmake`（服务端读学生工程直接跑 CTest，
      不信客户端；回归=已完成任务 testNames 并集）+ evaluate 路由分发
- [x] **前端**：plan 契约 verification；TaskPanel→cmakeTestInTerminal(testNames)
      路由；CmakeOutcome 暴露逐测试结果；测试状态含 skipped
- [x] 验证：后端 **321 全过**（+11：泄露精确判定×2/注册脚本/验证器失败路径×4/
      回归并入/生成器契约/无测试拒绝 + 执行档案 5）；前端 **282 全过**；
      **真实 Docker E2E**：Mock LLM 世界引擎学生旅程全链通过（3 任务演化
      工程→八步验证→ready→实例化→激活/解题/服务端验收（starter 必失败、
      实现后过、回归保持）→最终报告；参考实现/H4 API 隔离）；4 个 Docker
      套件 31 用例全过无回归

### P8.2.1 增量课程生成引擎（D46）

**根因**（上轮 5 次真实运行诊断）：全量再生成 + 上下文截断（14 文件×2200 字符）
→ t3 一致性缺陷三类模式；修复轮整包重生成无法收敛。

- [x] **LessonChangeSet 协议 + 确定性应用器**：模型只出本任务文件变更
      （完整内容 + baseHash 乐观锁）；未改文件服务端继承；原子/防穿越/
      防重复/保护删除；starter 挖空 create-on-existing 规范化
- [x] **工程上下文构建器**：全量 Manifest + 相关性选取关键文件全文
      （预算硬上限，整进整出）+ [partial] 摘要 + 上任务契约——替代截断
- [x] **增量 Builder**（`build_cpp_cmake_changeset`）：增量协议 v1 提示词
      （照抄 baseHash/追加注册不删旧/expectedFiles 只列挖空 TU）
- [x] **一致性验证器**：include/注册/回归保护/starter 挖空与泄露的结构化
      错误（errorCode/filePath/expected/actual/suggestedRepairScope）
- [x] **CppCMakeRepairAgent**：12 类失败确定性分类 + 最小补丁协议
      （不删测试/不弱化断言/不删 manifest）+ LLM/Token/沙箱预算
- [x] **Verifier 收紧**：starter 预期失败 = 真实执行且断言失败；
      Not Run/未发现/构建失败均非合格（未发现单列诊断）
- [x] **Checkpoint + Resume**：course_checkpoints/generation_jobs 表
      （迁移 bb22ce8a7741）；任务通过即固化快照+注册表；resume 新建版本
      复用连续前缀检查点（零 LLM）；restart→interrupted；释放
      verificationReport.diagnostics（reusedTasks）
- [x] **API**：GET /course-releases/{id}/checkpoints、POST .../resume、
      POST .../tasks/{taskId}/retry；ReleaseRead 增 verificationReport；
      SandboxVerification 增 note（starter 预期失败的具体测试名）
- [x] **前端**：失败卡片 = 已完成任务保留提示 + 从检查点恢复按钮 +
      完全重新生成；ready 卡片 = 检查点复用徽标 + 课程验证详情
      （CMake/CTest 逐步骤 ✔/✘ + 测试计数）
- [x] 验证：后端 **340 全过**（+19 新模块单测）；前端 **284 全过**；
      Mock 旅程 E2E + **断点恢复 E2E（验收 D）**全过——恢复时
      provider.calls == ["build:t3"]（t1/t2 零 LLM）、旧 release 不可变、
      学生旅程在 v2 上完整通过；真实 DeepSeek E2E 见下方运行记录

**P8.2.1 真实 DeepSeek 运行记录（12 轮，如实）**：t1/t2 **每轮稳定通过**
（增量 ChangeSet + 真实 CMake/CTest 八步验证 + 检查点固化）；t3 失败点
逐轮收敛（泄露→测试空断言→注册缺失→include 路径→starter 覆盖），每轮
修复一类真实缺陷并沉淀为确定性防线（预算记账/组间去重/哈希宽容/泄露
对齐/starter 补丁目标/测试基础设施放行/前序测试保护/空补丁拒绝/预算 5 轮），
但 5 轮修复预算内 t3 尚未全部收敛——**验收 A/B/C 的三任务连续 ready 未
达成**（Mock 全链与验收 D/E 已过）。下一步：deepseek-reasoner 或 t3 拆分
为两个较小任务（引擎侧集成 + app/demo）。

### P8.2.2 可靠 C++ 课程生成与生产加固（D47）

- [x] **GenerationTrace**：repairs 记录真实 changedFiles/outcome
      （deterministic-fix/circuit-break/regenerated）+ checkpoint.diagnostics
      （llmCalls/tokensUsed/sandboxRuns/firstAttemptPassed/deterministicFixes/trace）
- [x] **Task Complexity Analyzer**（`generation/task_complexity.py`）：确定性
      计分（交付物数/集成+入口耦合/终点全量验收/模块跨度/新目标+新测试），
      可解释 reasons + confidence；空规格返回 unknown 不伪装
- [x] **任务自动拆分**（`generation/task_refinement.py`）：保守确定性拆分
      高复杂度终点集成任务（集成侧 + 入口侧，按交付物可分性判定；分不动
      不拆）；只作用于 release 私有蓝图快照（gen 蓝图与既有 Checkpoint
      不触碰，蓝图哈希变化默认不复用旧检查点）；DAG 重挂后继
- [x] **严格 Hash 语义恢复**：update baseHash 缺失/不匹配一律拒绝
      （结构化冲突，无静默覆盖）+ **服务端权威回填**两类确定性修复
      （reference/test 哈希类冲突回填重试；Starter Overlay Base 按合成
      参考版回填——两阶段快照关系不依赖 LLM 抄哈希）
- [x] **Repair 收敛**：进度跟踪（错误签名集合对比）；连续两轮无净改善
      → 熔断改重新生成策略（已完成任务不受影响）；确定性修复分流
      （manifest 测试名保守对齐：一一对应才修正）；空补丁拒绝
- [x] **Model Routing**：COURSE_GENERATION/REASONING/REPAIR_MODEL +
      每任务 LLM/Token/耗时/沙箱上限配置；Mock provider 永不路由收费模型
- [x] **Job 原子 Lease**：事务 + FOR UPDATE 行锁抢占（SQLite 单写者天然
      串行）；唯一 lease_token；每任务续租；Checkpoint 提交与 ready 发布
      前验证租约（旧 worker 失效写入被拒）；重启 → interrupted
- [x] **Checkpoint 兼容加强**：task_spec_hash + prev_snapshot_hash 链验证
      （前序快照链不匹配即断链不复用）+ 迁移 7edb9eb11b76
- [x] **前端**：任务拆分徽标（原 N → 细化 M + 拆分原因）
- [x] 验证：后端 **352 全过**（+12：复杂度/拆分/租约原子性与并发竞态/
      熔断签名/确定性对齐/Starter Overlay Base）；前端 **284 全过**；
      **Mock 四任务 E2E（t3 自动拆分为 t3-a/t3-b）+ 断点恢复 E2E 全过**
      （恢复仅调用 build:t3-b；学生旅程四任务含回归全过）

**P8.2.2 真实 DeepSeek 运行记录（5 轮，如实）**：架构升级后逐轮失败点：
①t2 starter 预期失败未覆盖 → ②base-hash-mismatch（→ 系统化修复：Starter
Overlay Base 服务端回填）→ ③t3-b 链接错误（→ 系统化修复：验证修复上下文
纳入本任务全部源码/头文件）→ ④t2 参考实现断言失败 → ⑤t1 测试空断言。
**3/3 连续成功目标未达成（本会话 0/5）**；t1/t2/t3-a 在多轮中分别单独通过
（含真实 CMake/CTest 八步验证与检查点固化），但整课程 ready 的连续稳定性
仍不足——deepseek-chat 在受约束增量协议下的输出方差是主要瓶颈。
已按规范如实记录；下一阶段建议：启用 COURSE_REASONING_MODEL 路由到
推理模型做 A/B（配置已就绪，未在本会话启用以控费用）。

### P8.2.3 Autonomous Course Development Harness（D48）

- [x] **架构**：Agent Controller（LLM）/ Tool Runtime（白名单）/
      Course Workspace（版本化）/ Independent Evaluator / Session
      Persistence 五分离；Agent 只提出行动，Harness 执行与判定
- [x] **CourseDevSession**（表 course_dev_sessions，迁移
      6a388ff17721 + a74f266d552d）：状态机（pending/developing/paused/
      completed/failed/cancelled，服务端权威）+ 原子租约 + 真实用量计量
      （token/工具/沙箱）+ 预算（轮次/工具/Token/沙箱/无进展熔断）
- [x] **CourseWorkspace**：reference + starter_overlay（两阶段基线）+
      manifest/instructions/hints + revisions 不可变历史；修改全走
      ChangeApplier（严格哈希/原子/路径校验）
- [x] **工具注册表**（复用 P6 ToolRegistry）：list/read/apply/
      update_material + cmake_configure/build、run_ctest、run_executable
      （全走受限 Docker CMake Runtime，无任意 Shell）+ evaluate_lesson
      （独立评估）+ save_checkpoint（前置校验）/rollback/submit_task；
      工具结果结构化截断回填
- [x] **独立 Evaluator**：verify_cpp_cmake_task 八步（engineering 确定性）
      + pedagogy（starter 预期失败确定性 + 启发式标注）+ 稳定性（N 次独立
      Clean Sandbox）+ 轻量 Mutation（边界算子，compile-error 不算 killed）
- [x] **API**：POST /course-dev-sessions、GET /{id}、POST /{id}/run|pause|cancel
- [x] **前端**：开发会话区域（状态/预算/三维度评估/真实工具时间线）
- [x] 验证：后端 **358 全过**（+5 harness 单测）；前端 **284 全过**；
      **E2E B**（受控链接故障→Agent 真实读诊断→修 CMake→真实构建/CTest→
      独立评估 passed→checkpoint→submit，真 Docker）+ 控制/隔离 E2E 全过
- [x] **真实 DeepSeek 工具循环（E2E A）**：自主多轮调用 22 个真实工具
      （read×7 → apply×4 → configure → build×2 → ctest×2 → update_material
      → evaluate×2 → save_checkpoint → submit），15 轮/85,791 tokens/
      5 次沙箱/69s 完成 t2 Entity 任务——engineering/pedagogy/stability
      全部 passed，Verified Checkpoint 已固化（Agent 自己设计了 header-only
      Entity + spawn/valid 测试，真实 CMake/CTest 通过）。第一轮在 14 轮
      旧预算下评估已过但未及保存（已提高默认预算），第二轮完整闭环。

### P8.2.3.1 Harness 生产加固（D49）

修复 P8.2.3 审查确认的 7 个问题（Resume 丢失/评估未绑版本/稳定性可绕过/
manifest 可降级/外键语义/completed≠发布/预算可重置）：

- [x] **Evaluation Fingerprint**（`controller.evaluation_fingerprint`）：
      绑定 taskId/revision/reference/starter/manifest/instructions/hints/
      priorTests/baseHash/blueprintHash/acceptanceHash/evalVersion——任何
      apply/update/rollback 后旧评估即 **Stale**（工具链自动失效）
- [x] **Verified Checkpoint Policy**：engineering=passed + stability≠失败 +
      pedagogy≠失败 + **Fingerprint 与当前工作区一致**（TOCTOU 防护：评估后
      修改→保存拒绝）+ 会话租约有效（CourseDevSession 行级，非 GenerationJob）
- [x] **Runtime Snapshot 跨 Slice 恢复**：slice 结束持久化完整工作区
      （reference/starter/manifest/instructions/hints/revisions）+ Agent 消息
      （含 tool_call_id 链）+ 指纹 + 消耗；resume 时四重兼容校验（任务/
      蓝图/基线/协议版本）通过即原样恢复——**不重写已写文件、不重放消息**
- [x] **Frozen AcceptanceContract**（`acceptance.py`）：任务开始冻结
      （task_spec_hash + 必需行为 + 前序回归）；`update_course_material`
      的 manifest 变更经契约校验（前序回归不可删除；Agent 可增/改名自己的
      测试）；契约哈希入 Fingerprint
- [x] **外键语义修复**：无 Release 的开发 Checkpoint release_id=NULL
      （移除 generation_id 伪装）；CourseCheckpoint.release_id nullable 迁移
- [x] **CourseRelease 自动发布**（`service._publish_release`）：全部任务
      Verified Checkpoint → 链完整性（task_seq 连续 + prev_snapshot_hash 链）
      → 最终全量 CTest + Demo 运行（真沙箱）→ ready（数据库事务）；失败→
      session=failed 保留检查点可继续修复；release_id 回写 session
- [x] **双层预算**：会话总 Token 上限跨 slice 累计（不重置）；发布/恢复/
      完成任务 ID/发布 Release ID 进入 Status API
- [x] 验证：后端 **369 全过**（+11 加固单测：Fingerprint 变化/Stale/恢复
      往返与不兼容拒绝/契约冻结与降级拒绝/保存政策）；前端 **284 全过**；
      **跨 Slice 恢复 + 自动发布 E2E（真 Docker）通过**：t2 slice1 写文件→
      暂停（Runtime Snapshot 含文件与消息）→ slice2 恢复（apply 恰一次，
      不重写）→ 独立评估 passed（含稳定性 2/2）→ checkpoint → submit →
      **自动发布 ready CourseRelease**（检查点链 + 最终 CTest + instantiate
      学生项目成功）；E2E B 在契约冻结下通过（manifest 保留前序回归）

**P8.2.3.1 真实 DeepSeek 加固验证（完整发布链）**：真实 Agent 工具循环完成
t2 → 全任务完成（t1+t2）→ **自动发布 ready CourseRelease**
（`ce5dc069-57c9-4b9f-b995-b84ae7e9d139`，2/2 任务，最终全量 CTest 真沙箱
通过）→ 学生项目实例化成功（201）。全程 69s、单一 slice 完成（预算内），
Fingerprint/契约/租约校验全部生效。

### P8.2.3.2 全课程自主开发 + 发布恢复 + 协作取消（D50）

- [x] **Final Evaluation/Repair 状态机**（修复发布失败死状态）：全部任务
  完成 → final-evaluating（真全量 CTest + 稳定性 + Demo）→ publishing；
  失败按类别分流——engineering/contract → final-repairing（基于最后
  Verified Checkpoint 的修复工作区，Agent 可继续修）；infrastructure →
  paused（数据库/租约/沙箱错误**不交给 AI 改代码**）。全部任务完成但
  发布失败 → _build_controller 进入修复控制器（不再 422 死状态）
- [x] **Cooperative Pause/Cancel**：pause_requested/cancel_requested 持久化
  （迁移 e7341bdac4ec）；controller 在**每次 LLM 调用前 + 每个工具执行前**
  实时读 DB 检查——暂停/取消真正中断循环（单测证明取消后 LLM 零调用、
  暂停后第二轮 LLM 零调用）；取消后发布被拒
- [x] **Lease/并发修复**：generation_jobs.release_id 唯一约束（迁移
  fe28af09866a）+ 插入 IntegrityError 竞争防护——双线程并发抢占测试
  由间歇失败（2 winners）修复为 5/5 稳定恰一成功
- [x] **Effective Blueprint 单一权威**：发布使用 session 实际蓝图（含
  拆分映射/任务/里程碑 + effectiveBlueprint 溯源块）；artifact taskId
  集合必须与蓝图任务集合一致（不一致拒发 contract 失败）
- [x] **Final Evaluation Report**：{blueprintHash/checkpointCount/
  requiredTests/executedTests/passedTests/demoTargets/stability}——
  全部真实执行数据（全量 CTest 计数 + 2 次 Clean Sandbox 稳定性 + Demo
  逐目标运行）；发布幂等（同 session 已发布直接返回）
- [x] **expectedFiles 权威注入**：harness evaluate 把 starter_overlay 推导
  的 expectedFiles 注入材料——下游 verify/守卫同源判定（修复空
  instructions 时全工程启发式泄露误报）
- [x] **Level B 全课程 E2E（真 Docker）通过**：t1 World→t2 Entity→t3
  Integration→t4 Demo（banner 化 Demo 任务保证 CTest 可验证挖空）从零
  开发，每任务独立评估（真 CMake/CTest/稳定性 2/2）+ Verified Checkpoint
  （四任务累积快照 + 回归注册表）→ Final Evaluation（全量 CTest + Demo）
  → **自动发布 ready CourseRelease** → 学生四任务完整旅程（starter 态
  真实失败→实现→服务端 CTest 验收→解锁→final-report 4/4）
- [x] 验证：后端 **373/374**（test_debugging_api 偶发时序 flake 与本轮
  无关，独立复跑即绿；race 测试修复后 5/5 稳定）；前端 **284 全过**；
  harness 加固单测 16 过（含 Final Repair 控制器/失败分类/协作取消/
  暂停边界/取消拒发布）

**P8.2.3.2 真实 DeepSeek 四任务从零运行记录（如实）**：t1 World、t2 Entity、
t3 Integration **全部由真实 DeepSeek 在 Harness 中自主开发完成**（各任务
独立评估真 CMake/CTest/稳定性通过 + Verified Checkpoint 固化，逐任务累积
快照）。t4 Demo 未完成：Agent 陷入 read_workspace_file 循环（122 次读取/
1.7M token 无收敛），触发**会话总 Token 预算 2.3M 上限正确暂停**（预算
防线按设计生效——保存状态等待提高预算后续跑，非失控消耗）。瓶颈分析：
长会话上下文累积后模型重复读取不收敛——下一阶段应做上下文压缩/摘要
（超 N 轮触发 Session Summary）与重复读取检测。发布未触发（t4 无
Checkpoint）——如实记录。
