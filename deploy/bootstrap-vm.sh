#!/usr/bin/env bash
#
# bootstrap-vm.sh — Creates a Hetzner VPS, bootstraps it via cloud-init, and runs the BCR pipeline.
#
# Usage:
#   bash deploy/bootstrap-vm.sh [workshop_id] [server_name]
#
# Defaults: workshop_id=32489, server_name=bcr-agent-$(date +%s)
#
# Requires: ~/.config/bcr-deploy/secrets (HCLOUD_TOKEN, ZAI_API_KEY, BOT_NSEC_HEX)
# Requires: hcloud CLI installed
# Requires: SSH key registered with Hetzner (uses 'espen@mac' or HCLOUD_SSH_KEY env var)
#
set -euo pipefail

SECRETS_FILE="${HOME}/.config/bcr-deploy/secrets"
WORKSHOP_ID="${1:-32489}"
SERVER_NAME="${2:-bcr-agent-$(date +%s)}"
SSH_KEY="${HCLOUD_SSH_KEY:-espen@mac}"
SERVER_TYPE="cpx22"
IMAGE="ubuntu-24.04"
LOCATION="fsn1"

if [ ! -f "$SECRETS_FILE" ]; then
    echo "ERROR: secrets file not found at $SECRETS_FILE"
    exit 1
fi

source "$SECRETS_FILE"
export HCLOUD_TOKEN

CLOUDINIT_FILE="$(mktemp /tmp/bcr-cloudinit-XXXXXX.yaml)"

cat > "$CLOUDINIT_FILE" << CLOUDINIT
#cloud-config

package_update: true
packages:
  - python3
  - python3-pip
  - git
  - tmux
  - curl
  - jq
  - ca-certificates
  - build-essential

write_files:
  - path: /opt/bcr-agent-config/bot_nsec
    permissions: '0600'
    owner: root:root
    content: "${BOT_NSEC_HEX}"

  - path: /opt/bcr-agent-config/opencode.json
    permissions: '0600'
    owner: root:root
    content: |
      {
        "\$schema": "https://opencode.ai/config.json",
        "provider": {
          "zai": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Z.AI Coding Plan",
            "options": {
              "baseURL": "https://api.z.ai/api/coding/paas/v4",
              "apiKey": "${ZAI_API_KEY}"
            },
            "models": {
              "glm-4.6": { "name": "GLM-4.6" }
            }
          }
        }
      }

  - path: /opt/bcr-agent-config/config.json
    permissions: '0644'
    content: |
      {
        "llm": {
          "provider": "opencode",
          "opencode_path": "/usr/local/bin/opencode",
          "model": "zai/glm-4.6",
          "timeout_seconds": 300
        },
        "agent": {
          "max_diff_chars": 15000,
          "max_irc_chars": 8000,
          "max_github_chars": 4000,
          "previous_answers_context": 4
        }
      }

  - path: /etc/systemd/system/bcr-self-destruct.service
    content: |
      [Unit]
      Description=BCR Agent Self-Destruct
      After=network.target
      [Service]
      Type=oneshot
      ExecStart=/sbin/shutdown -h now "BCR Agent: 2-hour timeout reached"
      [Install]
      WantedBy=multi-user.target

  - path: /etc/systemd/system/bcr-self-destruct.timer
    content: |
      [Unit]
      Description=Self-destruct after 2 hours
      [Timer]
      OnBootSec=2h
      AccuracySec=1min
      Unit=bcr-self-destruct.service
      [Install]
      WantedBy=timers.target

runcmd:
  - set -ex

  # --- Install Go (for nak) ---
  - curl -sL https://go.dev/dl/go1.23.4.linux-amd64.tar.gz | tar -C /usr/local -xzf -
  - export PATH=\$PATH:/usr/local/go/bin:/root/go/bin
  - go install github.com/fiatjaf/nak@latest
  - cp /root/go/bin/nak /usr/local/bin/nak || echo "nak install failed, continuing"

  # --- Install opencode ---
  - curl -fsSL https://opencode.ai/install | bash
  - ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode || true

  # --- Clone repo ---
  - git clone https://github.com/Amperstrand/bcr-agent.git /opt/bcr-agent

  # --- Copy config files ---
  - cp /opt/bcr-agent-config/opencode.json /opt/bcr-agent/opencode.json
  - cp /opt/bcr-agent-config/config.json /opt/bcr-agent/config.json
  - chmod 600 /opt/bcr-agent/opencode.json

  # --- Set up self-destruct timer ---
  - systemctl enable --now bcr-self-destruct.timer

  # --- Scrub cloud-init data (remove cached secrets) ---
  - rm -rf /var/lib/cloud/instances/*
  - cloud-init clean --logs

  # --- Start pipeline in tmux ---
  - |
    tmux new-session -d -s bcr-agent "cd /opt/bcr-agent && export PATH=\$PATH:/usr/local/go/bin:/root/go/bin && python3 run.py full ${WORKSHOP_ID} --publish --nsec-file /opt/bcr-agent-config/bot_nsec 2>&1 | tee /var/log/bcr-agent.log"

  - echo "BCR Agent pipeline started in tmux session 'bcr-agent'"
  - echo "Attach with: tmux attach -t bcr-agent"
  - echo "Logs at: /var/log/bcr-agent.log"

CLOUDINIT

echo "=== Creating Hetzner VM ==="
echo "  Name: ${SERVER_NAME}"
echo "  Type: ${SERVER_TYPE} (2 vCPU, 4GB RAM, 80GB disk)"
echo "  Image: ${IMAGE}"
echo "  Location: ${LOCATION}"
echo "  SSH Key: ${SSH_KEY}"
echo "  Workshop: ${WORKSHOP_ID}"
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
echo "  Name: ${SERVER_NAME}"
echo "  IP: ${IP}"
echo "  Self-destruct: 2 hours after boot"
echo ""
echo "=== Connect ==="
echo "  SSH:  ssh root@${IP}"
echo "  Tmux: ssh root@${IP} -t 'tmux attach -t bcr-agent'"
echo "  Logs: ssh root@${IP} 'tail -f /var/log/bcr-agent.log'"
echo ""
echo "=== Cleanup ==="
echo "  Delete: hcloud server delete ${SERVER_NAME}"
echo "  Auto-cleanup cron: deploy/cleanup-vms.sh"
