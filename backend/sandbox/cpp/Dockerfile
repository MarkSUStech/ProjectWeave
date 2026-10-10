# ProjectWeave C++ 沙箱镜像（P4.2c，D34/D35）
#
# 构建：docker build -t projectweave-sandbox-cpp:clang15-bookworm backend/sandbox/cpp
#
# 工具链（Debian bookworm 固定版本，可追踪）：
# - clang/clang++ 15（含 libc++ 可选；默认链接 libstdc++ 12）
# - cmake 3.25 + ninja-build 1.11
# - python3（仅运行 ProjectWeave 注入的执行驱动，非用户依赖）
#
# 原则同 Python 镜像：非 root（10001）、无密钥、运行时只读根 + tmpfs。
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        clang-15 \
        libc++-dev \
        libstdc++-12-dev \
        cmake \
        ninja-build \
        python3 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/clang++-15 /usr/local/bin/clang++ \
    && ln -s /usr/bin/clang-15 /usr/local/bin/clang \
    && groupadd -g 10001 runner \
    && useradd -u 10001 -g 10001 -m -s /usr/sbin/nologin runner \
    && clang++ --version && cmake --version | head -1 && ninja --version

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001:10001
WORKDIR /sandbox
