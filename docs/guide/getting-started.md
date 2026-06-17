# Getting Started

## Prerequisites

- A z.ai API key (for GLM models via opencode)
- A Hetzner Cloud account + API token
- A Nostr private key (nsec) for publishing results
- `hcloud` CLI installed locally
- This repository cloned locally

## Setup

### 1. Configure Secrets

Create `~/.config/bcr-deploy/secrets`:

```bash
HCLOUD_TOKEN="your-hetzner-token"
ZAI_API_KEY="your-zai-api-key"
BOT_NSEC_HEX="your-bot-nsec-in-hex"
BOT_NPUB_HEX="your-bot-npub-in-hex"
```

```bash
chmod 600 ~/.config/bcr-deploy/secrets
```

### 2. Register SSH Key with Hetzner

```bash
hcloud ssh-key create --name "your-key" --public-key-from-file ~/.ssh/id_ed25519.pub
```

### 3. Set Up VM Cleanup (Optional but Recommended)

Install the launchd cron to auto-delete VMs after 4 hours:

```bash
# Edit deploy/com.bcr-agent.cleanup.plist to point to your repo path
# Then:
cp deploy/com.bcr-agent.cleanup.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.bcr-agent.cleanup.plist
```

## Running a Workshop

### Basic Deploy

```bash
# Workshop #33300 with GLM-5.2
bash deploy/bootstrap-vm.sh 33300 bcr-agent-run3 zai/glm-5.2
```

This will:
1. Create a cpx32 VM on Hetzner (4 vCPU, 8GB RAM, ~$0.06/hr)
2. Install all dependencies (build tools, clang-18, nodejs, opencode)
3. Clone Bitcoin Core at the workshop's PR branch
4. Mount BlossomFS (access to previous runs' artifacts)
5. Pre-fetch lineage data from previous runs
6. Start the autonomous agent session in tmux
7. Set 4-hour self-destruct timer

### Monitor the Run

```bash
# SSH in and watch the agent work
ssh root@<VM-IP> -t 'tmux attach -t bcr-agent'

# Or tail the log
ssh root@<VM-IP> 'tail -f /var/log/bcr-agent.log'

# Check results
ssh root@<VM-IP> 'ls -la /workspace/results/'
```

### After Completion

The agent automatically:
1. Scans results for secrets
2. Combines into a single report with version/machine metadata
3. Uploads report + session transcript to Blossom
4. Publishes Nostr events (kind 6500 + kind 1)
5. Archives to BlossomFS

Results appear on the [live site](https://amperstrand.github.io/bcr-agent/) within minutes.

### Clean Up

VMs auto-destruct after 4 hours. To delete manually:

```bash
hcloud server delete <server-name>
```

## Customizing

### Change the Model

```bash
bash deploy/bootstrap-vm.sh 33300 bcr-agent-glm46 zai/glm-4.6
```

Available models: `zai/glm-4.6`, `zai/glm-5.1`, `zai/glm-5.2`

### Run a Different Workshop

```bash
bash deploy/bootstrap-vm.sh 32489 bcr-agent-wallet
```

Workshop IDs can be found at [bitcoincore.reviews](https://bitcoincore.reviews/).

### Add Knowledge

Edit files in `knowledge/` and `workshops/<id>/` — these are read by the agent at session start and committed to the repo for future runs.

## Troubleshooting

| Issue | Fix |
|---|---|
| `cmake: command not found` | Pre-installed in bootstrap. If missing: `apt-get install cmake` |
| `nsec invalid` | Ensure BOT_NSEC_HEX is 64 hex chars in secrets file |
| Blossom upload fails | Check nak is installed: `which nak` |
| Build times out | Use `setsid make -j$(nproc) fuzz &` for background builds |
| Agent can't find workshop | Check `/workspace/workshop.json` was pre-scraped |
