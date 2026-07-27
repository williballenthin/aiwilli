#!/bin/sh
# The sprite proxy drops every few hours; this brings it back without touching
# the invoking shell (pgrep -f would match this script's own argv).
cd "$(dirname "$0")"
[ -f tunnel.pid ] && kill "$(cat tunnel.pid)" 2>/dev/null
sleep 1
KEY="${SPRITES_API_KEY:-$(env | sed -n 's/^\(export \)\?SPRITES_API_KEY=//p')}"
SPRITES_API_KEY="$KEY" setsid nohup sprite proxy 8080 -s osm > tunnel.log 2>&1 < /dev/null &
echo $! > tunnel.pid
sleep 6
curl -s -o /dev/null -w "tunnel=%{http_code}\n" --noproxy '*' http://127.0.0.1:8080/
