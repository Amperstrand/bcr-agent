# Bitcoin Core Build System — Accumulated Knowledge

*Updated after each BCR-agent run. Future agents read this before starting.*

## CMake Configuration

Bitcoin Core uses CMake (as of 2025). Key flags for fuzz testing:

```bash
cd /workspace/bitcoin && mkdir -p build && cd build
cmake -B . -S .. -DBUILD_FUZZ_BINARY=ON -DBUILD_TESTS=ON -DENABLE_IPC=OFF
```

- **`-DENABLE_IPC=OFF`**: Required when Cap'n Proto is not installed. The error message tells you this.
- **`-DBUILD_FUZZ_BINARY=ON`**: Enables fuzz target compilation.
- **`-DBUILD_TESTS=ON`**: Enables unit tests.

## Build Targets

| Target | What It Does | Build Time |
|---|---|---|
| `make test_fuzz` | Fuzz utility library only | ~2 min |
| `make fuzz` | Full fuzz binary (ALL 131+ harnesses) | ~15-20 min on 4 vCPU |
| `make check` | Unit tests | ~10 min |

- There is **no** per-harness target like `fuzz-cmpctblock`. All fuzz harnesses are compiled into one binary.
- The binary is at `build/src/test/fuzz/fuzz` after successful build.
- Run a specific harness: `./build/src/test/fuzz/fuzz --run=list` to see all targets, then `./build/src/test/fuzz/fuzz RUN_cmpctblock`.

## Build System Notes

- Bitcoin Core uses **make**, not ninja. Don't try `ninja` commands.
- Use `make -j$(nproc)` for parallel builds.
- ccache is not installed by default but would significantly speed up rebuilds.
- The build requires: build-essential, libboost-all-dev, libsqlite3-dev, libevent-dev, pkg-config, libssl-dev.

## Run History

| Run | Workshop | Build Result | Notes |
|---|---|---|---|
| 1 | #33300 | Partial (`test_fuzz` only) | Full `make fuzz` timed out. Cap'n Proto missing, fixed with `-DENABLE_IPC=OFF`. |
