#!/usr/bin/env bash
# Install the US/KR fear & greed briefing skill + collector into Hermes and (optionally) schedule it.
#
#   bash scripts/install.sh                 # install skill + script only (smoke-tests the sources)
#   bash scripts/install.sh --cron          # also create the weekday 08:30 KST job (delivers to origin)
#   bash scripts/install.sh --cron telegram # pick a delivery target (origin|local|telegram|discord|platform:chat_id)
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SKILL_DIR="$HERMES_HOME/skills/research/market-sentiment-briefings"

CRON=0; DELIVER=origin
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cron) CRON=1; if [[ $# -gt 1 && "$2" != --* ]]; then DELIVER="$2"; shift; fi ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done

command -v hermes >/dev/null || { echo "hermes CLI not found — install Hermes Agent first"; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }

mkdir -p "$SKILL_DIR/scripts" "$HERMES_HOME/scripts"
cp -r "$SRC/SKILL.md" "$SRC/references" "$SKILL_DIR/"
cp "$SRC/scripts/fear_greed.py" "$SRC/scripts/install.sh" "$SKILL_DIR/scripts/"
cp "$SRC/scripts/fear_greed.py" "$HERMES_HOME/scripts/"
echo "✓ skill  → $SKILL_DIR"
echo "✓ script → $HERMES_HOME/scripts/fear_greed.py"

echo "… smoke test (fetches CNN, kospifgi, siglens, feargreed.co.kr)"
OUT="$(FG_STATE_DIR="$(mktemp -d)" python3 "$HERMES_HOME/scripts/fear_greed.py" --force)"
for src in "1. 미국 CNN" "2. 한국 kospifgi" ; do
  if sed -n "/## $src/,/^## /p" <<<"$OUT" | grep -q "데이터 수집 실패"; then echo "! $src: 수집 실패"; else echo "✓ $src"; fi
done
grep -q "siglens.io: 데이터 수집 실패" <<<"$OUT" && echo "! siglens: 수집 실패" || echo "✓ siglens"
grep -q "feargreed.co.kr: 데이터 수집 실패" <<<"$OUT" && echo "! feargreed.co.kr: 수집 실패" || echo "✓ feargreed.co.kr"

if [[ $CRON == 1 ]]; then
  # CNN settles ~06:00 KST, kospifgi publishes from 08:10 KST → 08:30 KST weekdays.
  TZNAME="$(python3 - <<'EOF'
import os, re
tz = os.environ.get("HERMES_TIMEZONE", "")
cfg = os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), "config.yaml")
if not tz and os.path.exists(cfg):
    m = re.search(r'^timezone:\s*["\']?([^"\'\s]+)', open(cfg, encoding="utf-8").read(), re.M)
    tz = m.group(1) if m else ""
if not tz:
    import time
    tz = "local:" + time.strftime("%z")
print(tz)
EOF
)"
  case "$TZNAME" in
    Asia/Seoul|Asia/Tokyo|local:+0900) SCHED="30 8 * * 1-5" ;;
    UTC|Etc/UTC|local:+0000) SCHED="30 23 * * 0-4" ;;
    *) echo "! Hermes timezone is '$TZNAME'. Set timezone: Asia/Seoul in config.yaml"
       echo "  or create the job manually at 08:30 KST on weekdays."; exit 1 ;;
  esac
  hermes cron create "$SCHED" "$(cat "$SRC/references/cron-prompt.md")" \
    --name "미국·한국 공포탐욕지수 일일 분석" --skill market-sentiment-briefings \
    --script fear_greed.py --deliver "$DELIVER"
  echo "✓ cron job created ($SCHED, tz=$TZNAME, deliver=$DELIVER). Check: hermes cron list"
fi
