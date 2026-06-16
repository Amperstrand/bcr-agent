# Review Strategies — What Works

*Accumulated from BCR-agent runs. Future agents read this before starting.*

## Effective Search Patterns

1. **Start with `git log --oneline -10`** — understand what the PR changes before diving into code
2. **grep for protocol message types** — `grep -rn "NetMsgType::CMPCTBLOCK" src/` finds all handling code
3. **Read test files first** — fuzz harnesses and unit tests show intended behavior
4. **Use offset/limit when reading** — don't read entire 6000-line files; grep first, then read specific ranges
5. **Check the IRC log** — workshop IRC discussions contain crucial clarifications not in the questions
6. **git show for commit context** — `git show <hash>` shows exactly what changed and why
7. **Follow class definitions** — `grep -rn "class ClassName" src/ --include="*.h"` to find data structures

## Question Answering Strategy

1. **Q1 (build/fuzz)**: Attempt the build but don't spend >10 min. If it fails, document what you tried and move on. Read the fuzz harness source code instead.
2. **Conceptual questions**: grep for the relevant constants/functions, read the code around them, check BIPs if relevant.
3. **Implementation questions**: Read the actual code with line numbers. Reference specific files and lines.
4. **Always check git history** — `git log --oneline -- <file>` shows recent changes that may be relevant.

## Time Management

- Budget ~10 min per question (8 questions in 80 min)
- Don't spend >15 min on any single question
- If the build is taking too long, document the attempt and move on
- Save time for the journal and recommendations — they're mandatory

## Run History

| Run | Workshop | Duration | Quality Notes |
|---|---|---|---|
| 1 | #33300 | ~24 min | All 8 answered. Build failed (timeout). Strong code reading analysis. |
