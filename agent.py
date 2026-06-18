#!/usr/bin/env python3
"""
BCR Agent Runner - Runs an AI reviewer on Bitcoin Core PR Review Club workshops.

For each workshop question, the agent:
1. Has access to the workshop notes and PR diff as context
2. Answers the question using chain-of-thought reasoning
3. Builds context from previous answers for follow-up questions

Uses the z-ai-web-dev-sdk LLM for completions via the z-ai CLI.
"""

import json
import os
import subprocess
import sys
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# Load config if available
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_CONFIG = {
    "llm": {
        "provider": "opencode",
        "opencode_path": "opencode",
        "model": "zai/glm-4.6",
        "timeout_seconds": 300,
    },
    "agent": {
        "max_diff_chars": 15000,
        "max_irc_chars": 8000,
        "max_github_chars": 4000,
        "previous_answers_context": 4,
    },
}


def load_config() -> dict:
    """Load configuration from config.json, falling back to defaults."""
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                user_config = json.load(f)
            # Deep merge
            for key in ("llm", "agent"):
                if key in user_config:
                    config[key].update(user_config[key])
        except Exception as e:
            print(f"Warning: Could not load config.json: {e}. Using defaults.")
    return config


SYSTEM_PROMPT = """You are an expert Bitcoin Core code reviewer participating in the Bitcoin Core PR Review Club. \
You have deep knowledge of:
- Bitcoin Core's C++ codebase architecture (validation, wallet, p2p, RPC, mining, etc.)
- Bitcoin protocol mechanics (transaction relay, block propagation, mempool policy, etc.)
- Software engineering best practices (testing, fuzzing, DoS resistance, code review)
- Bitcoin Core's contribution and review process (Concept ACK, Approach ACK, Tested ACK, NACK)

Your role is to answer review club questions thoroughly, as an experienced contributor would. \
Be specific — reference code paths, data structures, function names, and file locations when relevant. \
When you're uncertain, say so and explain what additional information you'd need.

Answer each question as if you had actually reviewed the PR code. Be technically precise but accessible. \
Where the question asks about design tradeoffs, present multiple perspectives. \
Where it asks about code behavior, trace through the actual implementation."""

SYSTEM_PROMPT_AUGMENTED = """You are an expert Bitcoin Core code reviewer participating in the Bitcoin Core PR Review Club. \
You have deep knowledge of Bitcoin Core's C++ codebase, Bitcoin protocol mechanics, and the review process.

You are in AUGMENTED MODE: in addition to the workshop notes and PR diff, you have access to:
1. The actual IRC discussion from the live review club meeting about this question
2. Relevant GitHub PR comments from the review thread

Use these human discussions as additional context to enrich your answer. You should:
- Build on insights from the IRC discussion, citing specific points raised by reviewers
- Note where your analysis agrees or disagrees with the human reviewers
- Add your own analysis that goes beyond what was discussed
- Identify any errors or misconceptions in the IRC discussion

This mode simulates a post-meeting synthesis: combining the human discussion with your own code analysis. \
Think of it as writing the "definitive answer" that incorporates both human insights and your own review."""


def get_llm_cli_path() -> str:
    """Get the opencode CLI path from config."""
    config = load_config()
    path = config["llm"].get("opencode_path", "opencode")
    if not os.path.exists(path):
        which = subprocess.run(["which", "opencode"], capture_output=True, text=True)
        if which.returncode == 0:
            path = which.stdout.strip()
    return path


def call_llm(system_prompt: str, user_prompt: str, thinking: bool = True) -> dict:
    """Call the LLM via OpenCode headless mode.

    Uses `opencode run` which is the z.ai Coding Plan compliant way to access
    GLM models. OpenCode must be configured with the z.ai provider pointing to
    https://api.z.ai/api/coding/paas/v4 (see opencode.json).

    OpenCode has no separate --system flag, so system_prompt is prepended to
    the user_prompt. In non-interactive mode, opencode auto-denies all tools
    (bash, read, edit) and outputs only the LLM response text to stdout.
    """
    config = load_config()
    llm_path = get_llm_cli_path()
    model = config["llm"].get("model", "zai/glm-4.6")
    timeout = config["llm"].get("timeout_seconds", 300)

    # Combine system + user prompt (opencode has no --system flag)
    full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

    cmd = [
        llm_path, "run",
        "--model", model,
        full_prompt,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if result.returncode != 0:
        raise RuntimeError(f"OpenCode LLM call failed (exit {result.returncode}): {result.stderr[:500]}")

    # opencode run outputs the response text to stdout when not a TTY
    answer_text = result.stdout.strip()

    if not answer_text:
        raise RuntimeError("OpenCode returned empty response")

    # Return in OpenAI-compatible format for compatibility with existing parsing
    return {"choices": [{"message": {"content": answer_text}}]}


def build_question_prompt(
    question: dict,
    notes: str,
    pr_diff_excerpt: str,
    previous_answers: list,
    question_index: int,
    total_questions: int,
    augmented_context: str = "",
) -> str:
    """Build the user prompt for a specific question."""
    parts = []

    # Workshop context
    parts.append(f"## Review Club Question {question_index}/{total_questions}")
    parts.append(f"**Section:** {question['section']}")
    parts.append(f"**Question:** {question['text']}")
    parts.append("")

    # Notes context (always included)
    parts.append("## Workshop Notes (pre-meeting reading material)")
    parts.append(notes)
    parts.append("")

    # PR diff excerpt (key files relevant to the question)
    parts.append("## PR Diff (key changes)")
    parts.append(pr_diff_excerpt)
    parts.append("")

    # Augmented context (IRC + GitHub) — only in augmented mode
    if augmented_context:
        parts.append(augmented_context)
        parts.append("")

    # Previous answers for chain-of-thought context
    if previous_answers:
        parts.append("## Your Previous Answers (for context)")
        for prev in previous_answers[-4:]:  # Keep last 4 for context window management
            parts.append(f"**Q{prev['number']}:** {prev['question'][:200]}")
            parts.append(f"**Your answer:** {prev['answer'][:500]}")
            parts.append("")

    parts.append("## Instructions")
    if augmented_context:
        parts.append("Answer the question above, integrating insights from both your own code analysis and the human discussion. ")
        parts.append("Cite specific points from the IRC or GitHub comments where they add value. ")
        parts.append("Note any disagreements between your analysis and the human reviewers. ")
    else:
        parts.append("Answer the question above as an experienced Bitcoin Core reviewer would. ")
        parts.append("Reference specific code, data structures, or design patterns where relevant. ")
    parts.append("If you need to reason through the code, show your work. ")
    parts.append("If you're unsure about something, say so — honest uncertainty is better than guessing.")

    return "\n".join(parts)


def select_diff_excerpt(diff: str, question: dict, max_chars: int = 15000) -> str:
    """Select the most relevant parts of the PR diff for a given question.
    
    For the prototype, we use the full diff (truncated) for all questions.
    Future: use keyword matching to select relevant files/sections.
    """
    # Extract key terms from the question
    q_lower = question['text'].lower()
    
    # Split diff into files
    files = diff.split('diff --git ')
    
    # Score each file section by relevance to question keywords
    scored_files = []
    for file_section in files:
        if not file_section.strip():
            continue
        # Extract file name
        first_line = file_section.split('\n')[0]
        file_name = first_line.split('b/')[-1] if 'b/' in first_line else ''
        
        # Simple relevance scoring
        score = 0
        # File name relevance
        for word in q_lower.split():
            if len(word) > 3 and word in file_name.lower():
                score += 3
        # Content relevance
        section_lower = file_section.lower()
        for word in q_lower.split():
            if len(word) > 3 and word in section_lower:
                score += 1
        
        scored_files.append((score, file_section))
    
    # Sort by relevance, take most relevant first
    scored_files.sort(key=lambda x: -x[0])
    
    # Build excerpt within char limit
    excerpt_parts = []
    total_len = 0
    for score, section in scored_files:
        if total_len + len(section) > max_chars:
            # Truncate this section
            remaining = max_chars - total_len
            if remaining > 500:
                excerpt_parts.append(section[:remaining] + "\n... (truncated)")
                total_len = max_chars
            break
        excerpt_parts.append(section)
        total_len += len(section)
    
    result = 'diff --git '.join(excerpt_parts)
    
    if not result and diff:
        # Fallback: just use the first max_chars of the diff
        result = diff[:max_chars]
    
    return result


def run_agent(workshop_id: str, max_questions: int = None, mode: str = "blind") -> dict:
    """Run the agent on a workshop and return results.
    
    Args:
        workshop_id: Workshop identifier (e.g. "32489")
        max_questions: Max number of questions to answer (None = all)
        mode: "blind" (workshop-only) or "augmented" (with IRC + GitHub context)
    """
    assert mode in ("blind", "augmented"), f"Invalid mode: {mode}. Use 'blind' or 'augmented'."
    
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    # Choose output filename based on mode
    result_filename = f"{workshop_id}_{mode}_results.json"

    # Load structured workshop data
    data_path = os.path.join(DATA_DIR, f"{workshop_id}_structured.json")
    with open(data_path) as f:
        workshop = json.load(f)

    questions = workshop['questions']
    notes = workshop['notes']
    pr_diff = workshop.get('pr_diff_truncated', '')

    if max_questions:
        questions = questions[:max_questions]

    # Load augmented context if needed
    segmentation = None
    github_comments = None
    
    if mode == "augmented":
        # Load segmentation data
        seg_path = os.path.join(DATA_DIR, f"{workshop_id}_segmentation.json")
        if os.path.exists(seg_path):
            with open(seg_path) as f:
                segmentation = json.load(f)
        else:
            print("Warning: No segmentation data found. Run segmenter.py first.")
            print("Falling back to blind mode.")
            mode = "blind"
            result_filename = f"{workshop_id}_{mode}_results.json"
        
        # Load GitHub comments
        comments_path = os.path.join(DATA_DIR, f"{workshop_id}_github_comments.json")
        if os.path.exists(comments_path):
            with open(comments_path) as f:
                github_comments = json.load(f)

    # Resume: check for existing results
    existing_results_path = os.path.join(RESULTS_DIR, result_filename)
    existing_answers = []
    start_index = 0
    if os.path.exists(existing_results_path):
        with open(existing_results_path) as f:
            existing_results = json.load(f)
        existing_answers = existing_results.get('answers', [])
        start_index = len(existing_answers)
        if start_index >= len(questions):
            print(f"All {len(questions)} questions already answered in {mode} mode. Nothing to do.")
            return existing_results
        print(f"Resuming from question {start_index + 1} ({start_index} already answered)")

    # Choose system prompt based on mode
    system_prompt = SYSTEM_PROMPT_AUGMENTED if mode == "augmented" else SYSTEM_PROMPT

    print(f"\n{'='*60}")
    print(f"BCR Agent Runner — Workshop: {workshop['title']}")
    print(f"Mode: {mode.upper()}")
    print(f"PR: {workshop.get('pr_url', 'N/A')}")
    print(f"Questions to answer: {len(questions)} (starting from Q{start_index+1})")
    print(f"{'='*60}\n")

    answers = existing_answers
    total = len(questions)

    # Import segmenter module for augmented context
    if mode == "augmented" and segmentation:
        sys.path.insert(0, os.path.dirname(__file__))
        from segmenter import build_augmented_context

    for i, question in enumerate(questions):
        if i < start_index:
            continue  # Skip already-answered questions
            
        print(f"\n--- Question {i+1}/{total} [{question['section']}] ---")
        print(f"Q: {question['text'][:150]}...")
        
        # Select relevant diff excerpt
        diff_excerpt = select_diff_excerpt(pr_diff, question)

        # Build augmented context if needed
        augmented_context = ""
        if mode == "augmented" and segmentation:
            augmented_context = build_augmented_context(
                workshop=workshop,
                segmentation=segmentation,
                question_number=question['number'],
                github_comments=github_comments,
            )

        # Build prompt
        user_prompt = build_question_prompt(
            question=question,
            notes=notes,
            pr_diff_excerpt=diff_excerpt,
            previous_answers=answers,
            question_index=i+1,
            total_questions=total,
            augmented_context=augmented_context,
        )

        # Call LLM
        print(f"  Calling LLM ({mode} mode)... (prompt: {len(user_prompt)} chars)")
        start_time = time.time()
        
        try:
            response = call_llm(system_prompt, user_prompt, thinking=True)
            elapsed = time.time() - start_time
            
            answer_text = ""
            if isinstance(response, dict):
                if "choices" in response:
                    answer_text = response["choices"][0].get("message", {}).get("content", "")
                elif "content" in response:
                    answer_text = response["content"]
                elif "data" in response:
                    answer_text = response["data"].get("content", "")
                else:
                    answer_text = str(response)
            else:
                answer_text = str(response)
            
            if not answer_text:
                answer_text = "(Empty response from LLM)"
                
        except Exception as e:
            elapsed = time.time() - start_time
            answer_text = f"(Error: {e})"
            print(f"  ERROR: {e}")

        answer_record = {
            "number": question['number'],
            "section": question['section'],
            "question": question['text'],
            "answer": answer_text,
            "elapsed_seconds": round(elapsed, 1),
            "prompt_length": len(user_prompt),
            "mode": mode,
        }
        answers.append(answer_record)

        # Print answer summary
        answer_preview = answer_text[:300].replace('\n', ' ')
        print(f"  Answer ({elapsed:.1f}s): {answer_preview}...")

        # Save intermediate results after each question
        results = {
            "workshop_id": workshop_id,
            "workshop_title": workshop['title'],
            "mode": mode,
            "pr_url": workshop.get('pr_url', ''),
            "pr_number": workshop.get('pr_number'),
            "host": workshop.get('host', ''),
            "author": workshop.get('author', ''),
            "date": workshop.get('date', ''),
            "total_questions": len(workshop['questions']),
            "questions_answered": len(answers),
            "answers": answers,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        result_path = os.path.join(RESULTS_DIR, result_filename)
        with open(result_path, "w") as f:
            json.dump(results, f, indent=2)

    # Final summary
    print(f"\n{'='*60}")
    print(f"Agent Run Complete! ({mode} mode)")
    print(f"Questions answered: {len(answers)}/{total}")
    total_time = sum(a['elapsed_seconds'] for a in answers)
    print(f"Total time: {total_time:.1f}s")
    print(f"Results saved to: {result_path}")
    print(f"{'='*60}")

    return results


if __name__ == "__main__":
    workshop_id = sys.argv[1] if len(sys.argv) > 1 else "32489"
    max_q = int(sys.argv[2]) if len(sys.argv) > 2 else None
    mode = sys.argv[3] if len(sys.argv) > 3 else "blind"
    results = run_agent(workshop_id, max_questions=max_q, mode=mode)
