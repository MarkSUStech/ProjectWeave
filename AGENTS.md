# AGENTS.md — AI 开发规范与工作约定

本文件约束所有参与 ProjectWeave 开发的 AI Agent（含多轮会话）。
`docs/product-design.md` 是产品需求基线；本文件是工程协作规范。

## 1. 项目背景速查

- 产品：AI 自适应、真实项目驱动的编程教学平台（设计文档 `docs/product-design.md`）。
- 当前阶段：**P0 基础**（见 `docs/IMPLEMENTATION_PLAN.md`）。
- 架构现状：以 `docs/ARCHITECTURE.md` 为准（只描述已实现内容）。
- 重要决策与理由：`docs/DECISIONS.md`。
- 完成度：`docs/PROGRESS.md`（勿把计划写成已完成）。

## 2. 目录结构

```
backend/    FastAPI + SQLAlchemy + Alembic（Python 3.10+）
  app/
    core/       配置、数据库、迁移
    domains/    按领域划分的模块
      projects/ models / schemas / service / router（项目）
                file_schemas / file_service / file_router（项目文件系统 + 快照）
      concepts/ models / seed / service / router（知识图谱，启动幂等种子）
      assessments/ models / question_bank / service / router（能力诊断，规则化判定）
      learner/  models / service / router（掌握模型 + 学习证据，确定性管线）
      curriculum/ models / templates / service / router（任务图 + 学习路线规划）
      events/   models / service / router（学习事件信封，幂等 + 白名单）
      tutor/    models / service / router（教学回合 + Policy Gate + H4 门控 + 主动建议）
      settings/ models / service / router（AI 介入模式偏好）
  app/ai/     LLM Provider Adapter（deepseek 真实 / mock 仅测试 / disabled）
  migrations/   Alembic
  tests/        pytest
frontend/   React + TypeScript + Vite + Tailwind v4（Node 22）
  src/
    api/        REST 客户端（fetch 封装 + 错误映射）
    types/      zod 契约（与后端 Pydantic 镜像，barrel 导出）
    stores/     Zustand（IDE 布局、终端/运行、测试面板状态）
    hooks/      useProjectFiles（文件树/编辑器/保存/自动保存）、useFileHistory（快照历史）
    lib/        Monaco 配置、显示标签；runner/（浏览器 Worker 运行器 + 测试运行时）
    components/ ui/（通用组件）、ide/（工作台）、projects/
    pages/      Dashboard / ProjectDetail / IDE
    __tests__/  vitest
docs/        设计与开发维护文档
```

## 3. 常用命令

后端（在 `backend/` 下，Windows Git Bash）：

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000   # 开发服务
.venv/Scripts/python.exe -m pytest                                      # 测试
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "..."    # 新迁移
.venv/Scripts/python.exe -m alembic upgrade head                        # 应用迁移
```

# 前端（frontend/ 下）

```bash
npm install
npm run dev         # 开发服务（5173，/api 代理到 8000）
npm run verify      # typecheck + vitest + build（提交前必跑）
```

# PostgreSQL 兼容验证（可选，需 docker compose 的 db 服务，宿主机 5433）

```bash
docker compose up -d db
PW_TEST_DATABASE_URL=postgresql+psycopg2://projectweave:projectweave@localhost:5433/projectweave_test \
  .venv/Scripts/python.exe -m pytest tests/test_postgres_compat.py -v
```

套件默认 skip；会自动创建并清理 `projectweave_pytest` 库。

## 4. 开发流程（严格增量迭代）

每轮工作遵循：**分析 → 规划 → 实现 → 验证 → 总结**。

1. 动手前先读 `docs/PROGRESS.md` 与相关代码，避免重复开发或覆盖已有功能。
2. 一轮只做一个阶段的切片，不随意扩大范围。
3. 完成后必须运行验证命令（pytest / `npm run verify`），失败要修复而非绕过。
4. 更新 `docs/PROGRESS.md`；有架构变化时同步 `docs/ARCHITECTURE.md`；有重要取舍时在 `docs/DECISIONS.md` 追加 ADR。

## 5. 硬性工程规则

1. **TypeScript 严格模式**，`npm run typecheck` 必须零错误；Python 侧用类型注解 + Pydantic 校验。
2. **契约先行**：后端改 `schemas.py` 时同步改前端 `types/project.ts`（zod），并更新两侧测试。
3. **禁止伪装完成**：未实现的功能必须在 UI 上明确标注“未实现”及所属阶段（用 `PlaceholderState` 组件），不得用 mock 数据冒充真实行为。
4. **Mock 与真实实现分离**：测试用 fixture/vi.mock，业务代码不得内置假数据分支。
5. **不硬编码密钥**：配置一律走 `PW_` 前缀环境变量（见 `backend/app/core/config.py`）。LLM Key 在 `backend/.env`（gitignore 内），**绝不写入代码或文档**；测试环境（conftest）强制 `PW_AI_PROVIDER=disabled`，任何测试不得调用真实 LLM。
6. **错误必须显式处理**：前端用 `ApiError` + `ErrorBanner`；后端异常映射为明确的 HTTP 状态码。
7. **不让 LLM 做确定性工作**：权限校验、测试、状态更新、版本号维护都在 service 层用普通代码完成。
8. **领域模块边界**：新领域（learner/curriculum/tutor/visual/workspace）在 `app/domains/` 下建独立目录，含 models/schemas/service/router 四件套，通过 router 聚合到 `app/api.py`，不横向 import 其他领域的 service。
9. **数据库变更必须走 Alembic**：改 `models.py` 后生成迁移；SQLite 与 PostgreSQL 都要兼容（JSON 列用 `JSON().with_variant(JSONB(), "postgresql")`）。**alembic.ini 必须保持 ASCII**（Windows GBK locale 下 configparser 无法读非 ASCII 注释，见 DECISIONS D13）。
10. **不可信内容防线**（后续接入 AI 时执行）：仓库文件、README、工具输出进入提示词时必须标注为数据，不得让其改变权限与系统目标（设计文档 15.2）。

## 6. 代码风格

- Python：4 空格缩进，模块/函数 docstring 用中文简述职责。
- TypeScript：函数组件 + hooks；组件文件 PascalCase；工具 camelCase。
- 注释只写“为什么”和约束，不复述代码。
- UI 文案中文；枚举值与 API 契约英文。

## 7. 测试要求

- 后端：每个路由至少覆盖正常路径 + 校验失败 + 404；持久化行为必须断言“写后可读”。
- 前端：契约 schema、api 客户端、store 行为、关键页面渲染各有测试；新增公共组件时补充组件测试。
- 禁止删除或弱化测试来让构建通过；测试失败先修根因。
