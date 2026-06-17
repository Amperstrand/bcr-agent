# Architecture

## System Overview

BCR Agent is an autonomous AI reviewer that participates in Bitcoin Core PR Review Club workshops. It runs on a disposable Hetzner VM, uses opencode (with GLM models) as its agent harness, publishes results to Blossom and Nostr, and accumulates knowledge across runs.

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────────┐
│  bootstrap  │───▶│  vm-bootstrap │───▶│  opencode    │───▶│  collect &  │
│  -vm.sh     │    │  -v3.sh       │    │  agent       │    │  publish    │
│  (local)    │    │  (cloud-init) │    │  session     │    │  (auto)     │
└─────────────┘    └──────────────┘    └──────────────┘    └──────┬──────┘
                                                              │
                   ┌──────────────┐    ┌──────────────┐         │
                   │  Blossom     │◀───│  Nostr       │◀────────┘
                   │  (storage)   │    │  (events)    │
                   └──────────────┘    └──────────────┘
                          │
                   ┌──────────────┐
                   │  BlossomFS   │
                   │  (FUSE mount)│
                   │  ← lineage   │
                   └──────────────┘
```

## VM Lifecycle

1. **`bootstrap-vm.sh`** (run locally): Creates Hetzner cpx32 VM via cloud-init. Writes secrets, clones repo at pinned commit, launches `vm-bootstrap-v3.sh`.

2. **`vm-bootstrap-v3.sh`** (runs on VM): 14-step setup:
   - Install deps (build-essential, cmake, clang-18, nodejs, etc.)
   - Install Go + nak (Nostr CLI for signing)
   - Build BlossomFS from source
   - Install opencode
   - Clone bitcoin-core-review-club/bitcoin at PR branch
   - Pre-scrape workshop data
   - Mount BlossomFS (RW)
   - **Pre-fetch lineage** from previous runs
   - Set 4-hour self-destruct timer
   - Start opencode agent session in tmux

3. **Agent session** (opencode with `--dangerously-skip-permissions`):
   - Reads knowledge base + workshop cheat sheet + lineage artifacts
   - For each workshop question: understand → research → experiment → answer → verify
   - Builds Bitcoin Core, runs fuzz tests, reads code
   - Writes results to `/workspace/results/`

4. **`collect_and_publish.sh`** (auto-runs after session):
   - Secret-scans all output files
   - Combines into single report with version/machine metadata
   - Uploads report + session transcript to Blossom
   - Publishes NIP-90 Nostr events (kind 6500 + kind 1)
   - Exports opencode session as JSON
   - Archives to BlossomFS

## Knowledge System

### Three Layers

| Layer | Location | Purpose | Examples |
|---|---|---|---|
| **Git knowledge** | `knowledge/` | Cross-workshop patterns | build_system.md, review_strategies.md |
| **Workshop cheatsheets** | `workshops/<id>/` | Per-workshop tips & traps | 33300/cheatsheet.md |
| **BlossomFS lineage** | `/mnt/blossomfs/` | Raw artifacts from all runs | session.json, journal.md, build logs |

### Knowledge Feedback Loop

```
Run N completes
  → recommendations.md written
  → journal.md written  
  → learnings.jsonl updated (git)
  → session transcript published to Blossom
  → BlossomFS archive updated

Run N+1 starts
  → reads knowledge/ (git, structured)
  → reads workshops/<id>/cheatsheet.md (git, specific)
  → reads /workspace/lineage/ (pre-fetched session transcripts)
  → browses /mnt/blossomfs/ (all raw artifacts)
  → inherits Run N's wisdom, avoids Run N's mistakes
```

### learnings.jsonl Format

Each run appends one JSON line:

```json
{
  "run": 2,
  "workshop": "33300",
  "model": "glm-5.2",
  "cost_usd": 1.74,
  "duration_min": 32,
  "tokens": { "input": 117700, "output": 30700, "cache_read": 6500000 },
  "build_succeeded": true,
  "fuzz_ran": true,
  "learnings": ["..."],
  "failures": ["..."],
  "blossom_report": "https://blossom.psbt.me/...",
  "blossom_session": "https://blossom.psbt.me/..."
}
```

## Publishing Pipeline

### Blossom (BUD-02 upload)
- Report: ~45-70KB markdown, free tier (<1MB)
- Session transcript: ~250-280KB JSON, free tier
- Uses Cashu (NUT-24) for files >1MB
- Content-addressed by SHA256

### Nostr Events
- **Kind 6500** (NIP-90 job result): Machine-readable, includes Blossom URL, metrics
- **Kind 1** (text note): Human-readable announcement
- Published to: nos.lol, relay.damus.io, relay.primal.net

### BlossomFS (FUSE mount)
- Mounts bot's Blossom blobs as local filesystem
- Agent reads previous runs' artifacts directly
- Write access for archiving new artifacts

## Website

### GitHub Pages (`docs/`)
- `index.html` + `app.js` + `style.css`: Vanilla JS Nostr reader
- Fetches kind 1 + kind 6500 events from relays
- Mode toggle: Blind / Augmented / Autonomous
- Markdown rendering with syntax highlighting
- Run metrics: version, machine specs, model

### nsite (NIP-5A)
- Same `docs/` content deployed to Nostr
- CI: `.github/workflows/deploy-nsite.yml` runs on push to main

## Cost Model

| Component | Cost | Notes |
|---|---|---|
| Hetzner VM (cpx32) | ~$0.06/hour | 4 vCPU, 8GB RAM |
| z.ai GLM-4.6 | $0.56/run | 98K input, 18K output, 4.1M cache |
| z.ai GLM-5.2 | ~$1.99/run | 117K input, 30K output, 6.5M cache |
| Blossom storage | Free | <1MB per file |
| Nostr relays | Free | Public relays |
| **Total per run** | **$0.60 - $2.05** | Model-dependent |
