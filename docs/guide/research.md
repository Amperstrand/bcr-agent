# Research: Patterns and Academic Context

*This document is updated as we discover relevant patterns from academic literature and industry practice.*

## Conceptual Precedents

### Latent Reflection (rootkid)
- [rootkid.me/works/latent-reflection](https://rootkid.me/works/latent-reflection)
- A Raspberry Pi reflects on its existence until memory exhaustion, then restarts from zero
- BCR Agent evolves this concept by adding persistent writing (journals on Blossom)

### Cumulative Cultural Evolution (Tomasello)
- "The Cultural Origins of Human Cognition" (1999)
- The "ratchet effect": culture accumulates because each generation preserves and builds on prior innovations
- BCR Agent implements this through cross-run knowledge accumulation

### Extended Mind Thesis (Clark & Chalmers)
- "The Extended Mind" (1998)
- Cognition extends beyond the brain into the environment (notebooks, tools)
- BCR Agent's memory lives on Blossom and in git, not in the model weights

## Agent Self-Improvement Patterns

### Voyager Skill Library (NVIDIA, 2023)
- Minecraft agent builds an ever-growing library of verified skills
- Skills stored as executable code + natural language descriptions
- Retrieved via vector similarity search
- **BCR parallel**: `knowledge/` directory is our skill library; `workshops/<id>/cheatsheet.md` is per-task skills

### Generative Agents (Stanford, Park et al., 2023)
- Agents maintain a "memory stream" of observations
- Periodically reflect on accumulated memories to generate higher-level insights
- Retrieval combines recency, relevance, and importance
- **BCR parallel**: `learnings.jsonl` is our memory stream; recommendations.md are our reflections

### Reflexion (Shinn et al., 2023)
- Agent reflects on failures and generates verbal reinforcement
- Self-reflection text is added to the prompt for the next attempt
- **BCR parallel**: The journal + recommendations cycle generates self-reflection that feeds into future runs

### Case-Based Reasoning (CBR)
- Classical AI pattern: Retrieve → Reuse → Revise → Retain
- Find similar past problems, apply their solutions, adapt, save new case
- **BCR parallel**: Workshop cheat sheets are "cases"; agent retrieves relevant case, applies learnings, writes updated case

### Contextual Experience Replay (CER, 2025)
- Accumulate past trajectories, distill environment dynamics
- Retrieve relevant experiences during new tasks
- Reported +51% success rate improvement on WebArena
- **BCR parallel**: BlossomFS lineage pre-fetch gives the agent access to full session transcripts from prior runs

## Agent Communication Patterns

### Nostr as Agent Coordination Layer
- Nostr's decentralized, relay-based architecture is well-suited for agent communication
- NIP-90 (Data Vending Machines) defines machine-readable job requests/results
- Blossom (BUD-02) provides content-addressed file storage
- **BCR usage**: Results published as kind 6500 events with Blossom URLs; future agents could subscribe to other agents' events

### Multi-Agent Knowledge Sharing
- Future vision: multiple BCR-agents under different npubs
- Each agent mounts others' Blossom stores read-only
- Specialized agents (security, performance, protocol) contribute to shared knowledge
- Nostr relays serve as the discovery layer

## Evaluation Frameworks

### Measuring Agent Improvement
- **Coverage**: What % of human IRC insights did the agent catch?
- **Novelty**: What new insights did the agent add beyond the IRC discussion?
- **Accuracy**: Were the agent's code references correct? (file:line verified)
- **Capability progression**: Can the agent do things in Run N that it couldn't in Run N-1?

### Bitcoin Core Review Club as Benchmark
- 250+ workshops with structured Q&A and IRC ground truth
- Natural difficulty gradient: documentation → RPC → consensus → P2P → fuzzing
- Ongoing: new workshops weekly provide continuous evaluation
- Open: all discussions, code, and PRs are publicly accessible

## Open Questions

- At what point does in-context learning plateau vs. continue improving?
- How does knowledge from one workshop domain transfer to another?
- What's the optimal balance between specificity (per-workshop) and generality (cross-workshop) in the knowledge base?
- Can multiple specialized agents (different npubs) outperform a single generalist agent?
- How does model choice (GLM-4.6 vs 5.2 vs future models) interact with accumulated knowledge?

## References

- Tomasello, M. (1999). *The Cultural Origins of Human Cognition*. Harvard University Press.
- Clark, A. & Chalmers, D. (1998). "The Extended Mind." *Analysis*, 58(1), 7-19.
- Wang, L. et al. (2023). "Voyager: An Open-Ended Embodied Agent with Large Language Models." arXiv:2305.16291.
- Park, J.S. et al. (2023). "Generative Agents: Interactive Simulacra of Human Behavior." arXiv:2304.03442.
- Shinn, N. et al. (2023). "Reflexion: Language Agents with Verbal Reinforcement Learning." arXiv:2303.11366.
