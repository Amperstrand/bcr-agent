# BCR Agent

An autonomous AI agent that participates in [Bitcoin Core PR Review Club](https://bitcoincore.reviews/) workshops — reading code, building projects, running fuzz tests, and writing evidence-based reviews. Each run publishes its work to [Blossom](https://github.com/hzrd149/blossom) and [Nostr](https://github.com/nostr-protocol/nips), and passes accumulated knowledge forward to future runs.

Inspired by [Latent Reflection](https://rootkid.me/works/latent-reflection) by [rootkid](https://rootkid.me/).

---

## Documentation

| | |
|---|---|
| [Live Site](https://amperstrand.github.io/bcr-agent/) | Workshop results, rendered reports, mode comparison |
| [Architecture](docs/guide/architecture.md) | System design, VM lifecycle, knowledge system, publishing pipeline |
| [Philosophy](docs/guide/philosophy.md) | Agent reincarnation, the printing press moment, cumulative cultural evolution |
| [Getting Started](docs/guide/getting-started.md) | Deploy your own autonomous review run |
| [Research](docs/guide/research.md) | Academic patterns, related work, evaluation framework |

---

## What It Does

1. **Spins up a disposable VM** (Hetzner cpx32, 4 vCPU, 8GB RAM)
2. **Clones Bitcoin Core** at the workshop's PR branch
3. **Runs an autonomous agent** (opencode + GLM-5.2) that answers 8 review questions through hands-on code exploration, compilation, and fuzzing
4. **Publishes results** to Blossom (reports, session transcripts) and Nostr (announcements)
5. **Feeds learnings forward** to the next run via persistent knowledge base

Each run costs ~$0.60–$2.05 (model-dependent) and takes 30–60 minutes.

---

## Repository Structure

```
bcr-agent/
├── README.md                  ← You are here (map to the project)
├── prompts/
│   └── autonomous_agent.md    Master prompt for the agent session
├── knowledge/                 Cross-workshop knowledge (accumulates over runs)
│   ├── learnings.jsonl        Structured per-run data (cost, tokens, learnings)
│   ├── build_system.md        Bitcoin Core build recipes
│   ├── review_strategies.md   Effective search and analysis patterns
│   └── common_pitfalls.md     Things that repeatedly fail
├── workshops/                 Per-workshop cheat sheets
│   └── 33300/cheatsheet.md    Tips, traps, crash reproduction guide
├── deploy/                    Infrastructure
│   ├── bootstrap-vm.sh        Creates Hetzner VM, launches pipeline
│   ├── vm-bootstrap-v3.sh     14-step VM setup (runs on VM)
│   ├── collect_and_publish.sh Post-agent collection & publishing
│   ├── vm-opencode.json       opencode config (models, MCP tools)
│   └── cleanup-vms.sh         Local cron: auto-delete old VMs
├── docs/                      GitHub Pages + nsite content
│   ├── index.html             Web app (Nostr reader)
│   ├── app.js                 Vanilla JS event fetching + rendering
│   ├── style.css              Dark theme design system
│   └── guide/                 Documentation (architecture, philosophy, etc.)
├── *.py                       Python pipeline modules
│   ├── scraper.py             Scrape workshop pages → JSON
│   ├── segmenter.py           Map IRC log to questions
│   ├── agent.py               LLM-powered reviewer (text-only mode)
│   ├── comparator.py          Compare agent answers vs IRC discussion
│   ├── reporter.py            Generate coverage report
│   ├── blossom_publisher.py   BUD-02 upload + Cashu
│   ├── nostr_publisher.py     NIP-90 event publishing
│   └── secret_scanner.py      Pre-publish secret detection
└── .github/workflows/
    └── deploy-nsite.yml       CI: deploy docs/ to Nostr as nsite
```

---

## Quick Start

```bash
# Configure secrets
echo 'HCLOUD_TOKEN=...
ZAI_API_KEY=...
BOT_NSEC_HEX=...
BOT_NPUB_HEX=...' > ~/.config/bcr-deploy/secrets && chmod 600 $_

# Deploy an autonomous run
bash deploy/bootstrap-vm.sh 33300 bcr-agent-run3 zai/glm-5.2

# Monitor
ssh root@<VM-IP> -t 'tmux attach -t bcr-agent'
```

See [Getting Started](docs/guide/getting-started.md) for full instructions.

---

## Run History

| Run | Workshop | Model | Cost | Build | Questions | Report |
|---|---|---|---|---|---|---|
| 1 | #33300 | GLM-4.6 | $0.56 | ❌ timeout | 8/8 | [Blossom](https://blossom.psbt.me/46155ddb8b9e0c6a1afa8c3ca612d8582178e65a994a943a2abb211aaf7cd11e) |
| 2 | #33300 | GLM-5.2 | ~$2.05 | ✅ GCC + clang-18 | 8/8 | [Blossom](https://blossom.psbt.me/2cbfba2b68041c54224a0010eb564b5fda7c4546a9ea1d8de5cab6b6f734c09b) |

---

## License

MIT — see [LICENSE](LICENSE).
