# Tradeoffs

## Why Return Classification

I chose return classification because it has high operational leverage for an e-commerce business and a clean evaluation surface for a narrowly scoped support workflow.

Why this problem works well:

- High business value: fast, consistent routing reduces support load and speeds up customer handling.
- Clear decision rules: the four actions are easy to define and test.
- Tight scope: enough room to show LLM design, fallback behavior, eval rigor, and bilingual UX without drifting into platform work.
- Good uncertainty story: vague, adversarial, and out-of-scope messages are common in support flows, so “don’t guess” is a meaningful product requirement.

## What I Rejected

Ideas I did not choose:

- Full return-policy agent: more realistic end-to-end, but it expands into policy retrieval, order state, and workflow orchestration too quickly.
- Translation-first pipeline: simpler on paper, but it introduces another failure surface and hides whether Arabic reasoning is genuinely grounded.
- Embedding or semantic-search router: overkill for four labels and weaker than a well-tested prompt + fallback setup for this scope.
- Pure rules only: excellent for fallback, but weaker for nuanced bilingual paraphrases than an LLM-backed primary path.

## Why Llama 3.3 70B

I used `meta-llama/llama-3.3-70b-instruct:free` on OpenRouter because it hits a useful balance for this system:

- Strong enough for structured bilingual classification and concise explanation writing.
- Accessible through a simple API call, which keeps the project runnable.
- Cheap and low-friction for reviewers to try with their own key.
- Good fit for prompt-based routing without adding finetuning overhead.

I still treated the LLM as untrusted output:

- JSON is parsed explicitly.
- Output is validated with Pydantic.
- Validation failures convert into `is_uncertain=true` with `action=null`.
- If no API key exists, or the API call fails, the app drops to deterministic rules and still runs.

## LLM vs Translation API for Arabic

I chose a bilingual classification path instead of “translate Arabic to English, classify in English, translate back.”

Reasons:

- Fewer moving parts: one model interface instead of a translation hop plus a classification hop.
- Better nuance retention: customer return reasons are often short, informal, and context-light, so translation can erase useful phrasing.
- Cleaner uncertainty: if the original Arabic is vague, I want the system to preserve that ambiguity instead of smoothing it into false confidence.
- Better UX: the prompt explicitly asks for natural GCC Arabic, and the fallback path uses native Arabic strings directly.

The tradeoff is that prompt quality matters more. I compensated with:

- Clear routing boundaries in the system prompt.
- Few-shot Arabic and English examples for every class.
- A deterministic fallback that encodes the same policy.

## What Was Cut

I intentionally did not build:

- Fine-tuning
- Streaming responses
- Database persistence
- Reviewer dashboard for historical classifications
- Human-in-the-loop queues or escalation inboxes
- Policy engine integration with actual order metadata

Why:

- None of those were necessary to prove core routing quality.
- They would have spread time away from the core system goals: correctness, eval rigor, uncertainty handling, and production readiness.

## What I’d Build Next

If this moved beyond the current prototype, I would add:

1. Real data evals from anonymized support logs, including confusion slices by category and language.
2. A label-audit workflow so uncertain cases and escalations can become new eval seeds.
3. Lightweight analytics: action distribution, uncertainty rate, and fallback-vs-LLM usage.
4. A prompt-version registry so output changes are traceable across eval runs.
5. Optional policy-aware reply generation once live return rules are available.
6. A small moderation layer for abusive or clearly malicious text beyond the current uncertain handling.

## Bottom Line

The main tradeoff was choosing reliability over breadth:

- One sharp workflow
- Strict schema enforcement
- Honest uncertainty
- Bilingual coverage
- Deterministic no-key fallback
- Measurable evals that actually changed the implementation

That felt like the strongest way to maximize reliability and trustworthiness instead of shipping a larger but less dependable demo.
