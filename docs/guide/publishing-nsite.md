# Publishing as an nsite

The web UI in `docs/` is published through **two independent channels** that serve the exact same static files:

1. **GitHub Pages** — served from `docs/` at <https://amperstrand.github.io/bcr-agent/> (configured under *Settings → Pages*; no Actions workflow required). `docs/.nojekyll` disables Jekyll processing.
2. **Nostr nsite (NIP-5A)** — the same `docs/` directory is uploaded to Blossom storage and announced as a **named nsite** called `bcr-agent` via a Nostr kind `35128` manifest.

All local asset paths in `docs/` are relative (`style.css`, `app.js`, `vendor/…`), so the site works unchanged under both the GitHub Pages `/bcr-agent/` path and an nsite root `/`.

## Live endpoints

| Surface | URL |
|---|---|
| GitHub Pages | <https://amperstrand.github.io/bcr-agent/> |
| Named nsite gateway | <https://16b75mch3bknau4wzx3wbxnon44dcyghrhg4e6u4955gtdn86nbcr-agent.nsite.lol/> |
| Root nsite gateway | <https://npub19un7xypnmsyr6ut32hrl5hsxzfxrpv7wr3744heut9nyrqrn3ghs94wede.nsite.lol/> |
| Signer npub | `npub19un7xypnmsyr6ut32hrl5hsxzfxrpv7wr3744heut9nyrqrn3ghs94wede` (hex `2f27e31033dc083d717155c7fa5e06124c30b3ce1c7d5adf3c59664180738a2f`) |

The named-site subdomain encodes the signer npub in base36 followed by `bcr-agent`. The root nsite carries the same content and additionally publishes the identity's profile / server-list / relay-list (kinds 0, 10063, 10002).

## nsite configuration

- `.nsite/config.json` — relays, Blossom servers, fallback (`/index.html`), the NIP-89 app handler. **No secrets live here**; it is safe to commit.
- Blossom servers (used **in parallel for redundancy** — never a single backend):
  - `https://blossom.psbt.me`
  - `https://cdn.hzrd149.com`
  - `https://cdn.sovbit.host`
- Relays: `wss://relay.nsite.lol`, `wss://nos.lol`, `wss://relay.damus.io`.

> `blossom.psbt.me` is one of several Blossom servers used for redundancy — it is **not** the sole storage backend. Blossom server availability fluctuates; deploys succeed as long as at least one server is reachable, and `cdn.hzrd149.com` has historically been the most reliable.

## Self-contained assets (no CDNs)

The nsite is **fully self-hosted** — it pulls nothing from third-party CDNs:

- `docs/vendor/` holds pinned copies of `marked@12.0.2`, `dompurify@3.0.11`, `highlight.js@11.9.0` (+ CSS).
- No Google Fonts — `docs/style.css` uses system font stacks only.

This means no visitor-IP leakage to Google/Cloudflare/jsdelivr, no render-blocking external requests, and the nsite survives CDN outages. If the markdown libraries fail to load for any reason, `app.js` degrades gracefully: reports render in a `<pre>` block instead of styled markdown.

## Local deployment

Install the [`nsyte`](https://jsr.io/@nsyte/cli) CLI (v0.27.x; prebuilt binaries are on the [releases page](https://github.com/sandwichfarm/nsyte/releases)).

**The signer key lives OUTSIDE this repository** so it can never be accidentally committed: `~/.config/bcr-agent/nsite_nsec` (mode `0600`). The `.gitignore` also blocks `*nsec*` / `*secret*` / `*.env` patterns as a safety net, but keeping it outside the working tree is the real guarantee.

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

> Back up `~/.config/bcr-agent/nsite_nsec` (e.g. to a password manager). Losing it means the `bcr-agent` nsite can no longer be updated.

## CI deployment (GitHub Actions)

`.github/workflows/deploy-nsite.yml` runs on pushes to `main` that touch `docs/**`, `.nsite/**`, or the workflow itself. It deploys `docs/` via [`sandwichfarm/nsite-action`](https://github.com/sandwichfarm/nsite-action) (pinned to a commit SHA for supply-chain safety). The workflow uses `sync: true` (so it succeeds even when content is unchanged and backfills flaky servers) and includes nsyte's fallback relays/servers for resilience.

**Required GitHub secret:**

| Secret | Description |
|--------|-------------|
| `NBUNK_SECRET` | The nsite signer credential, fed to the action's `sec` input (→ `nsyte --sec`). Currently the signer's `nsec1...` private key. Add it under *Settings → Secrets and variables → Actions*. **Never commit this value** — the `.gitignore` blocks `*nsec*` / `*.env` / `*credential*`, and the key is stored outside the repo tree. |

The workflow fails immediately with a clear `::error::` if `NBUNK_SECRET` is missing. GitHub Pages is untouched by this workflow.

## Hardening the CI signer

The current setup puts the raw `nsec1...` in a GitHub secret (via the action's `sec` input). GitHub encrypts secrets at rest and masks them in logs, but a raw private key is the most sensitive credential form.

The stronger model is an `nbunksec1...` — a **NIP-46 bunker delegation**: CI never holds the private key; it asks a remote **bunker signer** (which holds the nsec) to sign on its behalf over a relay. The bunker can be rate-limited, restricted to specific operations, and revoked.

**Important — this is infrastructure, not a config swap.** `nsyte ci` / `nsyte bunker connect` connect to a bunker that must already be running and reachable on a public relay. To harden you must:

1. **Run a persistent NIP-46 bunker signer** that holds the nsec and listens on a relay (e.g. a wallet app like Amethyst/Coracle, a dedicated `nak bunker`, or a hosted bunker). It must be online whenever CI deploys — if it's down, deploys fail.
2. Connect nsyte to it interactively: `nsyte bunker connect --pubkey <signer> --relay <relay> --secret <conn-secret>`, which mints and stores an `nbunksec1...`.
3. Put the `nbunksec1...` in the `NBUNK_SECRET` secret and swap the workflow's `sec:` line to `nbunksec:` (the action validates that input starts with `nbunksec1` and rejects raw `nsec`).

Because a live bunker adds an always-on dependency, the project currently ships with the simpler `nsec`-via-`sec` approach. Switch to `nbunksec` once a permanent signer is in place.

## Validate before deploying

```bash
./scripts/check-static-site.sh
```

Checks that `docs/` and `docs/index.html` exist, flags any root-relative `"/bcr-agent/…"` asset paths that would break under nsite root serving (ignoring full URLs in prose), and verifies every local asset referenced from `index.html` resolves on disk.

## Verify after deployment

```bash
# Confirm assets resolve from the nsite root (named gateway)
curl -sS -o /dev/null -w "%{http_code}\n" https://16b75mch3bknau4wzx3wbxnon44dcyghrhg4e6u4955gtdn86nbcr-agent.nsite.lol/
curl -sS -o /dev/null -w "%{http_code}\n" https://16b75mch3bknau4wzx3wbxnon44dcyghrhg4e6u4955gtdn86nbcr-agent.nsite.lol/vendor/marked.min.js

# Full manifest / server-coverage check
nsyte status --name bcr-agent --full
```

> nsite gateways cache at the edge. Immediately after a deploy, a bare path may briefly serve the previous version while `/path?cb=N` already serves fresh content. The cache clears on the gateway's TTL; bumping the asset `?v=` query and redeploying forces refresh.
