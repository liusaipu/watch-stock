#!/bin/sh
# 股票行情监视器 macOS / Linux 启动器
exec python3 "$(dirname "$0")/watch_quotes.py" "$@"
