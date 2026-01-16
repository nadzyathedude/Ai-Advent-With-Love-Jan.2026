#!/usr/bin/env python3
"""
Execute Clean Architecture interview question against OpenAI and xAI APIs.
"""

import json
from api_client import call_openai, call_xai

QUESTION = """How do you understand what Clean Architecture is, and why does everyone interpret this concept differently?

Please provide:
1) A direct interview answer (concise, practical)
2) A step-by-step explanation covering:
   - Define the term precisely
   - State the dependency rule
   - Explain boundaries with a simple example
   - Explain tradeoffs and when not to overdo it
   - Explain why interpretations differ

Format with clear headers for "Direct Answer" and "Step-by-Step Explanation"."""

EXPERT_PROMPT = """You are a senior software architect in an interview panel.

Question: "How do you understand what Clean Architecture is, and why does everyone interpret this concept differently?"

Provide:
1. Your best interview answer (max 200-300 words)
2. One unique insight others might miss
3. One potential drawback or nuance to be aware of

Be concise and interview-ready."""


def main():
    results = {}

    # Call xAI
    print("Calling xAI API...")
    xai_result = call_xai(QUESTION)
    results["xai"] = xai_result

    if xai_result["success"]:
        print("xAI call succeeded")
    else:
        print(f"xAI call failed: {xai_result['error']}")

    # Call OpenAI
    print("\nCalling OpenAI API...")
    openai_result = call_openai(EXPERT_PROMPT)
    results["openai"] = openai_result

    if openai_result["success"]:
        print("OpenAI call succeeded")
    else:
        print(f"OpenAI call failed: {openai_result['error']}")

    # Call xAI for expert panel as well
    print("\nCalling xAI API for expert panel...")
    xai_expert_result = call_xai(EXPERT_PROMPT)
    results["xai_expert"] = xai_expert_result

    if xai_expert_result["success"]:
        print("xAI expert call succeeded")
    else:
        print(f"xAI expert call failed: {xai_expert_result['error']}")

    # Output results
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)

    print("\n### xAI Response ###")
    if results["xai"]["success"]:
        print(results["xai"]["content"])
    else:
        print(f"ERROR: {results['xai']['error']}")

    print("\n### OpenAI Expert Response ###")
    if results["openai"]["success"]:
        print(results["openai"]["content"])
    else:
        print(f"ERROR: {results['openai']['error']}")

    print("\n### xAI Expert Response ###")
    if results["xai_expert"]["success"]:
        print(results["xai_expert"]["content"])
    else:
        print(f"ERROR: {results['xai_expert']['error']}")

    # Save to file for reference
    with open("api_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults saved to api_results.json")


if __name__ == "__main__":
    main()
