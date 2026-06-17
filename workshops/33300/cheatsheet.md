# Workshop #33300 Cheat Sheet

*Tips, traps, and known solutions from prior BCR-agent runs.*

## PR Context

**PR:** fuzz: compact block harness (cmpctblock fuzz target)
**Branch:** `pr33300` at commit `ed813c48f8`
**What it does:** Adds a libFuzzer harness for BIP 152 compact block relay
**7 commits:** CMPCTBLOCK_VERSION header move, FinalizeHeader refactor, fs::copy wrapper, fuzzcopydatadir, scheduler-less validation, the harness itself, m_dirty_blockindex hash sort

## Build Recipe (Verified Working — Run 2, GLM-5.2)

### GCC build (fast, produces stub binary — can list targets but NOT run them)
```bash
cmake -B build -S . -DBUILD_FUZZ_BINARY=ON -DBUILD_TESTS=ON -DENABLE_IPC=OFF
cd build && make -j$(nproc) fuzz
# Binary: build/bin/fuzz (432 MB)
# Can list targets: PRINT_ALL_FUZZ_TARGETS_AND_ABORT=1 ./build/bin/fuzz | grep cmpct
# CANNOT run: "Must compile with -DBUILD_FOR_FUZZING=ON"
```

### Clang-18 build (CORRECT — runnable fuzzer with sanitizer)
```bash
apt-get install -y clang-18 llvm-18
CC=clang-18 CXX=clang++-18 cmake -B build-fuzz -S . \
    -DBUILD_FOR_FUZZING=ON -DSANITIZERS=fuzzer -DENABLE_IPC=OFF
cd build-fuzz && make -j$(nproc) fuzz
# Binary: build-fuzz/bin/fuzz (241 MB)
# Run: FUZZ=cmpctblock ./build-fuzz/bin/fuzz -runs=10000
```

### Known build traps
- **cmake missing**: `apt-get install -y cmake` (not in default bootstrap)
- **Cap'n Proto missing**: Use `-DENABLE_IPC=OFF`
- **clang-14 too old**: Fails with `consteval` error on GCC 13's libstdc++. Use clang-18.
- **`-DBUILD_FUZZ_BINARY=ON` alone produces stub**: Need `-DBUILD_FOR_FUZZING=ON` for runnable fuzzer
- **Target is `make fuzz`**: No per-harness targets like `fuzz-cmpctblock`
- **Use `setsid` for background builds**: Plain `&` gets killed by tool timeouts

## Fun Exercise: Reproduce Crash from PR #33296

### What the crash is
When `FillBlock()` is called and fails (invalid tx indices), it sets `header.SetNull()` at `blockencodings.cpp:207`. If a second `blocktxn` message arrives for the same block, the code tries `LookupBlockIndex(header.hashPrevBlock)` with an empty header → returns nullptr → `Assume()` crashes in debug builds.

### Exact reproduction steps
1. Revert the fix: `git revert 8b6264768030db1840041abeeaeefd6c227a2644`
2. Rebuild incrementally (only `net_processing.cpp` changes — fast)
3. The functional test `test/functional/p2p_compactblocks.py` has `test_multiple_blocktxn_response()` which reproduces it:
   - Send compact block with `prefill_list=[0]` (only first tx prefilled)
   - Wait for `getblocktxn` (requests indices 1, 2)
   - Send `blocktxn` with WRONG order: indices [2, 1] → FillBlock fails, header SetNull
   - Send SAME `blocktxn` AGAIN → crash at `net_processing.cpp:3513`
4. Run: `./test/functional/p2p_compactblocks.py`
5. Debug build asserts at `Assume(LookupBlockIndex(empty_header))`

### Why random fuzzing won't find it quickly
The crash requires a specific 5-step sequence. Random mutation is unlikely to produce:
1. A valid compact block with prefilled txs
2. Followed by a blocktxn with wrong indices
3. Followed by the SAME blocktxn again

**Use the functional test instead of random fuzzing for reproduction.**

## Key Code Locations

| What | File | Lines |
|---|---|---|
| Fuzz harness | `src/test/fuzz/cmpctblock.cpp` | 1-422 |
| FillBlock (sets header null) | `src/blockencodings.cpp` | 189-210 |
| Crash location (before fix) | `src/net_processing.cpp` | ~3505-3513 |
| Fix (empty header check) | `src/net_processing.cpp` | ~3507-3516 |
| BIP 152 HB peer limit | `src/net_processing.cpp` | 1284 (3 peers) |
| m_dirty_blockindex sort | `src/node/blockstorage.cpp` | determinism fix |
| Functional test for crash | `test/functional/p2p_compactblocks.py` | 558-598 |

## Run History

| Run | Model | Build | Fuzz Run | Crash Repro | Q&A Quality |
|---|---|---|---|---|---|
| 1 | GLM-4.6 | ❌ timeout | ❌ | ❌ | 8/8, ~550 lines |
| 2 | GLM-5.2 | ✅ GCC + clang-18 | ✅ ran cmpctblock | ❌ fuzzed 111s, no crash | 8/8, 951 lines |

## Common Traps for This Workshop

1. **Don't use `-DBUILD_FUZZ_BINARY=ON` alone** — it produces a stub. Use `-DBUILD_FOR_FUZZING=ON`.
2. **Don't try to fuzz to reproduce the crash** — use the functional test instead.
3. **Read the IRC log** — it contains clarifications about the 3-peer HB limit and the determinism discussion.
4. **The `m_dirty_blockindex` sort (Q7)** is about non-determinism from pointer addresses changing between runs — not about performance.
5. **Prefilled transaction index encoding (Q8)** uses differential encoding — read `blockencodings.h:72-80` carefully.
