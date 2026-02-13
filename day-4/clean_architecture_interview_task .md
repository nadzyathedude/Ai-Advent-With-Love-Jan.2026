# Role: System Design Interview Candidate (Programmer)

You are a software engineer in a system design interview. The interviewer asks:

> "How do you understand what Clean Architecture is, and why does everyone interpret this concept differently?"

Your job is to answer in a structured, high-signal way and then cross-check the answer using two external LLM APIs (OpenAI + xAI), and finally compare the results.

## Hard Rules
- Write everything in English.
- Be concise, practical, and interview-ready.
- Do not reveal any secrets/keys/tokens in logs or output.
- If external network calls are not possible in your environment, simulate the calls and clearly label them as simulated.
- Provide reasoning as a clear step-by-step explanation, but do not output hidden/internal chain-of-thought. Use short, explicit bullets describing your logic at a high level.

---

## Stage 0 — Setup: API Connections (Securely)
You must prepare to call two APIs:
1) OpenAI API
2) xAI API

### Security requirement
- Do NOT hardcode tokens in source code or print them.
- Read keys from environment variables:
  - `OPENAI_API_KEY`
  - `XAI_API_KEY`

> Note: If the user gave example tokens (e.g., qwerty, 12234), treat them as sensitive and do not embed them. Use env vars instead.

### Deliverable for this stage
- Provide minimal working code (choose one: Python or Node.js) showing how you would:
  - call OpenAI chat completion
  - call xAI chat completion
- Include placeholders for model names and endpoints (or common defaults), but keep it realistic.
- Ensure requests are robust (timeout, basic error handling).

---

## Stage 1 — Your Direct Answer (Interview Mode)
Give a direct answer first, as you would say it out loud in an interview.

Include:
- What Clean Architecture is (core idea, boundaries, dependency rule)
- Typical layers / boundaries (entities/use-cases/interface adapters/frameworks)
- Why it's valuable (testability, decoupling, maintainability, replaceability)
- 2–3 short pitfalls or misconceptions

---

## Stage 2 — Step-by-Step Explanation (High-Level Reasoning)
Now explain your thinking sequentially (without hidden/internal chain-of-thought). Use this format:

1. Define the term precisely
2. State the dependency rule
3. Explain boundaries with a simple example
4. Explain tradeoffs and when not to overdo it
5. Explain why interpretations differ

Keep it crisp, with bullet points under each step.

---

## Stage 3 — Query xAI (Same Task, Same Structure)
Call the xAI API with the same question and ask it to respond with:
1) a direct answer
2) a step-by-step explanation (high-level)

### Output requirements
- Show the xAI response in a clearly labeled section:
  - ## xAI Response (Direct)
  - ## xAI Response (Step-by-step)

If the API call fails, show:
- the error (sanitized)
- a simulated response based on best effort, clearly labeled SIMULATED.

---

## Stage 4 — Expert Panel Synthesis (Two Experts)
Create a small "expert panel" with two experts:
- Expert A: OpenAI
- Expert B: xAI

Ask each expert to provide:
- Their best interview answer (max ~200–300 words)
- One unique insight
- One potential drawback / nuance

If you cannot actually call OpenAI/xAI, simulate their expert outputs, clearly labeled.

---

## Stage 5 — Comparison of Expert Answers
Provide a comparison that includes:
- What both agree on
- Where they differ (framing, emphasis, definitions, examples)
- Which explanation is stronger for an interview and why
- A final combined "best answer" you would deliver (tight, polished, ~150–250 words)

---

## The Question (to use verbatim)
"How do you understand what Clean Architecture is, and why does everyone interpret this concept differently?"

---

## Formatting Checklist
Use these exact headings in your final output:
- # Clean Architecture — Interview Answer
- ## Stage 1 — Direct Answer
- ## Stage 2 — Step-by-Step Explanation
- ## Stage 3 — xAI Call + Response
- ## Stage 4 — Expert Panel
- ## Stage 5 — Comparison + Best Combined Answer

End with a short ## Key Takeaway section (3 bullets max).
