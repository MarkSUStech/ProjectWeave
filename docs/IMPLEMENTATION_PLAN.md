# 实施计划（Implementation Plan）

依据 `docs/product-design.md` §18 的分阶段路线细化。状态标记：
✅ 已完成 · 🔶 部分完成 · ⬜ 未开始。

> 本文档描述计划；实际完成度以 `docs/PROGRESS.md` 为准。

## P0 基础（当前阶段）—— 单人能创建并恢复项目

| # | 任务 | 状态 |
|---|---|---|
| 0.1 | 仓库结构、开发文档体系（AGENTS/PLAN/ARCHITECTURE/DECISIONS/PROGRESS） | ✅ |
| 0.2 | 后端基础工程：FastAPI + SQLAlchemy + Alembic + 配置 + 健康检查 | ✅ |
| 0.3 | projects 领域：ProjectSpec 核心字段建模、CRUD API、spec_version 维护 | ✅ |
| 0.4 | 前端基础工程：Vite + React + TS 严格模式 + Tailwind v4 + 路由 | ✅ |
| 0.5 | 纵向切片：创建项目目标 → 持久化 → 项目详情展示 | ✅ |
| 0.6 | 教学 IDE 骨架：Monaco 编辑器、四种工作模式、布局锁定、占位面板 | ✅ |
| 0.7 | 基础测试：后端 14 个 pytest、前端 19 个 vitest | ✅ |
| 0.8 | 身份与多用户（owner_id 已预留，认证体系未实现） | ⬜（推迟到 P1 与会话一起设计） |

**P0 完成门槛已达成**：可以本地启动前后端，创建项目并刷新后回读。

## P1 编程内核 —— 样板项目任务可在 IDE 中编译运行

| # | 任务 | 依赖 | 状态 |
|---|---|---|---|
| 1.1 | 服务器端文件系统：project_files 表、文件树 API、打开/保存/重命名/删除 | 0.3 | ✅ |
| 1.2 | 编辑器接入真实文件（含脏状态、Ctrl+S、切换保护），替换本地草稿 | 1.1 | ✅ |
| 1.3 | 代码快照（code_snapshots 表 + codeVersion）与防抖自动保存 | 1.1 | ✅ |
| 1.4 | 浏览器内 JS 运行器（Worker 沙箱），终端面板输出 | 1.1 | ✅ |
| 1.5 | 测试运行器（浏览器内断言式测试）与测试面板 | 1.4 | ✅ |
| 1.6 | WebSocket 通道（会话事件流骨架：运行状态、保存确认） | 0.2 | ⬜ |
| 1.7 | 身份认证（注册/登录，替换 dev-user 占位） | 0.8 | ⬜ |
| 1.8 | PostgreSQL 切换验证（docker-compose，兼容性 pytest 套件） | 0.2 | ✅ |

## P2 教学闭环 —— 根据两种不同能力情况给出不同路线

| # | 任务 | 依赖 | 状态 |
|---|---|---|---|
| 2.1 | knowledge_concepts 种子数据 + 知识图 API | P1 | ✅ |
| 2.2 | 初始能力诊断流程（预测题/解释题/小编码任务，规则化更新） | 2.1 | ✅（客观题；解释题/编码任务评分待 Tutor Engine） |
| 2.3 | learner_mastery 四维估计 + 置信度 + 学习证据表 | 2.2 | ✅（MVP：prediction→understanding 维；其余维待对应证据类型） |
| 2.4 | Curriculum Engine：任务-知识双图规划，LearningPlan 版本化 | 2.3 | ✅（样板课程模板；任意目标生成属后续） |
| 2.5 | Tutor Engine 骨架：LLM Provider Adapter、TeachingDecision、Policy Gate | 2.4 | ✅（DeepSeek 真实接入；冷却/三模式属 2.6） |
| 2.6 | 渐进式提示协议（H0-H4）与 AI 介入三模式（Quiet/Adaptive/Guided） | 2.5 | ✅（H4 门控 + 三模式建议差异 + 冷却；H4 后独立性重测属 P3.5） |
| 2.7 | 学习事件信封（transactional outbox + 幂等消费） | 2.3 | ✅（MVP：router 内追加而非严格同事务 outbox，见 D21） |

## P3 可视化与工作台 —— 点击代码与场景双向定位

| # | 任务 | 依赖 |
|---|---|---|
| 3.1 | TeachingScene Schema + 组件注册表 + Scene Renderer 协议 | P2 | ✅（含首个 L1 组件 console-timeline） |
| 3.2 | 两类标准组件端到端（执行时间线 + 调用栈/变量状态） | 3.1 | ✅（console-timeline + variables-state；调用栈组件按需追加） |
| 3.3 | 真实执行数据绑定（traceId + codeVersion 过期标记） | 3.2 | ✅（运行指纹 + 过期横幅；trace 数据库化留待远程沙箱） |
| 3.4 | WorkspaceAction 权限等级（A0/A1/A2）+ 撤销与布局锁定联防 | 2.5 | ✅（后端 Gate + 前端执行器/通知条组件；宿主挂载待并行前端合入——见 D28） |
| 3.5 | 阶段验收流程（/tasks/{id}/evaluate + rubric） | P2 | ✅（MVP rubric=套件全绿；per-task 测试绑定待课程内容制作） |
| 4.1 | 任务驱动教学闭环（试点课程 + 任务级测试绑定 + practice 信任级） | P2-P3 | ✅（D29） |
| 4.2a | 语言无关执行层 + 多文件 TypeScript（esbuild-wasm） | P1 | ✅（D30） |
| 4.2b | 远程执行沙箱 + Python（CPython 3.12 + pytest，Docker 隔离） | 4.2a | ✅（D32/D33） |
| 4.2c | C++20 多文件编译执行（Clang 15 + CMake/Ninja + 测试与教学联动） | 4.2b | ✅（D34/D35） |
| 4.3 | 正式认证信任级（服务端受保护测试 + 可信快照） | 4.2b | ⏳ 计划 |
| 4.4 | 受控依赖（requirements.txt / vcpkg 白名单） | 4.2c | ⏳ 计划 |
| 4.5a | C++ 交互式调试（LLDB DAP：断点/单步/调用栈/变量/TeachingScene/Mentor 只读联动） | 4.2c | ✅（D36/D37） |
| 4.5b.1 | C++ 内存与指针关系可视化（真实地址匹配 + 暂停代次隔离） | 4.5a | ✅（D38） |
| 4.5b.2 | 堆对象图/new-delete 生命周期动画与 Python DAP | 4.5b.1 | ⏳ 计划（白名单 evaluate 通道可扩展） |
| 5.1 | 多语言课程适配（版本化模板）+ C++ 指针课程（知识图/诊断/3 任务/Tutor hints）| 4.5b.1 | ✅（D39） |
| 5.2 | 第一轮学生试用反馈迭代 + Python 课程制作 | 5.1 | ⏳ 计划 |
| 6 | AI Teaching Agent（工具调用循环 + 只读工具 + 轨迹） | 5.1 | ✅（D40） |
| 6.1 | Course Architect Agent（GitHub 课程生成，复用 Runtime/Registry） | 6 | ⏳ 计划 |

## P4 打磨与试点 —— 完整用户旅程与学习效果测量

恢复/导出、可观测性（token 用量/延迟/场景命中率）、安全渗透测试、性能验证、小样本试点与对照实验。

## 明确不在近期范围

- GitHub 仓库导入（FR-10，SHOULD）→ V1.1
- REA 研究适配（FR-11，LATER）→ V2
- 任意项目自动课程生成、L3 动态生成可视化组件 → V1.2+
  （远程执行沙箱已于 P4.2b/P4.2c 交付：Python + C++ 真实运行，见 D32-D35）
