#!/usr/bin/env python3
"""
BCR Agent — Secret Scanner

Multi-layer secret detection and redaction for files destined for public publishing.
Guarantees that nsec, z.ai API keys, Hetzner tokens, Cashu tokens, and other secrets
never appear in any artifact uploaded to Blossom.

Three layers:
  1. Blocklist — files that must NEVER be published (opencode.json, config.json, etc.)
  2. Regex patterns — known secret formats (nsec1..., z.ai keys, Cashu tokens, GitHub tokens)
  3. Context-aware hex detection — 64-char hex strings near key-related keywords

Usage:
  from secret_scanner import scan_file, scan_directory, should_publish

  sanitized, findings = scan_file("results/report.txt")
  if sanitized is None:
      print("BLOCKED: file must not be published")
  elif findings:
      print(f"WARN: {len(findings)} secrets redacted")
  # Write sanitized content to blossomfs
"""

import json
import math
import os
import re
import sys
from typing import Tuple

# --- Layer 1: Files that must NEVER be published ---

NEVER_PUBLISH_EXACT = {
    "opencode.json",
    "config.json",
    "config.local.json",
    ".env",
    ".env.local",
    ".env.production",
    "secrets",
    "secrets.json",
    "secrets.yaml",
    "bot_nsec",
    "bot_nsec.txt",
    "nsec.txt",
    "nsec",
    "id_rsa",
    "id_ed25519",
    ".npmrc",
    ".pypirc",
    "cloud-init.yaml",
    "blossomfs.toml",
}

NEVER_PUBLISH_SUFFIXES = (
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".keystore",
)

NEVER_PUBLISH_SUBSTRINGS = (
    "nsec",
    "secret",
    "credential",
    "api-key",
    "apikey",
    "token",
)

# --- Layer 2: Regex patterns for known secret formats ---

REGEX_PATTERNS = [
    (
        re.compile(r"nsec1[023456789acdefghjklmnpqrstuvwxyz]{58}"),
        "nostr-nsec-bech32",
    ),
    (
        re.compile(r"[a-f0-9]{32}\.[A-Za-z0-9]{16}"),
        "zai-api-key",
    ),
    (
        re.compile(r"cashu[AB][a-zA-Z0-9+/=]{20,}"),
        "cashu-token",
    ),
    (
        re.compile(r"\b(gho_|ghp_|github_pat_)[A-Za-z0-9_]{36,}\b"),
        "github-token",
    ),
    (
        re.compile(r"\bsk-[a-zA-Z0-9]{40,}\b"),
        "openai-key",
    ),
    (
        re.compile(r"\b(HCLOUD_TOKEN|HETZNER_TOKEN)\s*[=:]\s*[A-Za-z0-9]{64}\b"),
        "hetzner-token",
    ),
    (
        re.compile(r"\b(ZAI_API_KEY|Z_AI_API_KEY|OPENCODE_API_KEY)\s*[=:]\s*[A-Za-z0-9._]{20,}\b"),
        "api-key-assignment",
    ),
]

# --- Layer 3: Context-aware hex private key detection ---

HEX_KEY_CONTEXT = re.compile(
    r"(?:nsec|private[_\s-]?key|secret[_\s-]?key|NOSTR_SECRET_KEY|BOT_NSEC|"
    r"signing[_\s-]?key|auth[_\s-]?key)\s*[:=]\s*"
    r"([a-f0-9]{64})",
    re.IGNORECASE,
)

# Bare 64-char hex that's NOT preceded by sha256/hash/checksum context
BARE_HEX_64 = re.compile(r"(?<![0-9a-fA-F])([a-f0-9]{64})(?![0-9a-fA-F])")

SAFE_HEX_CONTEXTS = re.compile(
    r"(?:sha[_\s-]?256|hash|checksum|digest|etag|blob[_\s-]?id|content[_\s-]?address|"
    r"commit|tree|git|x-ref|refer)",
    re.IGNORECASE,
)

# --- Entropy analysis ---


def shannon_entropy(data: str) -> float:
    if not data:
        return 0.0
    freq = {}
    for c in data:
        freq[c] = freq.get(c, 0) + 1
    n = len(data)
    return -sum((f / n) * math.log2(f / n) for f in freq.values())


def is_high_entropy_hex(s: str, threshold: float = 3.2) -> bool:
    if len(s) < 32:
        return False
    return shannon_entropy(s) >= threshold


# --- Core scanning functions ---


def is_blocked_file(file_path: str) -> bool:
    basename = os.path.basename(file_path)
    if basename in NEVER_PUBLISH_EXACT:
        return True
    if basename.endswith(NEVER_PUBLISH_SUFFIXES):
        return True
    lower = basename.lower()
    for substr in NEVER_PUBLISH_SUBSTRINGS:
        if substr in lower and not basename.endswith((".py", ".js", ".html", ".css", ".md")):
            if basename not in ("secret_scanner.py",):
                return True
    return False


def scan_content(content: str) -> Tuple[str, list]:
    """Scan content for secrets. Returns (sanitized_content, findings_list)."""
    sanitized = content
    findings = []

    for pattern, name in REGEX_PATTERNS:
        for match in pattern.finditer(sanitized):
            findings.append({
                "type": name,
                "preview": match.group()[:12] + "...",
                "pos": match.start(),
            })
            sanitized = (
                sanitized[: match.start()]
                + f"[REDACTED:{name}]"
                + sanitized[match.end() :]
            )

    for match in HEX_KEY_CONTEXT.finditer(sanitized):
        hex_val = match.group(1)
        findings.append({
            "type": "hex-privkey-in-context",
            "preview": hex_val[:12] + "...",
            "pos": match.start(1),
        })
        sanitized = (
            sanitized[: match.start(1)]
            + "[REDACTED:hex-key]"
            + sanitized[match.end(1) :]
        )

    start = 0
    while True:
        match = BARE_HEX_64.search(sanitized, start)
        if not match:
            break
        hex_val = match.group(1)
        context_before = sanitized[max(0, match.start() - 80) : match.start()]
        if SAFE_HEX_CONTEXTS.search(context_before):
            start = match.end()
            continue
        if is_high_entropy_hex(hex_val):
            findings.append({
                "type": "suspicious-bare-hex",
                "preview": hex_val[:12] + "...",
                "pos": match.start(),
            })
            sanitized = (
                sanitized[: match.start()]
                + "[REDACTED:hex]"
                + sanitized[match.end() :]
            )
        start = match.end()

    return sanitized, findings


def scan_file(file_path: str) -> Tuple[str | None, list]:
    """Scan a single file.

    Returns:
        (sanitized_content, findings) — content is None if file is blocked.
        findings is a list of dicts with type/preview/pos.
    """
    if is_blocked_file(file_path):
        return None, [{"type": "blocked-file", "filename": os.path.basename(file_path)}]

    try:
        with open(file_path, "r", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return None, [{"type": "read-error", "filename": file_path, "error": str(e)}]

    sanitized, findings = scan_content(content)
    return sanitized, findings


def scan_directory(dir_path: str, skip_dirs: set = None) -> dict:
    """Scan all files in a directory tree.

    Returns:
        {
            "scanned": int,
            "blocked": [filenames],
            "clean": [filenames],
            "redacted": [{filename, finding_count, findings}],
            "errors": [{filename, error}],
        }
    """
    if skip_dirs is None:
        skip_dirs = {".git", "__pycache__", ".omo", "node_modules", ".cache"}

    result = {
        "scanned": 0,
        "blocked": [],
        "clean": [],
        "redacted": [],
        "errors": [],
    }

    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            fpath = os.path.join(root, fname)
            result["scanned"] += 1

            sanitized, findings = scan_file(fpath)

            if sanitized is None:
                if findings and findings[0]["type"] == "blocked-file":
                    result["blocked"].append(fpath)
                else:
                    result["errors"].append({"filename": fpath, "error": findings[0].get("error", "unknown")})
            elif findings:
                result["redacted"].append({
                    "filename": fpath,
                    "count": len(findings),
                    "findings": [{"type": f["type"], "preview": f["preview"]} for f in findings],
                })
            else:
                result["clean"].append(fpath)

    return result


def verify_clean(file_path: str) -> bool:
    """Verify a file is safe to publish. Returns True if no secrets detected."""
    sanitized, findings = scan_file(file_path)
    return sanitized is not None and len(findings) == 0


def verify_content_clean(content: str) -> bool:
    """Verify content is safe to publish. Returns True if no secrets detected."""
    _, findings = scan_content(content)
    return len(findings) == 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python secret_scanner.py <file_or_directory>")
        print("       python secret_scanner.py --verify <file>")
        sys.exit(1)

    target = sys.argv[1]

    if sys.argv[1] == "--verify" and len(sys.argv) > 2:
        target = sys.argv[2]
        if os.path.isdir(target):
            result = scan_directory(target)
            print(json.dumps(result, indent=2))
            sys.exit(0 if not result["blocked"] and not result["redacted"] else 1)
        else:
            ok = verify_clean(target)
            print(f"{'CLEAN' if ok else 'SECRETS FOUND'}: {target}")
            sys.exit(0 if ok else 1)

    if os.path.isdir(target):
        result = scan_directory(target)
        print(json.dumps(result, indent=2))
    else:
        sanitized, findings = scan_file(target)
        if sanitized is None:
            print(f"BLOCKED: {target}")
        elif findings:
            print(f"REDACTED {len(findings)} secrets in {target}:")
            for f in findings:
                print(f"  [{f['type']}] {f.get('preview', '?')}")
        else:
            print(f"CLEAN: {target}")
