#!/bin/bash
set -ex

export PATH=$PATH:/usr/local/go/bin:/root/go/bin

echo "=== [1/8] Installing Go ==="
curl -sL https://go.dev/dl/go1.23.4.linux-amd64.tar.gz | tar -C /usr/local -xzf -

echo "=== [2/8] Installing nak ==="
go install github.com/fiatjaf/nak@latest
cp /root/go/bin/nak /usr/local/bin/nak || echo "WARN: nak install failed"
nak --version 2>&1 || true

echo "=== [3/8] Installing opencode ==="
curl -fsSL https://opencode.ai/install | bash
ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode || true
opencode --version 2>&1 || true

echo "=== [4/8] Cloning repo ==="
git clone https://github.com/Amperstrand/bcr-agent.git /opt/bcr-agent

echo "=== [5/8] Copying config files ==="
cp /opt/bcr-agent-config/opencode.json /opt/bcr-agent/opencode.json
cp /opt/bcr-agent-config/config.json /opt/bcr-agent/config.json
chmod 600 /opt/bcr-agent/opencode.json

echo "=== [6/8] Setting up self-destruct timer ==="
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
echo "Self-destruct timer active. VM will shut down in 2 hours."

echo "=== [7/8] Scrubbing cloud-init data ==="
cloud-init clean --logs
rm -rf /var/lib/cloud/instances/*

echo "=== [8/8] Starting BCR pipeline in tmux ==="
tmux new-session -d -s bcr-agent \
  "cd /opt/bcr-agent && export PATH=\$PATH:/usr/local/go/bin:/root/go/bin && python3 run.py full 32489 --publish --nsec-file /opt/bcr-agent-config/bot_nsec 2>&1 | tee /var/log/bcr-agent.log"

echo "=== DONE ==="
echo "Pipeline started in tmux session 'bcr-agent'"
echo "Attach: tmux attach -t bcr-agent"
echo "Logs:   tail -f /var/log/bcr-agent.log"
echo ""
echo "Self-destruct timer:"
systemctl list-timers bcr-self-destruct.timer 2>&1 || true
