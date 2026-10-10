# ProjectWeave Python 沙箱镜像（P4.2b，D32）
#
# 构建：docker build -t projectweave-sandbox-python:3.12 backend/sandbox/python
#
# 原则：
# - 固定 CPython 3.12 基础镜像，只预装 pytest（受控依赖集）；
# - 运行身份为非 root（uid/gid 10001，无登录 shell）；
# - 不内置任何密钥/服务端配置；运行时以 --read-only + tmpfs 启动（见 docker_sandbox.py）。
FROM python:3.12-slim

RUN groupadd -g 10001 runner \
    && useradd -u 10001 -g 10001 -m -s /usr/sbin/nologin runner

RUN pip install --no-cache-dir "pytest>=8.3,<9"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001:10001
WORKDIR /sandbox
