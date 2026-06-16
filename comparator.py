#!/usr/bin/env python3
"""
BCR Comparator - Compares agent answers against IRC meeting log discussions.

For each workshop question:
1. Extracts the relevant IRC discussion (messages around when the question was asked)
2. Uses an LLM to compare the agent's answer with the human discussion
3. Produces a coverage report: what the agent caught, what it missed, and what it added
"""

import json
import os
import sys
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

sys.path.insert(0, os.path.dirname(__file__))
from agent import call_llm as agent_call_llm


def call_llm(system_prompt: str, user_prompt: str) -> str:
    response = agent_call_llm(system_prompt, user_prompt, thinking=True)
    return response.get("choices", [{}])[0].get("message", {}).get("content", "")


def extract_irc_segment_for_question(log: list, question_text: str, question_idx: int, total_questions: int) -> list:
    """Extract the IRC log segment relevant to a specific question.
    
    Strategy: Find when the host asks this question, then collect messages
    until the next question is asked or the meeting ends.
    """
    # Keywords from the question to search for in the log
    q_keywords = set()
    for word in question_text.split():
        if len(word) > 4:
            q_keywords.add(word.lower())
    
    # Find the start: when the host (or anyone) mentions keywords from this question
    start_idx = None
    for i, entry in enumerate(log):
        msg_lower = entry["message"].lower()
        # Match if the message contains several keywords from the question
        matches = sum(1 for kw in q_keywords if kw in msg_lower)
        if matches >= min(3, len(q_keywords)):
            start_idx = i
            break
    
    if start_idx is None:
        # Fallback: distribute the log evenly across questions
        segment_size = len(log) // total_questions
        start_idx = question_idx * segment_size
    
    # Find the end: next question or end of log
    end_idx = len(log)
    if question_idx < total_questions - 1:
        # Look for the next question topic change
        next_q_text = None  # We'd need the next question text
        # Simple heuristic: look for the host asking something new
        for i in range(start_idx + 5, len(log)):
            msg = log[i]["message"]
            # Heuristic: if a message starts with a number and contains a question mark,
            # it's likely the next question
            if (msg.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")) 
                and "?" in msg):
                end_idx = i
                break
    
    return log[start_idx:end_idx]


def format_irc_segment(segment: list) -> str:
    """Format IRC log segment as readable text."""
    lines = []
    for entry in segment:
        lines.append(f"[{entry['time']}] {entry['nick']}: {entry['message']}")
    return "\n".join(lines)


def compare_answer_vs_irc(question: dict, agent_answer: str, irc_segment: str) -> dict:
    """Use LLM to compare agent answer against IRC discussion."""
    
    system_prompt = """You are comparing an AI reviewer's answer to a Bitcoin Core PR review club question \
against the actual IRC discussion from human reviewers. 

Your job is to:
1. Identify the KEY INSIGHTS raised in the IRC discussion (the important technical points)
2. Determine which of those insights the AI answer captured
3. Determine which insights the AI missed
4. Note any insights the AI raised that the humans did NOT discuss (novel contributions)
5. Rate the overall quality of the AI answer

Be specific - reference actual technical points by name. Don't just say "the AI covered some points" - \
say exactly which points it covered and which it missed."""

    user_prompt = f"""## Question
{question['text']}

## AI Reviewer's Answer
{agent_answer}

## IRC Discussion (Human Reviewers)
{irc_segment}

## Your Analysis

Please provide:

### Key Insights from IRC Discussion
(List the main technical points raised by human reviewers)

### Insights Captured by AI
(Which of the above points did the AI answer also cover?)

### Insights Missed by AI  
(Which of the above points did the AI answer NOT cover?)

### Novel Insights from AI
(What points did the AI raise that were NOT discussed in IRC?)

### Quality Rating
(Rate 1-5: 1=completely off, 2=major gaps, 3=decent coverage, 4=strong answer, 5=expert-level)

### Summary
(2-3 sentence overall assessment)"""

    result_text = call_llm(system_prompt, user_prompt)
    
    return {
        "question_number": question["number"],
        "question_text": question["text"],
        "comparison": result_text,
    }


def run_comparator(workshop_id: str) -> dict:
    """Run the full comparison for a workshop."""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Load workshop data
    data_path = os.path.join(DATA_DIR, f"{workshop_id}_structured.json")
    with open(data_path) as f:
        workshop = json.load(f)

    # Load agent results
    results_path = os.path.join(RESULTS_DIR, f"{workshop_id}_agent_results.json")
    with open(results_path) as f:
        agent_results = json.load(f)

    questions = workshop["questions"]
    answers = agent_results["answers"]
    log = workshop["log"]

    # Filter out bot messages for cleaner analysis
    log_substantive = [
        e for e in log 
        if e["nick"] not in ("corebot", "corebot`") 
        and not e["message"].startswith(("#startmeeting", "#endmeeting", "#here", "#topic"))
        and len(e["message"]) > 3
    ]

    print(f"\n{'='*60}")
    print(f"BCR Comparator — Workshop: {workshop['title']}")
    print(f"Questions: {len(questions)}")
    print(f"IRC entries (substantive): {len(log_substantive)}")
    print(f"{'='*60}\n")

    comparisons = []
    for i, question in enumerate(questions):
        if i >= len(answers):
            print(f"  Q{question['number']}: No agent answer available, skipping")
            continue

        print(f"Comparing Q{question['number']}: {question['text'][:80]}...")
        
        # Extract relevant IRC segment
        irc_segment = extract_irc_segment_for_question(
            log_substantive, question["text"], i, len(questions)
        )
        irc_text = format_irc_segment(irc_segment)
        
        # Limit IRC text length to avoid excessive prompts
        if len(irc_text) > 8000:
            irc_text = irc_text[:8000] + "\n... (truncated)"

        # Compare
        try:
            comparison = compare_answer_vs_irc(
                question=question,
                agent_answer=answers[i]["answer"],
                irc_segment=irc_text,
            )
            comparisons.append(comparison)
            print(f"  Done. Comparison length: {len(comparison['comparison'])} chars")
        except Exception as e:
            print(f"  Error: {e}")
            comparisons.append({
                "question_number": question["number"],
                "question_text": question["text"],
                "comparison": f"Error during comparison: {e}",
            })

        # Rate limit: wait between LLM calls
        time.sleep(2)

    # Save comparison results
    comparison_results = {
        "workshop_id": workshop_id,
        "workshop_title": workshop["title"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "comparisons": comparisons,
    }

    output_path = os.path.join(RESULTS_DIR, f"{workshop_id}_comparison.json")
    with open(output_path, "w") as f:
        json.dump(comparison_results, f, indent=2)

    print(f"\nComparison results saved to: {output_path}")

    # Print summary
    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}")
    for comp in comparisons:
        # Extract quality rating if present
        rating_line = ""
        for line in comp["comparison"].split("\n"):
            if "Quality Rating" in line or "rating" in line.lower():
                rating_line = line.strip()
                break
        print(f"\nQ{comp['question_number']}: {comp['question_text'][:80]}...")
        if rating_line:
            print(f"  {rating_line}")

    return comparison_results


if __name__ == "__main__":
    workshop_id = sys.argv[1] if len(sys.argv) > 1 else "32489"
    run_comparator(workshop_id)
