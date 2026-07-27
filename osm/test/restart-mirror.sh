#!/bin/sh
# pgrep -f "mirror.mjs" also matches the shell running this command, because the
# shell's own argv contains the string. A pidfile does not have that problem.
# PORT lets several mirrors run at once, one per suite.
cd "$(dirname "$0")"
PORT="${PORT:-8099}"
PIDFILE="mirror.$PORT.pid"
[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
sleep 1
PORT="$PORT" setsid nohup node mirror.mjs > "mirror.$PORT.log" 2>&1 < /dev/null &
echo $! > "$PIDFILE"
sleep 2
curl -s -o /dev/null -w "mirror($PORT)=%{http_code}\n" --noproxy '*' "http://127.0.0.1:$PORT/"
