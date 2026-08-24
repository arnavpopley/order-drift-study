#!/bin/zsh
# Auto-resume classification after Gemini daily-quota reset (midnight Pacific).
# Retries every 30 min up to 8 times; generates audit worksheet on success.

REPO="/Users/arnavpopley/Documents/Default Project/order-drift-study"
LOG="$REPO/data/processed/classify_auto.log"

cd "$REPO" || exit 1
echo "=== auto-classify start $(date) ===" >> "$LOG"

for i in $(seq 1 8); do
    uv run python -u -m src.classify --rpm 2 >> "$LOG" 2>&1
    status=$?
    if [ $status -eq 0 ]; then
        echo "=== classify complete $(date) ===" >> "$LOG"
        uv run python -m src.audit --draw >> "$LOG" 2>&1
        osascript -e 'display notification "Classification done - audit worksheet ready" with title "Order Drift Study"' >/dev/null 2>&1
        exit 0
    fi
    echo "=== attempt $i failed (rc=$status), sleeping 30m $(date) ===" >> "$LOG"
    sleep 1800
done
echo "=== giving up after 8 attempts $(date) ===" >> "$LOG"
exit 1
