#!/usr/bin/env bash
#
# bootstrap-vm.sh — Creates a Hetzner cpx31 VPS and runs the autonomous BCR agent.
#
# Usage:
#   bash deploy/bootstrap-vm.sh [workshop_id] [server_name] [model]
#
# Defaults: workshop_id=33300, server_name=bcr-agent-$(date +%s), model=zai/glm-4.6
#
# Requires: ~/.config/bcr-deploy/secrets (HCLOUD_TOKEN, ZAI_API_KEY, BOT_NSEC_HEX)
# Requires: hcloud CLI installed
# Requires: SSH key registered with Hetzner (uses 'espen@mac' or HCLOUD_SSH_KEY env var)
#
set -euo pipefail

SECRETS_FILE="${HOME}/.config/bcr-deploy/secrets"
WORKSHOP_ID="${1:-33300}"
SERVER_NAME="${2:-bcr-agent-$(date +%s)}"
MODEL="${3:-zai/glm-4.6}"
SSH_KEY="${HCLOUD_SSH_KEY:-espen@mac}"
SERVER_TYPE="cpx32"
IMAGE="ubuntu-24.04"
LOCATION="fsn1"

if [ ! -f "$SECRETS_FILE" ]; then
    echo "ERROR: secrets file not found at $SECRETS_FILE"
    exit 1
fi

source "$SECRETS_FILE"
export HCLOUD_TOKEN

COMMIT_HASH=$(git rev-parse --short HEAD)
COMMIT_FULL=$(git rev-parse HEAD)

CLOUDINIT_FILE="/tmp/bcr-cloudinit-$$.yaml"

cat > "$CLOUDINIT_FILE" << CLOUDINIT
#cloud-config

package_update: true
packages:
  - git
  - tmux
  - curl

write_files:
  - path: /opt/bcr-agent-config/bot_nsec
    permissions: '0600'
    owner: root:root
    content: "${BOT_NSEC_HEX}"

  - path: /opt/bcr-agent-config/env
    permissions: '0600'
    owner: root:root
    content: |
      export ZAI_API_KEY="${ZAI_API_KEY}"
      export WORKSHOP_ID="${WORKSHOP_ID}"
      export MODEL="${MODEL}"
      export BCR_COMMIT="${COMMIT_HASH}"
      export BCR_COMMIT_FULL="${COMMIT_FULL}"
      export SERVER_TYPE="${SERVER_TYPE}"
      export MODE="autonomous"

runcmd:
  - set -ex
  - git clone https://github.com/Amperstrand/bcr-agent.git /opt/bcr-agent
  - cd /opt/bcr-agent && git checkout ${COMMIT_HASH}
  - bash -c 'source /opt/bcr-agent-config/env && bash /opt/bcr-agent/deploy/vm-bootstrap-v3.sh'
  - rm -rf /var/lib/cloud/instances/*
  - cloud-init clean --logs

CLOUDINIT

echo "=== Creating Hetzner VM ==="
echo "  Name:      ${SERVER_NAME}"
echo "  Type:      ${SERVER_TYPE} (2 vCPU, 8GB RAM)"
echo "  Commit:    ${COMMIT_HASH}"
echo "  Workshop:  ${WORKSHOP_ID}"
echo "  Model:     ${MODEL}"
echo "  Mode:      autonomous"
echo ""

hcloud server create \
    --name "$SERVER_NAME" \
    --type "$SERVER_TYPE" \
    --image "$IMAGE" \
    --location "$LOCATION" \
    --ssh-key "$SSH_KEY" \
    --label "bcr-agent=true" \
    --user-data-from-file "$CLOUDINIT_FILE" \
    2>&1

rm -f "$CLOUDINIT_FILE"

echo ""
echo "=== VM Created ==="
IP=$(hcloud server ip "$SERVER_NAME" 2>/dev/null || echo "unknown")
echo "  Name:      ${SERVER_NAME}"
echo "  IP:        ${IP}"
echo "  Commit:    ${COMMIT_HASH}"
echo "  Self-destruct: 3 hours (via vm-bootstrap-v3.sh)"
echo ""
echo "=== Connect ==="
echo "  SSH:   ssh root@${IP}"
echo "  Tmux:  ssh root@${IP} -t 'tmux attach -t bcr-agent'"
echo "  Logs:  ssh root@${IP} 'tail -f /var/log/bcr-agent.log'"
echo ""
echo "=== Cleanup ==="
echo "  Delete: hcloud server delete ${SERVER_NAME}"
echo "  Auto-cleanup cron: deploy/cleanup-vms.sh (3h max)"
