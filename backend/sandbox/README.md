# 远程执行沙箱（P4.2b）

## 构建 Python 沙箱镜像（一次性）

```bash
# 仓库根目录执行
docker build -t projectweave-sandbox-python:3.12 backend/sandbox/python
```

镜像内容：`python:3.12-slim` + pytest 8.x（唯一预装依赖），非 root 运行用户
（uid/gid 10001，无登录 shell），不内置任何密钥或服务端配置。

未构建镜像 / Docker 未运行时，`POST /api/v1/executions` 返回 **503** 与
修复提示，不伪造执行结果。

## 运行时隔离（每次执行一个一次性容器）

由 `backend/app/domains/executions/sandbox/docker_sandbox.py` 施加：

| 措施 | 参数 |
|---|---|
| 禁止网络 | `--network none` |
| 只读根文件系统 | `--read-only` + 唯一可写区 `/sandbox`（tmpfs，`noexec`，64MB，属主 10001） |
| 非 root | `--user 10001:10001` |
| 权限收紧 | `--cap-drop ALL` + `--security-opt no-new-privileges` |
| 资源上限 | `--memory 512m --cpus 1 --pids-limit 128` |
| 可追踪/可清理 | `--label pw.sandbox=1 --label pw.exec_id=<id>` + 确定性容器名 |
| 优雅终止 | `--stop-timeout 5`；超时/取消 kill 整个容器并 `docker rm -f` |

文件注入：项目文件 + manifest + 执行驱动打包为 gzip tar，经容器 **stdin**
解包到 `/sandbox/work`（不挂载宿主目录、不用 docker cp）。
程序 stdin 来自请求（随 manifest 一次性提交，非交互）。

服务启动时后台线程清理遗留容器（`pw.sandbox=1` 标签过滤）。

## 安全边界声明（重要）

普通 Docker 容器**不是**对抗恶意多租户的完全可靠隔离边界。本沙箱面向
开发/教学场景的失误代码隔离（防误操作、防资源耗尽、防意外访问宿主），
不承诺对抗蓄意容器逃逸。公开的多租户不可信执行服务应接入 gVisor
（`--runtime=runsc`）或微虚拟机（Firecracker/Kata），届时实现同一
`SandboxManager` 协议即可，上层（执行服务/语言运行器/API）零改动。

执行控制器（FastAPI 进程）与用户代码运行权限完全分离：用户代码只在
容器内以 uid 10001 运行，接触不到 API 密钥、数据库凭据或服务端配置
（环境变量白名单：仅 `PYTHONDONTWRITEBYTECODE`/`PYTHONUNBUFFERED`/
`HOME`/`TMPDIR`）。

## 相关配置（`PW_` 前缀环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PW_EXECUTION_ENABLED` | `true` | 总开关（false → 422） |
| `PW_EXECUTION_MAX_TIMEOUT_MS` | `30000` | 单次执行超时上限 |
| `PW_EXECUTION_MAX_CONCURRENT` | `2` | 并发沙箱数（超出排队） |
| `PW_EXECUTION_MAX_FILES` | `200` | 单次执行文件数上限 |
| `PW_EXECUTION_MAX_TOTAL_BYTES` | `4194304` | 文件总大小上限 |
| `PW_EXECUTION_MAX_STDIN_CHARS` | `65536` | stdin 上限 |
| `PW_EXECUTION_OUTPUT_MAX_CHARS` | `262144` | stdout/stderr 各自保留上限（超出截断） |
| `PW_EXECUTION_MEMORY_MB` / `PW_EXECUTION_CPUS` / `PW_EXECUTION_PIDS_LIMIT` | `512` / `1.0` / `128` | 容器资源限制 |

## Docker E2E 测试（选入）

```bash
cd backend
PW_SANDBOX_E2E=1 .venv/Scripts/python.exe -m pytest tests/test_executions_docker_e2e.py -v
```

覆盖任务验收场景 A-G/J（hello 运行 / 多文件 import / stdin / pytest 成败 /
收集错误 / 无限循环超时清理 / 宿主文件与网络封锁 / 只读根 / 取消与零遗留）。
默认（无环境变量）跳过，CI/无 Docker 环境不依赖。
