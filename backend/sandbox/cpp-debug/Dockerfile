# ProjectWeave C++ 调试沙箱镜像（P4.5a，D36）
#
# 构建：docker build -t projectweave-sandbox-cpp-debug:clang19-trixie backend/sandbox/cpp-debug
#
# 工具链（Debian trixie 固定版本，可追踪）：
# - clang/clang++ 19 + libstdc++ 13（调试构建：-O0 -g）
# - lldb 19 + lldb-dap（Debug Adapter Protocol 服务端，会话内调试自有子进程）
# - cmake 3.31 + ninja 1.12
# - python3（仅运行 ProjectWeave 注入的构建/引导驱动）
#
# 与普通 C++ 运行镜像（bookworm/clang-15）分离：调试会话在自己的镜像内
# 编译并调试，普通执行沙箱策略（noexec 等）零改动。
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        clang-19 \
        lldb-19 \
        libstdc++-14-dev \
        libc++-dev \
        cmake \
        ninja-build \
        python3 \
    && rm -rf /var/lib/apt/lists/* \
    && for b in clang clang++ lldb lldb-dap; do \
        ln -s /usr/bin/$b-19 /usr/local/bin/$b 2>/dev/null || true; \
    done \
    && groupadd -g 10001 runner \
    && useradd -u 10001 -g 10001 -m -s /usr/sbin/nologin runner \
    && clang++ --version | head -1 && lldb --version | head -1 && lldb-dap --help 2>&1 | head -1 && cmake --version | head -1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001:10001
WORKDIR /sandbox
