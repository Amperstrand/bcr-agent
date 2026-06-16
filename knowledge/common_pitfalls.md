# Common Pitfalls — Things That Repeatedly Fail

*Accumulated from BCR-agent runs. Future agents read this to avoid repeating mistakes.*

## Build Pitfalls

- **Cap'n Proto missing**: Use `-DENABLE_IPC=OFF`. The cmake error message tells you this.
- **`ninja` not found**: Bitcoin Core uses `make`, not `ninja`. Don't try ninja.
- **`fuzz-cmpctblock` target doesn't exist**: The target is just `make fuzz` (all harnesses in one binary).
- **Full build timeout**: 131+ fuzz targets take 15-20 min. If you're short on time, build `make test_fuzz` instead (just the library, ~2 min).
- **Missing `-j` flag**: Always use `make -j$(nproc) <target>` for parallel compilation.

## Analysis Pitfalls

- **Skipping the IRC log**: The IRC discussion contains clarifications and context not in the questions. Always read it.
- **Making up line numbers**: Only reference lines you've actually seen. Use the Read tool to verify.
- **Theoretical reasoning without code**: Every claim must be backed by code you read. Don't guess.
- **Spending too long on builds**: If the build hasn't finished in 10 min, move on to code reading.

## Tool Pitfalls

- **Reading entire large files**: Use `grep -n` first to find relevant lines, then read specific ranges.
- **Not batching commands**: Run multiple grep searches in parallel when possible.
- **Forgetting journal entries**: Update the journal after EACH question, not at the end.
