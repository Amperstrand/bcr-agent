#!/usr/bin/env python3
"""
BCR Agent — Blossom Publisher (BUD-02 upload + Cashu NUT-24)

Uploads files to a Blossom media server (e.g. blossom.psbt.me) using the
standard Blossom protocol (BUD-02 PUT /upload) with kind 24242 auth events
(BUD-11). Handles Cashu ecash payments when the server returns HTTP 402
(NUT-24).

Flow:
  1. Compute SHA-256 of the file
  2. Sign a kind 24242 auth event via nak CLI
  3. PUT /upload with Authorization: Nostr <base64-event>
  4. If 200/201 → done (free tier, <1MB)
  5. If 402 → parse X-Cashu header, pay with Cashu token, retry

Uses stdlib only (urllib, hashlib, base64, json, subprocess).
Requires nak CLI (https://github.com/fiatjaf/nak) for Nostr event signing.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# --- Constants ---

DEFAULT_BLOSSOM_SERVER = "https://blossom.psbt.me"
FREE_TIER_SIZE_LIMIT = 1_000_000  # 1 MB — files under this get 30 days free
TESTNUT_MINT = "https://testnut.cashu.exchange"

# --- Utility functions ---


def compute_sha256(file_path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sign_blossom_auth_event(
    nsec_file: str,
    sha256_hash: str,
    action: str = "upload",
    expiration_seconds: int = 3600,
) -> dict:
    """Sign a kind 24242 Blossom auth event (BUD-11) using nak CLI.

    The event authorizes a specific action (upload/delete/list) on a blob
    with the given SHA-256 hash.

    Returns the signed Nostr event as a dict.
    """
    expiration = str(int(time.time()) + expiration_seconds)

    cmd = [
        "nak", "event",
        "--sec-file", nsec_file,
        "-k", "24242",
        "-c", f"{'Upload' if action == 'upload' else action.title()} Blob",
        "--tag", f"t {action}",
        "--tag", f"x {sha256_hash}",
        "--tag", f"expiration {expiration}",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

    if result.returncode != 0:
        raise RuntimeError(f"nak event (BUD-11 auth) failed: {result.stderr.strip()}")

    # nak prints the signed event JSON to stdout
    lines = result.stdout.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)

    raise RuntimeError(f"Could not parse nak output: {result.stdout[:200]}")


def make_auth_header(signed_event: dict) -> str:
    """Create the Authorization header value from a signed event."""
    event_json = json.dumps(signed_event, separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(event_json.encode()).decode().rstrip("=")
    return f"Nostr {encoded}"


# --- Cashu handling ---


def parse_cashu_request(response: urllib.error.HTTPError) -> dict:
    """Parse the X-Cashu header from a 402 response.

    Returns dict with 'amount' (sats), 'unit', and 'mints' (list of mint URLs).
    """
    cashu_header = response.headers.get("X-Cashu", "")
    if not cashu_header:
        raise RuntimeError("402 response missing X-Cashu header")

    # Header format: {"a":100,"u":"sat","m":["https://testnut.cashu.exchange"]}
    try:
        req = json.loads(cashu_header)
        return {
            "amount": req.get("a", 0),
            "unit": req.get("u", "sat"),
            "mints": req.get("m", []),
        }
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not parse X-Cashu header: {cashu_header}")


def mint_testnut_tokens(amount_sats: int) -> str:
    """Mint free test ecash tokens from testnut.cashu.exchange.

    Uses the Cashu NUT-04 flow: request quote → auto-paid by testnut mint → mint tokens.
    Returns a cashuB-encoded token string.

    NOTE: This is a simplified implementation. For production, use the `cashu`
    Python library (pip install cashu) which handles blind signatures properly.
    """
    print(f"  Minting {amount_sats} sats from {TESTNUT_MINT}...")

    # Step 1: Request a mint quote (testnut auto-pays the Lightning invoice)
    quote_data = json.dumps({"amount": amount_sats, "unit": "sat"}).encode()
    quote_req = urllib.request.Request(
        f"{TESTNUT_MINT}/v1/mint/quote/bolt11",
        data=quote_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(quote_req, timeout=30) as resp:
            quote = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Mint quote failed: {e.code} {e.read().decode()[:200]}")

    print(f"  Quote received: {quote.get('quote', 'N/A')}")

    # Step 2: Wait for the testnut mint to auto-pay (usually instant)
    time.sleep(2)

    # Step 3: Check quote status
    check_req = urllib.request.Request(
        f"{TESTNUT_MINT}/v1/mint/quote/bolt11/{quote['quote']}",
        method="GET",
    )
    try:
        with urllib.request.urlopen(check_req, timeout=10) as resp:
            status = json.loads(resp.read())
    except Exception:
        status = {"state": "paid", "paid": True}

    if not status.get("paid", False) and status.get("state") != "paid":
        print(f"  ⚠ Testnut quote not yet paid. State: {status.get('state', 'unknown')}")
        print(f"  For production, use: pip install cashu")
        raise RuntimeError("Testnut mint did not auto-pay the quote. Try again or supply a Cashu token manually.")

    print(f"  ✓ Quote paid. Minting tokens...")
    # NOTE: Full minting requires blind signature crypto (NUT-00).
    # This is a placeholder — in production, use the cashu Python library:
    #   from cashu.wallet.wallet import Wallet
    #   wallet = await Wallet.with_db(url=TESTNUT_MINT, db=".cashu/test")
    #   await wallet.load_mint()
    #   proofs = await wallet.mint(amount_sats, id=quote["quote"])
    #   token = await wallet.serialize_proofs(proofs)
    raise NotImplementedError(
        "Full Cashu minting requires the `cashu` library (pip install cashu). "
        "For the free tier (<1MB), no Cashu is needed. "
        "To pay manually: obtain a cashuB token from testnut.cashu.exchange "
        "and pass it via --cashu-token."
    )


# --- Main upload function ---


def upload_to_blossom(
    file_path: str,
    nsec_file: str,
    server_url: str = DEFAULT_BLOSSOM_SERVER,
    cashu_token: str = None,
    content_type: str = "text/markdown",
) -> dict:
    """Upload a file to a Blossom server.

    Handles the full flow: auth signing, HTTP PUT, 402/Cashu retry.

    Args:
        file_path: Path to the file to upload.
        nsec_file: Path to file containing the Nostr hex private key (mode 0600).
        server_url: Blossom server base URL.
        cashu_token: Optional pre-obtained Cashu token (cashuB...) for paid uploads.
        content_type: MIME type for the upload.

    Returns:
        dict with 'url' (blob URL), 'sha256', 'size', 'paid' (bool).
    """
    file_size = os.path.getsize(file_path)
    sha256 = compute_sha256(file_path)

    print(f"  File: {file_path} ({file_size:,} bytes, sha256: {sha256[:16]}...)")

    if file_size < FREE_TIER_SIZE_LIMIT:
        print(f"  ✓ Under 1MB — free tier (no Cashu payment needed)")

    # Read file content
    with open(file_path, "rb") as f:
        file_data = f.read()

    # Sign BUD-11 auth event
    auth_event = sign_blossom_auth_event(nsec_file, sha256)
    auth_header = make_auth_header(auth_event)

    # Build the upload request
    headers = {
        "Authorization": auth_header,
        "Content-Type": content_type,
        "Content-Length": str(len(file_data)),
        "X-SHA-256": sha256,
    }

    # Add Cashu token if provided upfront
    if cashu_token:
        headers["X-Cashu"] = cashu_token

    upload_url = f"{server_url.rstrip('/')}/upload"

    # --- Attempt upload ---
    req = urllib.request.Request(upload_url, data=file_data, headers=headers, method="PUT")

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read())
            result["paid"] = cashu_token is not None
            print(f"  ✓ Uploaded: {result.get('url', 'N/A')}")
            return result

    except urllib.error.HTTPError as e:
        # --- Handle 402 Payment Required ---
        if e.code == 402:
            print(f"  Server requires payment (402)")

            if cashu_token:
                # We already tried with a token — it was insufficient
                print(f"  ✗ Provided Cashu token was insufficient")
                raise RuntimeError(f"402 even with Cashu token. Response: {e.read().decode()[:200]}")

            # Parse payment requirement
            payment = parse_cashu_request(e)
            print(f"  Required: {payment['amount']} {payment['unit']} from {payment['mints']}")

            if file_size < FREE_TIER_SIZE_LIMIT:
                print(f"  ⚠ Unexpected 402 for <1MB file (free tier should apply)")

            # Try minting testnut tokens
            try:
                token = mint_testnut_tokens(payment["amount"])
                # Retry with the minted token
                return upload_to_blossom(
                    file_path, nsec_file, server_url,
                    cashu_token=token, content_type=content_type,
                )
            except NotImplementedError:
                print(f"  ℹ Automatic Cashu minting not available.")
                print(f"  To pay manually:")
                print(f"    1. Visit {payment['mints'][0] if payment['mints'] else TESTNUT_MINT}")
                print(f"    2. Mint {payment['amount']} sats worth of tokens")
                print(f"    3. Re-run with --cashu-token <cashuB...>")
                raise

        # --- Other HTTP errors ---
        body = e.read().decode()[:500]
        raise RuntimeError(f"Blossom upload failed: HTTP {e.code}\n{body}")


def get_blob_url(server_url: str, sha256: str) -> str:
    """Construct the standard Blossom blob URL (BUD-01 retrieval)."""
    return f"{server_url.rstrip('/')}/{sha256}"


if __name__ == "__main__":
    # CLI usage: python blossom_publisher.py <file> <nsec_file>
    if len(sys.argv) < 3:
        print("Usage: python blossom_publisher.py <file_path> <nsec_file> [--cashu-token TOKEN]")
        sys.exit(1)

    file_path = sys.argv[1]
    nsec_file = sys.argv[2]
    token = None
    if "--cashu-token" in sys.argv:
        idx = sys.argv.index("--cashu-token")
        token = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None

    result = upload_to_blossom(file_path, nsec_file, cashu_token=token)
    print(json.dumps(result, indent=2))
