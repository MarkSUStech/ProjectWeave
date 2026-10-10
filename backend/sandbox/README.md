# 远程执行与调试沙箱（P4.2b / P4.2c / P4.5a）

## 构建沙箱镜像（一次性）

```bash
# 仓库根目录执行
docker build -t projectweave-sandbox-python:3.12 backend/sandbox/python
docker build -t projectweave-sandbox-cpp:clang15-bookworm backend/sandbox/cpp
docker build -t projectweave-sandbox-cpp-debug:clang19-trixie backend/sandbox/cpp-debug
```

- **Python 镜像**：`python:3.12-slim` + pytest 8.x（唯一预装依赖），非 root（uid/gid 10001），无密钥。
- **C++ 运行镜像**：Debian bookworm 固定工具链（clang/clang++ 15.0.6、cmake 3.25.1、ninja 1.11.1、libstdc++ 12）+ python3（仅运行注入的执行驱动），同样非 root、无密钥。
- **C++ 调试镜像**（P4.5a）：Debian trixie（clang 19、**lldb 19.1.7 + lldb-dap**、cmake 3.31、ninja 1.12 + python3 驱动运行时）；与运行镜像分离，互不影响。

未构建镜像 / Docker 未运行时，`POST /api/v1/executions` 返回 **503** 与
修复提示，不伪造执行结果。

## 运行时隔离（每次执行一个一次性容器）

由 `backend/app/domains/executions/sandbox/docker_sandbox.py` 施加：

| 措施 | 参数 |
|---|---|
| 禁止网络 | `--network none` |
| 只读根文件系统 | `--read-only` + 唯一可写区 `/sandbox`（tmpfs，属主 10001） |
| 工作区执行策略 | **语言专属**（D34）：Python `noexec`；C++ `exec`（编译产物需执行，256MB tmpfs）——由服务端 `SandboxSpec.exec_workspace` 声明，客户端不可控 |
| 非 root | `--user 10001:10001` |
| 权限收紧 | `--cap-drop ALL` + `--security-opt no-new-privileges` |
| 资源上限 | `--memory 512m --cpus 1 --pids-limit 128` |
| 可追踪/可清理 | `--label pw.sandbox=1 --label pw.exec_id=<id>` + 确定性容器名 |
| 优雅终止 | `--stop-timeout 5`；超时/取消 kill 整个容器并 `docker rm -f` |

文件注入：项目文件 + manifest + 执行驱动打包为 gzip tar，经容器 **stdin**
解包到 `/sandbox/work`（不挂载宿主目录、不用 docker cp）。
程序 stdin 来自请求（随 manifest 一次性提交，非交互）。

服务启动时后台线程清理遗留容器（`pw.sandbox=1` 标签过滤）。

## C++ 执行约定（D35）

- 编译参数服务端固定：`-std=c++20 -O0 -g -Wall -Wextra -fdiagnostics-color=never`。
- 无 CMakeLists.txt：入口 + 全部非测试翻译单元 → clang++ 链接为真实可执行程序。
- 有 CMakeLists.txt（run 模式）：`cmake -G Ninja` 配置 + 构建包含入口源文件的目标
  （解析 `add_executable`，未命中回退"目标名 = 入口去扩展名"）。
- 测试：每个测试文件编译为独立可执行程序；**通过 = 退出 0 且有输出**；
  干净退出非零 = 断言失败；崩溃/超时/编译失败/空输出 = error（空测试不判通过）。

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
PW_SANDBOX_E2E=1 .venv/Scripts/python.exe -m pytest tests/test_executions_docker_e2e.py tests/test_executions_cpp_e2e.py -v
```

分别覆盖 Python（验收 A-G/J）与 C++（验收 A-I/K：单文件/多翻译单元/缺头文件
诊断/链接错误/stdin/超时清理/测试成败与空测试/CMake+Ninja/编译失败不报成功/
容器封锁/取消零遗留）。默认（无环境变量）跳过。


## 交互式调试沙箱（P4.5a，D36）

与一次性执行沙箱的差异：

- **长生命周期容器**：`sleep infinity` 常驻，构建/文件注入/DAP 通道均经
  `docker exec -i`（`pw.debug=1` 标签追踪）；
- **调试专用 seccomp**（`backend/sandbox/cpp-debug/seccomp-debug.json`）：
  上游 moby v28.0.1 默认 profile **仅移除 personality 的按值限制**（LLDB
  禁 ASLR 需要；ptrace 上游已允许），其余规则一字不动——只用于调试沙箱，
  **绝不用于普通执行沙箱**，绝不 --privileged / seccomp=unconfined；
- 其余隔离与执行沙箱一致：禁网、只读根、exec tmpfs（uid 10001 属主）、
  非 root、cap-drop ALL、no-new-privileges、memory/cpu/pids 限额；
- DAP 通道 = `docker exec -i <容器> lldb-dap`（stdio 直通，调试器与被调试
  程序同容器；调试器只调试自己启动的子进程，不接触宿主/服务端文件）；
- **资源回收三防线**：看门狗线程（默认空闲 600s / 硬上限 1800s，
  `PW_DEBUG_IDLE_TIMEOUT_SECONDS` / `PW_DEBUG_HARD_TIMEOUT_SECONDS` 可调）→
  服务启动清理遗留容器 + 悬挂会话行标记终止 → DAP 通道死亡即回收；
  轮询即活动——浏览器断连后自然进入空闲回收。

调试功能面向受控开发/教学环境（同下方安全边界声明），调试指令为结构化
白名单（continue/next/stepIn/stepOut/pause/stop/setBreakpoints），不透传
任意 LLDB 命令。

## Docker E2E 测试（选入）

```bash
cd backend
PW_SANDBOX_E2E=1 .venv/Scripts/python.exe -m pytest tests/test_executions_docker_e2e.py tests/test_executions_cpp_e2e.py tests/test_debugging_cpp_e2e.py -v
```

分别覆盖 Python 执行（A-G/J）、C++ 执行（A-I/K）与 C++ 调试
（A-H：断点暂停/单步/真实变量/递归栈/多文件断点/编译失败不启动调试器/
停止与超时清理）。默认（无环境变量）跳过。