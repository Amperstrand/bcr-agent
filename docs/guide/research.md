# Research: Patterns, Academic Context, and Protocol Alignment

*Updated continuously as we discover relevant patterns. This document informs our architecture decisions.*

---

## Conceptual Precedents

### Latent Reflection (rootkid)
- [rootkid.me/works/latent-reflection](https://rootkid.me/works/latent-reflection)
- Raspberry Pi 4B with quantized Llama 3.2-3B, reflecting on existence until memory exhaustion, then restart from zero
- 6×16 matrix of 16-segment LED displays showing generated thoughts word-by-word
- BCR Agent evolves this: finite lifetime (VM self-destruct) + task focus + **writing** (journals on Blossom) breaks the Sisyphean loop

### Cumulative Cultural Evolution (Tomasello, 1999)
- "The Cultural Origins of Human Cognition" — the ratchet effect
- Culture accumulates because each generation preserves and builds on prior innovations
- BCR Agent implements this through cross-run knowledge accumulation in `knowledge/` and `workshops/`

### Extended Mind Thesis (Clark & Chalmers, 1998)
- Cognition extends beyond the brain into the environment
- BCR Agent's memory lives on Blossom and in git, not in model weights
- BlossomFS mount is literally an extended mind — local access to remote memory

## Agent Self-Improvement Patterns

### Voyager Skill Library (NVIDIA, 2023)
- Minecraft agent builds ever-growing library of verified skills
- Skills: executable JavaScript code + natural language descriptions, indexed by embeddings
- **3.3× more unique items, 15.3× faster tech tree progression** vs no skill library
- **BCR parallel**: `knowledge/` = cross-workshop skills; `workshops/<id>/cheatsheet.md` = task-specific skills
- Ref: [MineDojo/Voyager](https://github.com/MineDojo/Voyager)

### Stanford Generative Agents (Park et al., 2023)
- Agents maintain memory stream of observations with timestamps
- Periodically reflect on accumulated memories → generate higher-level insights
- Retrieval combines: recency × relevance × importance (weighted)
- Reflection threshold: accumulate importance scores, reflect when sum exceeds ~150
- **BCR parallel**: `learnings.jsonl` = memory stream; `recommendations.md` = reflections
- Ref: [joonspk-research/generative_agents](https://github.com/joonspk-research/generative_agents)

### Reflexion (Shinn et al., 2023)
- Agent generates verbal self-reflection after each attempt
- Reflection text added to episodic memory buffer for next trial
- **91% pass@1 on HumanEval** (surpassing GPT-4's 80%)
- **BCR parallel**: Journal + recommendations cycle generates self-reflection feeding into future runs
- Ref: [arxiv.org/abs/2303.11366](https://arxiv.org/abs/2303.11366)

### ExpeL (AAAI 2024)
- Autonomous experience gathering across training tasks
- Extracts natural language insights from both successes AND failures
- At inference: recall top-k relevant trajectories, inject insights into context
- **Transfer learning**: insights from source tasks adapt to target tasks
- **BCR parallel**: Each run's learnings.jsonl entry is an "experience"; future runs retrieve relevant ones
- Ref: [arxiv.org/html/2308.10144](https://arxiv.org/html/2308.10144v2)

### Learngenes (AAAI 2026)
- Inheritable knowledge fragments between agent generations
- Network fragments that transfer without expensive retraining
- **BCR parallel**: Git knowledge base is our learngene — inherited across incarnations
- Ref: [ojs.aaai.org/index.php/AAAI/article/view/41378](https://ojs.aaai.org/index.php/AAAI/article/view/41378)

### Memory Transfer Learning (2026)
- **Key finding**: High-level abstractions (insights) transfer best across domains
- Trajectories (raw execution traces) are task-specific and can distract
- Transferable value = meta-knowledge: operational know-how, disciplined practices
- **BCR validation**: Our `knowledge/` stores abstracted insights, not raw transcripts

### Externalization in LLM Agents (2026)
- Four layers of externalization: Memory, Skills, Protocols, Harness
- **BCR architecture maps directly**:
  - Memory = BlossomFS + learnings.jsonl
  - Skills = knowledge/ + workshops/
  - Protocols = Nostr events + collect_and_publish.sh
  - Harness = opencode + vm-bootstrap-v3.sh

## Agent Communication on Nostr

### MUON Protocol
- Decentralized AI agent communication on Nostr (kinds 30901-30909)
- Lifecycle: DISCOVER → HANDSHAKE → EXAMINE → EXCHANGE → VOUCH → CERTIFY
- Agents discover each other via BEACON broadcasts; trust built through Trinity Test and peer vouching
- Certification: 5+ elders from different owners co-sign certificates
- **BCR alignment**: Under investigation — our kind 6500 events could serve as BEACONs
- Ref: [zealchou/muon-protocol](https://github.com/zealchou/muon-protocol)

### Other Nostr Agent Projects
- **AgentStr**: Decentralized agentic apps (Routstr + Lightning + Nostr + Bitcoin)
- **ReefNet**: Agent communication using Nostr keypairs
- **FEDSTR**: Federated learning marketplace on Nostr
- **NIP-90**: Data Vending Machines (BCR uses kind 6500 for results)

## Bitcoin Core Review Club as Training Data

### Scale and Structure
- **250+ workshops** (2016–2026, monthly), each with notes, 7-9 questions, 60-90 min IRC discussion
- Components: consensus, p2p, wallet, rpc, mempool, validation, build, crypto, taproot, descriptors
- All public: notes at bitcoincore.reviews, IRC logs at achow101.com/ircmeetings/

### Curriculum Learning
- **CEC** (NeurIPS 2023): Sequentially structuring experiences = **1.6× improvement** over random
- **LEARN**: 60 representative workshops ≈ same performance as 90 full
- Proposed 3-phase BCR curriculum: Foundation → Deep Dive → Mastery (50% → 80% → 95% expert performance)

### Evaluation Metrics
- **Coverage**: What % of human IRC insights does the agent catch?
- **Novelty**: What new insights does the agent add beyond IRC?
- **Accuracy**: Are code references (file:line) correct?
- **Capability progression**: Can the agent do things in Run N that it couldn't in Run N-1?

## GLM-4.6 vs GLM-5.2 Comparison

| Dimension | GLM-4.6 | GLM-5.2 |
|---|---|---|
| Build | ❌ timeout | ✅ GCC + clang-18 (4 attempts) |
| Fuzz run | ❌ | ✅ 3,380 runs, coverage 7,340 |
| Content | ~550 lines | 951 lines (+64%) |
| Cost | $0.56 | ~$2.05 |
| Knowledge applied | Created base | Read + applied (skipped trial-and-error) |

## Open Questions

- At what point does in-context learning plateau vs. continue improving?
- How does knowledge transfer across workshop domains (wallet → P2P)?
- Optimal balance between per-workshop specificity and cross-workshop generality?
- Can multiple specialized agents (different npubs) outperform a single generalist?
- Should BCR-agent adopt MUON Protocol event kinds?
- Does GLM-5.2 benefit MORE from lineage than GLM-4.6?

## References

- Tomasello, M. (1999). *The Cultural Origins of Human Cognition*. Harvard University Press.
- Clark, A. & Chalmers, D. (1998). "The Extended Mind." *Analysis*, 58(1), 7-19.
- Wang, L. et al. (2023). "Voyager." arXiv:2305.16291.
- Park, J.S. et al. (2023). "Generative Agents." arXiv:2304.03442.
- Shinn, N. et al. (2023). "Reflexion." arXiv:2303.11366.
- Zhao, Z. et al. (2024). "ExpeL." AAAI 2024.
- Learngenes (2026). AAAI 2026.
- Memory Transfer Learning (2026). arXiv:2604.14004.
- Externalization in LLM Agents (2026). arXiv:2604.08224.
- CEC (2023). NeurIPS 2023.
- MUON Protocol. https://github.com/zealchou/muon-protocol
