#!/bin/bash
# Bot Service Manager
# Usage: ./bot_service.sh {start|stop|restart|status|logs}

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="${BOT_DIR}/bot.pid"
LOG_FILE="${BOT_DIR}/bot.log"

start() {
    if [ -f "${PID_FILE}" ] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
        echo "Bot is already running (PID: $(cat "${PID_FILE}"))"
        return 1
    fi

    cd "${BOT_DIR}"
    source venv/bin/activate
    nohup python bot.py >> "${LOG_FILE}" 2>&1 &
    echo $! > "${PID_FILE}"
    sleep 2

    if kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
        echo "Bot started (PID: $(cat "${PID_FILE}"))"
        echo "Logs: ${LOG_FILE}"
    else
        echo "Failed to start bot"
        rm -f "${PID_FILE}"
        return 1
    fi
}

stop() {
    if [ ! -f "${PID_FILE}" ]; then
        echo "Bot is not running (no PID file)"
        pkill -f "python.*bot.py" 2>/dev/null
        return 0
    fi

    PID=$(cat "${PID_FILE}")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        sleep 2
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID"
        fi
        echo "Bot stopped (was PID: $PID)"
    else
        echo "Bot was not running"
    fi
    rm -f "${PID_FILE}"
}

restart() {
    stop
    sleep 1
    start
}

status() {
    if [ -f "${PID_FILE}" ] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
        PID=$(cat "${PID_FILE}")
        echo "Bot is running (PID: $PID)"
        echo "Uptime: $(ps -o etime= -p "$PID" | xargs)"
    else
        echo "Bot is not running"
        [ -f "${PID_FILE}" ] && rm -f "${PID_FILE}"
    fi
}

logs() {
    if [ -f "${LOG_FILE}" ]; then
        tail -f "${LOG_FILE}"
    else
        echo "No log file found"
    fi
}

case "$1" in
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    logs)    logs ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
