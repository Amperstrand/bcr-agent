# BCR Agent 🤖⚡

**AI-Powered Bitcoin Core PR Review Club Agent**

An automated AI reviewer that runs [Bitcoin Core PR Review Club](https://bitcoincore.reviews/) workshops, answers structured review questions using an LLM, and compares its findings against the actual IRC discussions from human reviewers.

---

## What It Does

The Bitcoin Core PR Review Club hosts weekly workshops where contributors review Bitcoin Core PRs together. Each workshop has three parts:

1. **Notes** — Pre-meeting background reading
2. **Questions** — Structured review questions (conceptual + implementation)
3. **Meeting Log** — IRC transcript of the live discussion

BCR Agent automates the reviewer role:

| Step | Module | Description |
|------|--------|-------------|
| 1️⃣ | `scraper.py` | Scrapes a workshop page into structured JSON (notes, questions, IRC log) |
| 2️⃣ | `segmenter.py` | Maps IRC log entries to specific workshop questions using anchor detection |
| 3️⃣ | `agent.py` | Answers each question using an LLM with the PR diff as context |
| 4️⃣ | `comparator.py` | Compares the agent's answers against the IRC discussion |
| 5️⃣ | `reporter.py` | Generates a coverage report: what the AI caught, missed, and added |

### Two Agent Modes

| Mode | Context | Use Case |
|------|---------|----------|
| **Blind** | Workshop notes + PR diff only | Running new/future workshops without human discussion |
| **Augmented** | Notes + diff + IRC log + GitHub PR comments | Backtesting against past workshops, measuring coverage |

---

## Quick Start

### Prerequisites

- Python 3.9+
- An LLM CLI backend (e.g. [z-ai-web-dev-sdk](https://github.com/z-ai/z-ai-web-dev-sdk))

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/bcr-agent.git
cd bcr-agent

# Copy and edit the config (set your LLM backend path)
cp config.example.json config.json
```

### Run a Workshop

```bash
# Full pipeline: scrape → segment → agent (both modes) → compare → report
python run.py full 32489

# Or run individual steps
python run.py scrape 32489           # Scrape workshop data
python run.py segment 32489          # Segment IRC log + fetch GitHub comments
python run.py agent 32489 blind      # Run AI reviewer in blind mode
python run.py agent 32489 augmented  # Run AI reviewer with IRC/GitHub context
python run.py both 32489             # Run both modes back-to-back
python run.py compare 32489          # Compare agent answers vs IRC discussion
python run.py report 32489           # Generate human-readable report
```

---

## Project Structure

```
bcr-agent/
├── run.py                # CLI entry point
├── scraper.py            # Scrape workshop pages → structured JSON
├── segmenter.py          # Map IRC log to questions + fetch GitHub comments
├── agent.py              # AI reviewer (LLM-powered, blind + augmented modes)
├── comparator.py         # Compare agent answers vs IRC discussion
├── mode_compare.py       # Compare blind vs augmented answers head-to-head
├── reporter.py           # Generate human-readable coverage report
├── config.example.json   # Configuration template
├── data/                 # Scraped workshop data (gitignored)
└── results/              # Agent output and comparisons (gitignored)
```

---

## Backtest Results — Workshop #32489

**PR:** `wallet: Add exportwatchonlywallet RPC` (+649/-101 lines, 15 files)  
**Host:** ryanofsky | **Author:** achow101 | **Date:** Aug 6, 2025

| Metric | Value |
|--------|-------|
| Questions answered | 8/8 |
| Human insights captured | 20/49 (41%) |
| Novel AI insights | 23 |
| Human-only insights | 29 |
| Avg. time per question | ~18s |

### Key Findings

**Strengths:**
- Structured, comprehensive coverage of each question as asked
- Additional code references and implementation details beyond the PR diff
- Performance and edge case analysis not discussed by humans
- Consistent quality across questions (rated 3-4/5 on most)

**Weaknesses:**
- Misses points that emerged from interactive back-and-forth discussion
- IRC conversation drifts to related topics the agent doesn't follow
- Q6 mismatch: IRC discussed a different sub-topic than what the question asked; agent answered the question as written
- Doesn't capture real-time corrections and clarifications

**Notable:** The agent produced **23 novel insights** that humans didn't discuss, suggesting it can add value as a parallel reviewer — not just replicate human analysis.

---

## How the Agent Works

### Blind Mode (for future workshops)

For each question, the agent:
1. Receives the workshop **notes** and a relevance-ranked **PR diff excerpt**
2. Has access to its **previous answers** for chain-of-thought context (last 4)
3. Uses a system prompt encoding Bitcoin Core expertise (C++ codebase, protocol, review process)
4. Produces a structured answer with specific code references

The diff excerpt is selected by scoring each file section's relevance to the question keywords, so the agent focuses on the most relevant code changes.

### Augmented Mode (for backtesting)

In addition to the blind mode context, the agent also receives:
1. The **IRC discussion segment** for that specific question (extracted by `segmenter.py`)
2. **GitHub PR comments** relevant to the question

The augmented mode system prompt instructs the agent to synthesize both human insights and its own analysis, noting agreements and disagreements.

### IRC Segment Matching

The segmenter uses anchor-based detection to map IRC discussion to questions:
1. Detects the host nick (the person who says `#startmeeting`)
2. Finds "anchor" messages where the host introduces a question (numbered questions, verbatim text matches, "first question" / "next question" cues)
3. Assigns all messages between anchors to the preceding question
4. Handles unanchored questions by splitting at text-match boundaries
5. Rebalances interleaved discussions when questions were posted together

---

## Configuration

Copy `config.example.json` to `config.json` and customize:

```json
{
  "llm": {
    "provider": "z-ai",
    "z_ai_path": "/usr/local/bin/z-ai",
    "model": "glm-4-plus",
    "thinking": true,
    "timeout_seconds": 300
  },
  "agent": {
    "max_diff_chars": 15000,
    "max_irc_chars": 8000,
    "max_github_chars": 4000,
    "previous_answers_context": 4
  }
}
```

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  bitcoincore │────▶│  scraper.py  │────▶│ structured   │
│  .reviews    │     │  (HTML→JSON) │     │ JSON + diff  │
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                    ┌──────────────┐              │
                    │ segmenter.py │◀─────────────┘
                    │ (IRC→Q map)  │
                    └──────┬───────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   ┌────────────┐  ┌────────────┐   ┌────────────┐
   │ Blind Mode │  │  Augmented │   │  GitHub    │
   │  (notes +  │  │   Mode     │   │  Comments  │
   │   diff)    │  │ (+IRC+GH)  │   │  Fetcher   │
   └─────┬──────┘  └─────┬──────┘   └─────┬──────┘
         │               │                 │
         └───────┬───────┘                 │
                 ▼                         │
          ┌────────────┐                   │
          │  agent.py  │◀──────────────────┘
          │  (LLM call)│
          └─────┬──────┘
                │
                ▼
         ┌───────────────┐     ┌──────────────┐
         │ comparator.py │────▶│ reporter.py  │
         │ (AI vs IRC)   │     │ (report.txt) │
         └───────────────┘     └──────────────┘
```

---

## Publishing as an nsite

The web UI in **`docs/`** is published through two independent channels that both serve the exact same static files:

1. **GitHub Pages** — served from `docs/` at `https://amperstrand.github.io/bcr-agent/` (configured under *Settings → Pages*; no Actions workflow required). `docs/.nojekyll` disables Jekyll processing.
2. **Nostr nsite (NIP-5A)** — the same `docs/` directory is uploaded to Blossom storage and announced as a **named nsite** called `bcr-agent` via a Nostr kind `35128` manifest.

Because all local asset paths in `docs/` are relative (`style.css`, `app.js`), the site works unchanged under both the `/bcr-agent/` path and an nsite root `/`.

### nsite configuration

- `.nsite/config.json` — relays, Blossom servers, fallback (`/index.html`), and the `publishServerList` flag. **No secrets live here**; it is safe to commit.
- The nsite uses these Blossom servers for redundancy (never a single backend):
  - `https://blossom.psbt.me`
  - `https://cdn.hzrd149.com`
  - `https://cdn.sovbit.host`
- Relays: `wss://relay.nsite.lol`, `wss://nos.lol`, `wss://relay.damus.io`.

> Note: `blossom.psbt.me` is one of several Blossom servers used for redundancy — it is **not** the sole storage backend.

### Local deployment

Install the [`nsyte`](https://jsr.io/@nsyte/cli) CLI (v0.27.x; prebuilt binaries are on the [releases page](https://github.com/sandwichfarm/nsyte/releases)).

**The signer key lives OUTSIDE this repository** so it can never be accidentally committed. It is stored at `~/.config/bcr-agent/nsite_nsec` (mode `0600`). The `.gitignore` also blocks `*nsec*` / `*secret*` / `*.env` patterns as a safety net, but keeping it outside the working tree is the real guarantee.

```bash
# Generate the signer once and store it outside the repo (mode 0600).
# Reuses this repo's proven bech32 key-gen logic (see deploy/vm-bootstrap-v3.sh).
mkdir -p ~/.config/bcr-agent && chmod 700 ~/.config/bcr-agent
python3 - <<'PY'  # writes ~/.config/bcr-agent/nsite_nsec
import os
CHARSET='qpzry9x8gf2tvdw0s3jn54khce6mua7l'
def polymod(v):
    g=[0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3];c=1
    for x in v:
        b=c>>25;c=(c&0x1ffffff)<<5^x
        for i in range(5): c^=g[i] if (b>>i)&1 else 0
    return c
hrp='nsec';d=os.urandom(32)
def c8to5(d):
    a=0;b=0;r=[]
    for v in d:
        a=(a<<8|v)&0xffffffff;b+=8
        while b>=5:b-=5;r.append(a>>b&31)
    return r
d5=c8to5(d);cs=polymod([ord(x)>>5 for x in hrp]+[0]+[ord(x)&31 for x in hrp]+d5+[0,0,0,0,0,0])^1
chk=[(cs>>5*(5-i))&31 for i in range(6)]
open(os.path.expanduser('~/.config/bcr-agent/nsite_nsec'),'w').write('nsec1'+''.join(CHARSET[x] for x in d5+chk)+'\n')
os.chmod(os.path.expanduser('~/.config/bcr-agent/nsite_nsec'),0o600)
print('wrote ~/.config/bcr-agent/nsite_nsec')
PY

# Deploy docs/ as the named nsite "bcr-agent" using the stored key
nsyte deploy ./docs --name bcr-agent --fallback=/index.html \
  --sec "$(cat ~/.config/bcr-agent/nsite_nsec)" -i

# Inspect what is published
nsyte status --name bcr-agent --full

# Diagnose connectivity / signing issues
nsyte debug --verbose
```

### CI deployment (GitHub Actions)

`.github/workflows/deploy-nsite.yml` runs on pushes to `main` that touch `docs/**`, `.nsite/**`, or the workflow itself. It deploys `docs/` via the official [`sandwichfarm/nsite-action`](https://github.com/sandwichfarm/nsite-action).

**Required GitHub secret:**

| Secret | Description |
|--------|-------------|
| `NBUNK_SECRET` | The nsite signer's **`nsec1...` private key**. The workflow feeds it to the action's `sec` input (which passes it to `nsyte --sec`). Generate it as shown above, copy the contents of `~/.config/bcr-agent/nsite_nsec`, and add it under *Settings → Secrets and variables → Actions*. **Never commit this value.** The `.gitignore` already blocks `*nsec*`, `*.env`, and `*credential*` patterns, and the key is stored outside the repo tree. See [Hardening the CI signer](#hardening-the-ci-signer) to upgrade to a revocable `nbunksec1...` later. |

The workflow fails immediately with a clear `::error::` message if `NBUNK_SECRET` is missing. The existing GitHub Pages setup is untouched.

#### Hardening the CI signer

This workflow currently uses the action's `sec` input with the raw `nsec1...` key. GitHub encrypts secrets at rest and masks them in logs, but a raw private key is the most sensitive form of credential. For a **delegated, revocable** credential instead:

1. Run `nsyte ci` interactively in a terminal where your key is in a Nostr signer / keychain — it mints an `nbunksec1...` (a NIP-46 bunker token) that is never written to disk.
2. Replace the secret value and swap the workflow's `sec:` line back to `nbunksec:` (the action validates that input starts with `nbunksec1` and rejects raw `nsec` values).
3. Update the secret's stored value accordingly.

`nsyte ci` is interactive (Nostr Connect / bunker flow) and cannot be driven from this non-interactive setup, which is why the default here is the `nsec` via `sec`.

### Validate before deploying

```bash
./scripts/check-static-site.sh
```

This checks that `docs/` and `docs/index.html` exist, flags any hardcoded `/bcr-agent/` or root-absolute asset paths that would break under nsite root serving, and verifies that every local asset referenced from `index.html` resolves on disk.

### Verify after deployment

After the nsite is published, **test it through an nsite gateway** to confirm files resolve from the root path `/`, not just from the GitHub Pages `/bcr-agent/` path. The current live deployment is:

- **Named site:** `bcr-agent`
- **Signer npub:** `npub19un...hs94wede` (hex `2f27e31033dc083d717155c7fa5e06124c30b3ce1c7d5adf3c59664180738a2f`)
- **Gateway URL:** `https://16b75mch3bknau4wzx3wbxnon44dcyghrhg4e6u4955gtdn86nbcr-agent.nsite.lol/`

```bash
# Confirm assets resolve from the nsite root
curl -sS -o /dev/null -w "%{http_code}\n" https://16b75mch3bknau4wzx3wbxnon44dcyghrhg4e6u4955gtdn86nbcr-agent.nsite.lol/
curl -sS -o /dev/null -w "%{http_code}\n" https://16b75mch3bknau4wzx3wbxnon44dcyghrhg4e6u4955gtdn86nbcr-agent.nsite.lol/app.js
curl -sS -o /dev/null -w "%{http_code}\n" https://16b75mch3bknau4wzx3wbxnon44dcyghrhg4e6u4955gtdn86nbcr-agent.nsite.lol/style.css

# Full manifest / server-coverage check
nsyte status --name bcr-agent --full
```

The named-site subdomain encodes the signer npub in base36 followed by `bcr-agent`. Note that Blossom server availability fluctuates — the deployment uses **three** servers for redundancy, so a single server being down does not take the nsite offline (during initial deploy `cdn.hzrd149.com` carried 100% of blobs while two other servers were intermittently unavailable).

---

## Roadmap

- [ ] **Multi-agent review** — Different agents with different perspectives (security, performance, correctness)
- [ ] **Code execution** — Agent that can actually build and test the PR
- [ ] **RAG over bitcoin/bitcoin** — Give the agent access to the full codebase, not just the diff
- [ ] **Batch backtesting** — Run against all 253 workshops to evaluate prompt strategies
- [ ] **IRC segment alignment** — Better matching of IRC discussion to specific questions
- [ ] **Prompt optimization** — A/B test different system prompts and context strategies
- [ ] **Self-hosted Docker image** — Package with configurable LLM backend (OpenAI, Anthropic, local models)
- [ ] **Multi-agent discussion mode** — AI bots talking with each other, simulating the IRC review
- [ ] **GitHub Actions integration** — Automatically run on new review club posts

---

## Contributing

Contributions are welcome! This is an early prototype — there's lots of room for improvement.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-improvement`)
3. Commit your changes (`git commit -am 'Add new feature'`)
4. Push to the branch (`git push origin feature/my-improvement`)
5. Open a Pull Request

### Ideas for Contributions

- **Better LLM backend support** — Add OpenAI, Anthropic, or local model providers
- **Improved IRC segmentation** — Smarter anchor detection, topic modeling
- **Batch runner** — Script to backtest across many workshops
- **Web dashboard** — Visualize comparison results
- **Prompt engineering** — Better system prompts for Bitcoin Core review
- **Test suite** — Unit tests for scraper, segmenter, agent modules

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Acknowledgments

- [Bitcoin Core PR Review Club](https://bitcoincore.reviews/) — The amazing community that makes these workshops happen
- [bitcoin-core-review-club/bitcoincore.reviews](https://github.com/bitcoin-core-review-club/bitcoincore.reviews) — The Jekyll source for the review club site
- All the Bitcoin Core contributors who participate in reviews
