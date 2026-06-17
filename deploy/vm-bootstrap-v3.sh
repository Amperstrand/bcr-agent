#!/bin/bash
set -ex

# BCR Agent VM Bootstrap v3
# Sets up a Hetzner cpx31 VM for an autonomous opencode agent session.
# The agent reviews a Bitcoin Core PR, then results are collected & published.
#
# Required env vars:
#   ZAI_API_KEY       — API key for z.ai (GLM models + MCP tools)
#   WORKSHOP_ID       — Bitcoin Core PR Review Club workshop ID (default: 33300)
#   MODEL             — opencode model string (default: zai/glm-4.6)
#   BOT_NSEC_HEX      — Nostr private key (hex) for publishing

export HOME="${HOME:-/root}"
export PATH=$PATH:/usr/local/go/bin:/root/go/bin:/root/.cargo/bin

WORKSHOP_ID="${WORKSHOP_ID:-33300}"
MODEL="${MODEL:-zai/glm-4.6}"
NPUB_HEX="9a515b0f08d554b582e54202c7ca0e6ee56d81559957cbf9b40047d391b95fd5"

echo "=== BCR Agent VM Bootstrap v3 ==="
echo "  Workshop: ${WORKSHOP_ID}"
echo "  Model:    ${MODEL}"
echo ""

# Ensure nsec file has content (cloud-init write_files can produce empty files)
if [ -n "${BOT_NSEC_HEX:-}" ] && [ ! -s /opt/bcr-agent-config/bot_nsec ]; then
    mkdir -p /opt/bcr-agent-config
    echo -n "${BOT_NSEC_HEX}" > /opt/bcr-agent-config/bot_nsec
    chmod 600 /opt/bcr-agent-config/bot_nsec
    echo "  Wrote nsec from env (${#BOT_NSEC_HEX} chars)"
fi

# ---------------------------------------------------------------------------
echo "=== [1/14] Installing system dependencies (incl. Bitcoin Core build deps) ==="
apt-get update -qq
apt-get install -y -qq \
    build-essential cmake pkg-config libssl-dev libboost-all-dev libsqlite3-dev libevent-dev \
    autoconf automake libtool bsdmainutils \
    python3 python3-pip git tmux curl jq ca-certificates sqlite3 \
    fuse3 libfuse3-dev \
    nodejs npm clang-18 llvm-18 \
    >/dev/null 2>&1

# ---------------------------------------------------------------------------
echo "=== [2/14] Installing Go + nak (Nostr publishing) ==="
if [ ! -d /usr/local/go ]; then
    curl -sL https://go.dev/dl/go1.23.4.linux-amd64.tar.gz | tar -C /usr/local -xzf -
fi
export PATH=$PATH:/usr/local/go/bin
go install github.com/fiatjaf/nak@latest 2>&1 || echo "WARN: nak install failed"
cp /root/go/bin/nak /usr/local/bin/nak 2>/dev/null || true

# ---------------------------------------------------------------------------
echo "=== [3/14] Installing Rust (for blossomfs) ==="
if [ ! -f /root/.cargo/bin/cargo ]; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y >/dev/null 2>&1
fi
source /root/.cargo/env 2>/dev/null || true

# ---------------------------------------------------------------------------
echo "=== [4/14] Building blossomfs ==="
if [ ! -f /opt/blossomfs/target/release/blossomfs ]; then
    git clone https://github.com/Amperstrand/blossomfs.git /opt/blossomfs
    cd /opt/blossomfs
    cargo build --release 2>&1 | tail -5
fi
BLOSSOMFS_BIN="/opt/blossomfs/target/release/blossomfs"

# ---------------------------------------------------------------------------
echo "=== [5/14] Installing opencode ==="
curl -fsSL https://opencode.ai/install | bash
ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode 2>/dev/null || true

# ---------------------------------------------------------------------------
echo "=== [6/14] Cloning bcr-agent ==="
rm -rf /opt/bcr-agent
git clone https://github.com/Amperstrand/bcr-agent.git /opt/bcr-agent
cp /opt/bcr-agent-config/config.json /opt/bcr-agent/config.json 2>/dev/null || true

# ---------------------------------------------------------------------------
echo "=== [6b] Capturing version and machine info ==="
BCR_VERSION="${BCR_COMMIT:-$(cd /opt/bcr-agent && git rev-parse --short HEAD)}"
CPU_CORES=$(nproc)
RAM_TOTAL=$(free -h | awk '/^Mem:/{print $2}')
DISK_TOTAL=$(df -h / | awk 'NR==2{print $2}')
MACHINE_SPECS="${SERVER_TYPE:-unknown}, ${CPU_CORES} vCPU, ${RAM_TOTAL} RAM"
echo "  BCR Version:  ${BCR_VERSION}"
echo "  Machine:      ${MACHINE_SPECS}"
echo "  Mode:         ${MODE:-autonomous}"

# ---------------------------------------------------------------------------
echo "=== [7/14] Cloning bitcoin (review-club fork) at PR branch ==="
mkdir -p /workspace
if [ ! -d /workspace/bitcoin ]; then
    git clone https://github.com/bitcoin-core-review-club/bitcoin.git /workspace/bitcoin
fi
cd /workspace/bitcoin
git fetch origin "pr${WORKSHOP_ID}" 2>/dev/null || true
git checkout "pr${WORKSHOP_ID}" 2>/dev/null || echo "WARN: branch pr${WORKSHOP_ID} not found, staying on default"

# ---------------------------------------------------------------------------
echo "=== [8/14] Copying opencode.json with MCP tools ==="
# Replace the ${ZAI_API_KEY} placeholder with the actual key
sed "s|\${ZAI_API_KEY}|${ZAI_API_KEY}|g" \
    /opt/bcr-agent/deploy/vm-opencode.json > /workspace/opencode.json
chmod 600 /workspace/opencode.json

# ---------------------------------------------------------------------------
echo "=== [9/14] Pre-scraping workshop data (best-effort) ==="
cd /opt/bcr-agent
python3 -c "
import sys, json, os
sys.path.insert(0, '.')
try:
    from scraper import scrape_workshop
    data = scrape_workshop('${WORKSHOP_ID}')
    with open('/workspace/workshop.json', 'w') as f:
        json.dump(data, f, indent=2)
    print(f'  Workshop data saved: {len(data.get(\"questions\", []))} questions')
except Exception as e:
    print(f'  WARN: Pre-scrape failed: {e}')
    print('  Agent will need to scrape itself.')
" || echo "WARN: Pre-scrape failed, continuing"

# ---------------------------------------------------------------------------
echo "=== [10/14] Creating results directory ==="
mkdir -p /workspace/results

# ---------------------------------------------------------------------------
echo "=== [11/14] Mounting blossomfs (RW) ==="
mkdir -p /mnt/blossomfs

# Write nsec hex to temp file for bech32 conversion
echo -n "${BOT_NSEC_HEX}" > /opt/bcr-agent-config/bot_nsec 2>/dev/null || \
    echo -n "${BOT_NSEC_HEX}" > /tmp/bot_nsec
NSEC_FILE="/opt/bcr-agent-config/bot_nsec"
[ -f "$NSEC_FILE" ] || NSEC_FILE="/tmp/bot_nsec"
HEXKEY=$(cat "$NSEC_FILE" | tr -d ' \n')

# Convert hex nsec to bech32 using Python
NSEC_BECH32=$(python3 -c "
CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
def bech32_polymod(values):
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk
def bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]
def bech32_create_checksum(hrp, data):
    values = bech32_hrp_expand(hrp) + data
    polymod = bech32_polymod(values + [0,0,0,0,0,0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
def convertbits(data, frombits, tobits, pad=True):
    acc = 0; bits = 0; ret = []; maxv = (1 << tobits) - 1; max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits): return None
        acc = ((acc << frombits) | value) & max_acc; bits += frombits
        while bits >= tobits: bits -= tobits; ret.append((acc >> bits) & maxv)
    if pad and bits: ret.append((acc << (tobits - bits)) & maxv)
    return ret
data = bytes.fromhex('$HEXKEY')
data5 = convertbits(data, 8, 5)
checksum = bech32_create_checksum('nsec', data5)
print('nsec1' + ''.join([CHARSET[d] for d in data5 + checksum]))
")
echo "$NSEC_BECH32" > /opt/bcr-agent-config/nsec_bech32.txt
chmod 600 /opt/bcr-agent-config/nsec_bech32.txt
echo "  nsec (bech32): ${NSEC_BECH32:0:20}..."

$BLOSSOMFS_BIN mount \
    --pubkey "$NPUB_HEX" \
    --server "https://blossom.psbt.me" \
    --nsec-file /opt/bcr-agent-config/nsec_bech32.txt \
    --read-only false \
    --mountpoint /mnt/blossomfs \
    --daemon || echo "WARN: blossomfs mount failed, continuing without archive"

sleep 2

BLOSSOMFS_WRITE_PATH="/mnt/blossomfs/public/${NPUB_HEX}/servers/blossom.psbt.me/by-sha256"
mkdir -p "$BLOSSOMFS_WRITE_PATH" 2>/dev/null || true

# ---------------------------------------------------------------------------
echo "=== [12/14] Setting up self-destruct timer (3h) ==="
cat > /etc/systemd/system/bcr-self-destruct.service << 'EOF'
[Unit]
Description=BCR Agent Self-Destruct
After=network-target
[Service]
Type=oneshot
ExecStart=/sbin/shutdown -h now "BCR Agent: 3-hour timeout reached"
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/bcr-self-destruct.timer << 'EOF'
[Unit]
Description=Self-destruct after 4 hours
[Timer]
OnBootSec=4h
AccuracySec=1min
Unit=bcr-self-destruct.service
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now bcr-self-destruct.timer
echo "  Timer active. VM shuts down in 4 hours."

# ---------------------------------------------------------------------------
echo "=== [13/14] Starting autonomous agent session in tmux ==="
# The agent runs opencode with the autonomous agent prompt.
# After it finishes, the collection/publish script runs automatically.
tmux new-session -d -s bcr-agent "
cd /opt/bcr-agent && \
export PATH=\$PATH:/usr/local/go/bin:/root/go/bin && \
export PYTHONUNBUFFERED=1 && \
export ZAI_API_KEY='${ZAI_API_KEY}' && \
export WORKSHOP_ID='${WORKSHOP_ID}' && \
export MODEL='${MODEL}' && \
export NSEC_FILE='/opt/bcr-agent-config/bot_nsec' && \
export BLOSSOMFS_MOUNT='/mnt/blossomfs' && \
export BCR_VERSION='${BCR_VERSION}' && \
export MACHINE_SPECS='${MACHINE_SPECS}' && \
export MODE='${MODE:-autonomous}' && \
opencode run \
  --model '${MODEL}' \
  --dangerously-skip-permissions \
  --dir /workspace \
  \"\$(cat /opt/bcr-agent/prompts/autonomous_agent.md)\" \
  2>&1 | tee /var/log/bcr-agent.log ; \
EXIT_CODE=\$? ; \
echo '=== Agent session complete (exit '\$EXIT_CODE'), collecting & publishing results ===' && \
bash /opt/bcr-agent/deploy/collect_and_publish.sh \
  2>&1 | tee /var/log/bcr-publish.log ; \
echo '=== Pipeline finished ==='
"

# ---------------------------------------------------------------------------
echo "=== [14/14] Done ==="
echo ""
echo "Pipeline started in tmux session 'bcr-agent'"
echo "  Workshop:  ${WORKSHOP_ID}"
echo "  Model:     ${MODEL}"
echo "  Bitcoin:   /workspace/bitcoin (branch: pr${WORKSHOP_ID})"
echo "  Workspace: /workspace"
echo "  Archive:   ${BLOSSOMFS_WRITE_PATH}"
echo ""
echo "Attach:    tmux attach -t bcr-agent"
echo "Logs:      tail -f /var/log/bcr-agent.log"
echo "BlossomFS: ls /mnt/blossomfs/"
echo ""
echo "Self-destruct timer:"
systemctl list-timers bcr-self-destruct.timer 2>&1 || true
