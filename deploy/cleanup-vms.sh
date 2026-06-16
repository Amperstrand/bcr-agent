#!/usr/bin/env bash
#
# cleanup-vms.sh — Local cron job: delete bcr-agent VMs older than MAX_UPTIME seconds.
#
# ONLY touches servers labeled bcr-agent=true. Your other Hetzner VMs are safe.
#
# Install as cron:
#   crontab -e
#   */5 * * * * /Users/macbook/src/bcr-agent/deploy/cleanup-vms.sh >> ~/.config/bcr-deploy/cleanup.log 2>&1
#
# Or with launchd (macOS):
#   See deploy/com.bcr-agent.cleanup.plist template

set -euo pipefail

SECRETS_FILE="${HOME}/.config/bcr-deploy/secrets"
MAX_UPTIME_SECONDS="${BCR_MAX_UPTIME:-7200}"  # 2 hours default
LABEL="bcr-agent=true"

if [ ! -f "$SECRETS_FILE" ]; then
    echo "$(date -Iseconds) ERROR: secrets file not found at $SECRETS_FILE"
    exit 1
fi

source "$SECRETS_FILE"
export HCLOUD_TOKEN

if ! command -v hcloud &> /dev/null; then
    echo "$(date -Iseconds) ERROR: hcloud CLI not found"
    exit 1
fi

NOW=$(date +%s)

SERVERS_JSON=$(hcloud server list --label-selector "$LABEL" -o json 2>/dev/null || echo "[]")

if [ "$SERVERS_JSON" = "[]" ]; then
    exit 0
fi

COUNT=$(echo "$SERVERS_JSON" | jq length)
for i in $(seq 0 $((COUNT - 1))); do
    SERVER_ID=$(echo "$SERVERS_JSON" | jq -r ".[$i].id")
    SERVER_NAME=$(echo "$SERVERS_JSON" | jq -r ".[$i].name")
    CREATED=$(echo "$SERVERS_JSON" | jq -r ".[$i].created")

    CREATED_EPOCH=$(date -jf "%Y-%m-%dT%H:%M:%SZ" "${CREATED%%.*}Z" +%s 2>/dev/null || \
                    date -d "$CREATED" +%s 2>/dev/null || echo 0)

    if [ "$CREATED_EPOCH" -eq 0 ]; then
        echo "$(date -Iseconds) WARN: could not parse created date for $SERVER_NAME ($SERVER_ID), skipping"
        continue
    fi

    AGE=$((NOW - CREATED_EPOCH))

    if [ "$AGE" -gt "$MAX_UPTIME_SECONDS" ]; then
        echo "$(date -Iseconds) DELETE: $SERVER_NAME (id=$SERVER_ID) uptime=${AGE}s > ${MAX_UPTIME_SECONDS}s"
        hcloud server delete "$SERVER_ID"
        echo "$(date -Iseconds) DELETED: $SERVER_NAME"
    else
        echo "$(date -Iseconds) OK: $SERVER_NAME uptime=${AGE}s (< ${MAX_UPTIME_SECONDS}s)"
    fi
done
