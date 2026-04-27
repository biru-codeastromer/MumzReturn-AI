# MumzReturn AI

Track: A — AI Engineering Intern

Live app: [https://mumzreturn-ai.vercel.app](https://mumzreturn-ai.vercel.app)

GitHub repo: [https://github.com/biru-codeastromer/MumzReturn-AI](https://github.com/biru-codeastromer/MumzReturn-AI)

MumzReturn AI is a bilingual return-reason classifier for Mumzworld that takes a customer’s free-text message in English, Arabic, or mixed language and routes it into `REFUND`, `EXCHANGE`, `STORE_CREDIT`, `ESCALATE`, or `uncertain`. It returns a strict structured schema with confidence, grounded reasoning in both languages, a customer-ready reply in both languages, and safe uncertainty behavior when the text is vague, unrelated, or adversarial.

This prototype targets a real Mumzworld support-operations workflow: fast, safe routing of return requests across English and Arabic customer messages. It uses a strict Pydantic schema, bilingual reasoning and replies, a live OpenRouter-backed LLM path, a deterministic fallback when the API key is missing or rate-limited, and an explicit uncertainty path for vague, unrelated, or adversarial inputs so the system does not guess.

## Setup and Local Run

Under 5 minutes on a clean machine:

```bash
git clone https://github.com/biru-codeastromer/MumzReturn-AI.git
cd MumzReturn-AI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# add OPENROUTER_API_KEY if you want the LLM path; omit it to use fallback mode
uvicorn src.app:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Deployed app:

- Vercel production URL: [https://mumzreturn-ai.vercel.app](https://mumzreturn-ai.vercel.app)

Quick commands:

```bash
python -m src.evaluator
curl -X POST http://127.0.0.1:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"text":"المقاس صغير وأبغى مقاس أكبر.","language":"auto"}'
```

## Run Evals

```bash
python -m src.evaluator
cat evals/results.json
```

The checked-in benchmark artifact is the deterministic fallback benchmark so scores stay reproducible even when OpenRouter free-tier capacity varies.

## Loom Walkthrough Flow

Use these 5 inputs in the 3-minute walkthrough:

1. `The stroller wheel arrived broken and the frame is bent.` → `REFUND`
2. `المقاس صغير وأبغى مقاس أكبر.` → `EXCHANGE`
3. `I accidentally bought two of the same bottle warmer.` → `STORE_CREDIT`
4. `My baby got a rash after using this lotion.` → `ESCALATE`
5. `When will my order arrive?` → `action=null`, `is_uncertain=true`

## What It Does

The service classifies return reasons into one of four operational actions. Damage, wrong item, and non-delivery route to `REFUND`; size, color, or variant changes route to `EXCHANGE`; change-of-mind and duplicate orders route to `STORE_CREDIT`; and any safety, medical, injury, or fraud concern routes to `ESCALATE`. If the message is empty, vague, unrelated, or adversarial, the system refuses to guess and returns `is_uncertain=true` with `action=null`.

## Architecture

```text
Customer text
    |
    v
FastAPI /classify
    |
    v
System prompt loader + language hint
    |
    +--> OpenRouter (meta-llama/llama-3.3-70b-instruct:free)
    |        |
    |        v
    |   JSON parse
    |
    +--> Deterministic fallback rules (when no API key or LLM call fails)
             |
             v
      Pydantic validation
             |
             v
   Structured bilingual response
```

Implementation notes:

- `src/classifier.py` handles both the OpenRouter path and the deterministic fallback.
- `prompts/system_prompt.txt` defines the routing rules, few-shot examples, and uncertainty behavior.
- `src/schema.py` is the single source of truth for output validation.
- `src/evaluator.py` runs the 50-case synthetic benchmark and writes [evals/results.json](./evals/results.json).
- `ui/index.html` is a single-file UI with no build step.

## Evals

Saved summary from `python -m src.evaluator` in fallback mode:

| Metric | Score |
| --- | ---: |
| Action accuracy | 100.0% |
| Uncertainty recall | 100.0% |
| False confidence rate | 0.0% |
| Schema validity | 100.0% |

Artifacts:

- Full report: [EVALS.md](./EVALS.md)
- Raw outputs: [evals/results.json](./evals/results.json)
- Dataset: [data/synthetic_returns.json](./data/synthetic_returns.json)

Note on live mode:

- The deployed site currently has `OPENROUTER_API_KEY` configured and `/health` reports `fallback_mode: false`.
- OpenRouter free-tier requests can still return `429` rate-limit responses during peak usage; when that happens the app transparently falls back to the deterministic classifier instead of failing the request.
- The saved benchmark artifact remains the deterministic fallback run so the reported scores are stable and reproducible.

## Tradeoffs

Short version:

- I chose return classification because it has immediate business value, crisp routing rules, and measurable uncertainty requirements.
- I used `meta-llama/llama-3.3-70b-instruct:free` for the LLM path because it is capable enough for bilingual structured classification while remaining easy to run for a take-home.
- I kept the system fully runnable without an API key by shipping a deterministic fallback first, then proving it on evals.
- I cut fine-tuning, persistence, streaming, and policy-aware workflow integration to stay focused on a reliable demoable core.

Full discussion: [TRADEOFFS.md](./TRADEOFFS.md)

## API

### `POST /classify`

Request:

```json
{
  "text": "The stroller wheel arrived broken.",
  "language": "auto"
}
```

Response shape:

```json
{
  "action": "REFUND",
  "confidence": 0.94,
  "reasoning_en": "...",
  "reasoning_ar": "...",
  "suggested_reply_en": "...",
  "suggested_reply_ar": "...",
  "is_uncertain": false,
  "uncertainty_reason": null
}
```

Behavior:

- Returns HTTP `422` if `text` is empty.
- Returns HTTP `422` if `text` exceeds 500 characters.
- Returns HTTP `422` instead of `500` for request/body validation failures.
- Uses fallback mode automatically when `OPENROUTER_API_KEY` is missing.

### `GET /health`

Returns:

```json
{
  "status": "ok",
  "model": "llama-3.3-70b-instruct",
  "fallback_mode": false
}
```

## UI

The UI is intentionally styled like a premium research/evaluation product rather than a developer console: warm off-white palette, serif-led editorial hierarchy, rounded black CTAs, soft bordered cards, and a two-column analysis workspace. Arabic reasoning and reply blocks render in RTL, and uncertain outputs surface a yellow warning banner instead of pretending confidence.

## Tooling

Honest usage:

- AI coding assistance was used to draft and refine the project code, shape the fallback heuristics, and iterate on the UI.
- The evaluation loop was tool-assisted: I ran the benchmark, inspected concrete failures, and then tightened the exact rules that failed instead of claiming success from the first pass.
- The visual direction for the UI was not generated from scratch; I used the supplied AfterQuery screenshots as explicit design references and implemented the interface directly to preserve that look and density.
- No external translation API was added. Arabic support comes from the bilingual prompt plus native Arabic strings in the fallback path.

## AI Usage Note

- OpenRouter with `meta-llama/llama-3.3-70b-instruct:free` is the intended primary model path for structured bilingual classification.
- Codex was used as the coding harness for implementation, prompt iteration, eval design, UI refinement, deployment wiring, and README polish.
- The fallback classifier, eval suite, and output schema were iterated through agent-assisted coding plus manual failure review.
- Browser automation was used to verify the UI on desktop and mobile after implementation changes.
- I overruled early rule-matching behavior where evals exposed ambiguity bugs, then tightened the rules before finalizing.

## Tooling Transparency

- Harness: Codex was used for code implementation, refactors, live deployment verification, and release auditing.
- Model path: OpenRouter + `meta-llama/llama-3.3-70b-instruct:free` for live structured classification, with deterministic rules as the no-key / rate-limit fallback.
- Workflow: prompt iteration, schema-first implementation, eval-driven debugging, browser-based UI verification, and final deployment checks.
- Human override points: I explicitly adjusted the fallback safety heuristics, uncertainty logic, and README positioning after concrete failures and release-audit findings.

## Time Log

- `0.5h`: scoped the problem, designed the output contract, and set the project structure
- `1.5h`: built the classifier, fallback logic, prompt, dataset, and FastAPI endpoints
- `1.0h`: built the evaluator, ran failure analysis, and tightened edge-case handling
- `1.25h`: designed and refined the UI for bilingual demoability and browser verification
- `0.75h`: docs, packaging, GitHub prep, and deployment setup

## File Map

```text
mumzworld-return-classifier/
├── README.md
├── EVALS.md
├── TRADEOFFS.md
├── requirements.txt
├── .env.example
├── data/
│   └── synthetic_returns.json
├── src/
│   ├── __init__.py
│   ├── app.py
│   ├── classifier.py
│   ├── evaluator.py
│   └── schema.py
├── prompts/
│   └── system_prompt.txt
├── evals/
│   └── results.json
└── ui/
    └── index.html
```
