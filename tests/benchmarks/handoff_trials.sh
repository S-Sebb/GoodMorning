#!/bin/bash
# Live check for #253: one evening and one morning in each language, one at a time, on the
# production model. Each prints save-to-ready and save-to-session-idle seconds; ready should be ~0 s.
# Results: $OUT/results.txt (one line per trial); full logs stay in each trial's run directory.
set -u
cd "$(dirname "$0")/../.."
LOCK=/tmp/agent-locks/GoodMorning/live-trials.lock
OUT=/var/tmp/goodmorning-trials/$(basename "$PWD")/handoff
PY="uv run --no-project --with-requirements requirements/browser.txt python"
mkdir -p "$(dirname "$LOCK")" "$OUT"
exec 9>>"$LOCK"
flock -w 1800 9 || { echo "BLOCKED: live-trials lock held: $(cat "$LOCK")"; exit 1; }
echo "handoff_trials #253, PID $$, since $(date -Is)" > "$LOCK"
command -v uv >/dev/null || { echo "BLOCKED: uv is not installed"; exit 1; }
[ -f "${XDG_DATA_HOME:-$HOME/.local/share}/opencode/opencode.db" ] || { echo "BLOCKED: no OpenCode credential store"; exit 1; }

: > "$OUT/results.txt"
status=0
for case in evening-timing morning-timing; do for lang in en zh-CN; do
  name=h253-$case-$lang
  $PY tests/benchmarks/trial.py clean "$name" >/dev/null 2>&1
  $PY tests/benchmarks/trial.py start "$name" briefing_tone_live --language "$lang" --only "$case" >/dev/null
  $PY tests/benchmarks/trial.py wait "$name" --timeout 900 >/dev/null; code=$?
  log=$(ls /var/tmp/goodmorning-trials/"$(basename "$PWD")"/"$name".log 2>/dev/null)
  handoff=$(grep -h "handoff (s)" "$log" 2>/dev/null | tail -1)
  if [ $code -eq 0 ] && [ -n "$handoff" ]; then line="PASS $name: $handoff"
  elif [ $code -eq 2 ]; then line="FAIL $name: timed out; stopped"; $PY tests/benchmarks/trial.py stop "$name" >/dev/null 2>&1
  else line="FAIL $name: exit $code; $(tail -2 "$log" 2>/dev/null | tr '\n' ' ' | cut -c1-300)"; fi
  [ "${line%% *}" = PASS ] || status=1
  echo "$line" | tee -a "$OUT/results.txt"
done; done
exit $status
