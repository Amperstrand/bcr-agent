#!/bin/bash
set -ex

export PATH=$PATH:/usr/local/go/bin:/root/go/bin:/root/.cargo/bin

echo "=== [1/10] Installing system dependencies ==="
apt-get update -qq
apt-get install -y -qq python3 python3-pip git tmux curl jq ca-certificates \
    build-essential pkg-config libssl-dev fuse3 libfuse3-dev >/dev/null 2>&1

echo "=== [2/10] Installing Go ==="
if [ ! -d /usr/local/go ]; then
    curl -sL https://go.dev/dl/go1.23.4.linux-amd64.tar.gz | tar -C /usr/local -xzf -
fi
export PATH=$PATH:/usr/local/go/bin
go install github.com/fiatjaf/nak@latest 2>&1 || echo "WARN: nak install failed"
cp /root/go/bin/nak /usr/local/bin/nak 2>/dev/null || true

echo "=== [3/10] Installing Rust (for blossomfs) ==="
if [ ! -f /root/.cargo/bin/cargo ]; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y >/dev/null 2>&1
fi
source /root/.cargo/env 2>/dev/null || true

echo "=== [4/10] Building blossomfs ==="
if [ ! -f /opt/blossomfs/target/release/blossomfs ]; then
    git clone https://github.com/Amperstrand/blossomfs.git /opt/blossomfs
    cd /opt/blossomfs
    cargo build --release 2>&1 | tail -5
fi
BLOSSOMFS_BIN="/opt/blossomfs/target/release/blossomfs"

echo "=== [5/10] Installing opencode ==="
curl -fsSL https://opencode.ai/install | bash
ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode 2>/dev/null || true

echo "=== [6/10] Cloning bcr-agent ==="
rm -rf /opt/bcr-agent
git clone https://github.com/Amperstrand/bcr-agent.git /opt/bcr-agent
cp /opt/bcr-agent-config/opencode.json /opt/bcr-agent/opencode.json
cp /opt/bcr-agent-config/config.json /opt/bcr-agent/config.json
chmod 600 /opt/bcr-agent/opencode.json

echo "=== [7/10] Writing nsec (bech32) for blossomfs ==="
HEXKEY=$(cat /opt/bcr-agent-config/bot_nsec | tr -d ' \n')

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

echo "=== [8/10] Mounting blossomfs (RW) ==="
mkdir -p /mnt/blossomfs
NPUB_HEX="9a515b0f08d554b582e54202c7ca0e6ee56d81559957cbf9b40047d391b95fd5"
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

echo "=== [9/10] Setting up self-destruct timer ==="
cat > /etc/systemd/system/bcr-self-destruct.service << 'EOF'
[Unit]
Description=BCR Agent Self-Destruct
After=network-target
[Service]
Type=oneshot
ExecStart=/sbin/shutdown -h now "BCR Agent: 2-hour timeout reached"
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/bcr-self-destruct.timer << 'EOF'
[Unit]
Description=Self-destruct after 2 hours
[Timer]
OnBootSec=2h
AccuracySec=1min
Unit=bcr-self-destruct.service
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now bcr-self-destruct.timer
echo "  Timer active. VM shuts down in 2 hours."

echo "=== [10/10] Starting BCR pipeline in tmux ==="
tmux new-session -d -s bcr-agent "
cd /opt/bcr-agent && \
export PATH=\$PATH:/usr/local/go/bin:/root/go/bin && \
export PYTHONUNBUFFERED=1 && \
python3 -u run.py full ${WORKSHOP_ID:-33300} \
    --publish \
    --nsec-file /opt/bcr-agent-config/bot_nsec \
    --archive-dir '$BLOSSOMFS_WRITE_PATH' \
    2>&1 | tee /var/log/bcr-agent.log
"

echo ""
echo "=== DONE ==="
echo "Pipeline started in tmux session 'bcr-agent'"
echo "Workshop: ${WORKSHOP_ID:-33300}"
echo "Archive:  $BLOSSOMFS_WRITE_PATH"
echo ""
echo "Attach:   tmux attach -t bcr-agent"
echo "Logs:     tail -f /var/log/bcr-agent.log"
echo "BlossomFS: ls /mnt/blossomfs/"
echo ""
echo "Self-destruct timer:"
systemctl list-timers bcr-self-destruct.timer 2>&1 || true
