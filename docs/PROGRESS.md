# 进度记录

更新时间：2026-10-10（P3.1 完成；仓库已推送 GitHub）

## 已完成（经过验证）

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
- [x] 验证：前端 vitest 150 个用例全过（viz 10：schema 默认值与拒绝非法/
      注册表元数据与重复注册/来源标签与时间线渲染（system 条目过滤、相对
      毫秒）/诚实空态/点击详情本地交互/未注册显式报错/内置场景渲染）；
      typecheck/build 通过；dev 冒烟通过（viz 模块经 Vite 编译无错）；后端
      本轮零改动（111+4 状态不变）

### P1 验证汇总

- [x] 验证（P1.3 轮）：后端 43 + 前端 98 用例、typecheck/build、快照恢复冒烟全过
- [x] 验证：SQLite pytest 43 个用例全过（PG 套件默认 skip 4 个）；PG 兼容套件
      4 个用例全过（容器 PG 16）；真实服务冒烟（uvicorn+PG）通过

## 未实现（明确标注，禁止伪装）

- [ ] 第二类标准组件（调用栈/变量状态）与 L2 动态组合（AI 产出 SceneSpec）— P3.2
- [ ] 真实执行数据绑定（traceId + codeVersion 过期标记）— P3.3
- [ ] H4 之后的独立性迁移验证（依赖任务验收与 rubric）— P3.5
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
- 重命名/删除使用浏览器 prompt/confirm，后续换成内联 UI。
- 浏览器 Worker 隔离为便利级（无 DOM/应用状态访问，但同源 fetch 理论可行）；真实网络隔离待远程沙箱（D11）。
- 运行器/测试尚无 stdin；多文件 import 不支持（Worker 单文件模式，种子示例已自包含并注明）；`.tsx` 不支持运行。
- 自研断言 API 是 jest 子集（toBe/toEqual/toBeTruthy/toBeFalsy/toContain/toThrow/.not），不承诺语法全集兼容（D14）。
- 快照内联存 DB（每文件 50 份 × 1MB 上限）；多用户/大项目场景再评估内容寻址 + 对象存储（D15）。
- 自动保存固定 2.5s 防抖且默认开启（代码级可关）；设置面板提供开关属后续 UI 工作。
