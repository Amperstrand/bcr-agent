#!/usr/bin/env python3
"""
BCR Mode Comparator - Compares blind vs augmented agent answers for the same workshop.

Shows:
- Where augmented mode picked up insights from the IRC discussion
- Where blind mode had unique insights 
- Overall quality difference between the two modes
"""

import json
import os
import re
import subprocess
import sys

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# Reuse config from agent.py
sys.path.insert(0, os.path.dirname(__file__))
from agent import get_llm_cli_path, load_config


def call_llm(system_prompt: str, user_prompt: str) -> str:
    config = load_config()
    llm_path = get_llm_cli_path()
    timeout = config["llm"].get("timeout_seconds", 300)

    output_path = os.path.join(RESULTS_DIR, "mode_compare_llm.json")
    cmd = [
        llm_path, "chat",
        "--prompt", user_prompt,
        "--system", system_prompt,
        "-o", output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"LLM call failed: {result.stderr}")
    with open(output_path) as f:
        response = json.load(f)
    return response["choices"][0]["message"]["content"]


def compare_modes(workshop_id: str) -> dict:
    """Compare blind vs augmented answers for each question."""
    
    blind_path = os.path.join(RESULTS_DIR, f"{workshop_id}_blind_results.json")
    aug_path = os.path.join(RESULTS_DIR, f"{workshop_id}_augmented_results.json")
    
    if not os.path.exists(blind_path):
        # Try old naming
        old_path = os.path.join(RESULTS_DIR, f"{workshop_id}_agent_results.json")
        if os.path.exists(old_path):
            blind_path = old_path
        else:
            print(f"No blind results found for {workshop_id}")
            return {}
    
    if not os.path.exists(aug_path):
        print(f"No augmented results found for {workshop_id}")
        return {}
    
    with open(blind_path) as f:
        blind = json.load(f)
    with open(aug_path) as f:
        aug = json.load(f)
    
    system_prompt = """You are comparing two AI-generated answers to the same Bitcoin Core PR review club question. \
One answer was generated in BLIND mode (only had the workshop notes and PR diff), \
and the other was generated in AUGMENTED mode (also had access to the IRC discussion and GitHub comments).

Your job is to determine:
1. What insights does the AUGMENTED answer have that the BLIND answer lacks? (from IRC/GitHub context)
2. What insights does the BLIND answer have that the AUGMENTED answer lacks? (independent analysis)
3. Which answer is overall better and why?
4. Rate each answer 1-5

Be specific about which insights come from the IRC discussion vs independent analysis."""

    comparisons = []
    
    for i in range(min(len(blind["answers"]), len(aug["answers"]))):
        blind_a = blind["answers"][i]
        aug_a = aug["answers"][i]
        
        print(f"\nComparing Q{blind_a['number']}: {blind_a['question'][:80]}...")
        
        user_prompt = f"""## Question
{blind_a['question']}

## BLIND Answer (workshop notes + PR diff only)
{blind_a['answer'][:3000]}

## AUGMENTED Answer (workshop notes + PR diff + IRC discussion + GitHub comments)
{aug_a['answer'][:3000]}

## Analysis

### Insights Only in AUGMENTED (from IRC/GitHub)
(What did the augmented answer pick up from the human discussion?)

### Insights Only in BLIND (independent analysis)  
(What did the blind answer have that the augmented answer dropped?)

### Overall Comparison
(Which is better and why?)

### Quality Ratings
BLIND: X/5
AUGMENTED: X/5"""

        try:
            comparison = call_llm(system_prompt, user_prompt)
            comparisons.append({
                "question_number": blind_a["number"],
                "question": blind_a["question"],
                "comparison": comparison,
            })
            print(f"  Done.")
        except Exception as e:
            print(f"  Error: {e}")
            comparisons.append({
                "question_number": blind_a["number"],
                "question": blind_a["question"],
                "comparison": f"Error: {e}",
            })
    
    # Save results
    result = {
        "workshop_id": workshop_id,
        "comparisons": comparisons,
    }
    
    output_path = os.path.join(RESULTS_DIR, f"{workshop_id}_mode_comparison.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\nMode comparison saved to: {output_path}")
    
    # Print summary
    print(f"\n{'='*60}")
    print("MODE COMPARISON SUMMARY")
    print(f"{'='*60}")
    for comp in comparisons:
        # Extract ratings
        blind_rating = "?"
        aug_rating = "?"
        for line in comp["comparison"].split("\n"):
            if "BLIND:" in line and "/5" in line:
                nums = re.findall(r'(\d)/5', line)
                if nums:
                    blind_rating = nums[0]
            if "AUGMENTED:" in line and "/5" in line:
                nums = re.findall(r'(\d)/5', line)
                if nums:
                    aug_rating = nums[0]
        print(f"  Q{comp['question_number']}: BLIND={blind_rating}/5  AUGMENTED={aug_rating}/5")
    
    return result


if __name__ == "__main__":
    workshop_id = sys.argv[1] if len(sys.argv) > 1 else "32489"
    compare_modes(workshop_id)
