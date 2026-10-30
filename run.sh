#!/usr/bin/env bash
# Quick launcher for Crypto Futures Chart Scanner & Telegram Alert Bot
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "⚡ Creating Python virtual environment..."
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
fi

source venv/bin/activate

if [ ! -f "config.json" ]; then
    echo "📋 Copying config.example.json -> config.json"
    cp config.example.json config.json
    echo "👉 Vui lòng điền 'telegram_bot_token' và 'telegram_chat_id' trong file config.json nếu muốn nhận alert qua Telegram!"
fi

echo "=================================================================="
echo "🎯 BINANCE FUTURES AUTO-CHART SCANNER & TELEGRAM ALERT BOT"
echo "=================================================================="
echo "Options:"
echo "  1) Quét 1 vòng thử nghiệm (Scan Once & Save Charts)"
echo "  2) Chạy ngầm liên tục 24/7 (Daemon Loop)"
echo "  3) Chạy toàn bộ Unit Tests (TDD Suite)"
echo "=================================================================="

case "$1" in
    loop|--loop)
        exec python3 main.py --loop
        ;;
    test|--test)
        exec python3 -m pytest tests/ -v
        ;;
    *)
        exec python3 main.py "$@"
        ;;
esac
