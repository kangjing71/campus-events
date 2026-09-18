#!/usr/bin/env bash
# 启动校园共创服务（使用 conda campus-events 环境的 Python 3.12）
# 用法: ./scripts/run.sh [--port 端口] [--host 地址] [--public-base-url URL] [--demo]
#       PORT=端口 ./scripts/run.sh   （环境变量方式，优先级低于 --port）
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=/opt/miniconda3/envs/campus-events/bin/python
if [ ! -x "$PYTHON" ]; then
    echo "找不到 conda 环境 campus-events，请先创建: conda create -y -n campus-events python=3.12" >&2
    exit 1
fi

exec "$PYTHON" server.py --port "${PORT:-18765}" "$@"
