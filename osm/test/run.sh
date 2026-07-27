#!/bin/sh
# Every suite against its own mirror, all at once. They are independent — each
# picks its own scenario through /_mode and keeps its own in-memory
# OpenStreetMap — so the wall clock is the slowest one rather than the sum.
#
#   ./run.sh              all four
#   ./run.sh 03-tags      just one, on the default port
#   RECORD=1 ./run.sh     re-fetch the upstream fixtures instead of replaying
cd "$(dirname "$0")" || exit 1

SUITES="${*:-01-flow 02-data 03-tags 04-upload}"
PORT_BASE=8099
rc=0
pids=""
i=0

# Started together: each one sleeps three seconds proving it came up, and doing
# that in turn put twelve seconds in front of every run.
starts=""
for s in $SUITES; do
  port=$((PORT_BASE + i))
  PORT=$port ./restart-mirror.sh > /dev/null &
  starts="$starts $!"
  i=$((i + 1))
done
# shellcheck disable=SC2086
wait $starts

i=0
for s in $SUITES; do
  port=$((PORT_BASE + i))
  ( TARGET="http://127.0.0.1:$port/" node "$s.mjs" > ".$s.out" 2>&1; echo $? > ".$s.rc" ) &
  pids="$pids $!"
  i=$((i + 1))
done
# shellcheck disable=SC2086
wait $pids

for s in $SUITES; do
  cat ".$s.out"
  [ "$(cat ".$s.rc")" = "0" ] || rc=1
  rm -f ".$s.out" ".$s.rc"
done

i=0
for s in $SUITES; do
  port=$((PORT_BASE + i))
  [ -f "mirror.$port.pid" ] && kill "$(cat "mirror.$port.pid")" 2>/dev/null
  rm -f "mirror.$port.pid"
  i=$((i + 1))
done

echo ""
[ $rc = 0 ] && echo "==> everything passed" || echo "==> SOMETHING FAILED"
exit $rc
