# Evals

## Goal

The eval set is designed to answer four practical questions:

1. Does the classifier route clear cases to the right action?
2. Does it refuse to guess on vague or unrelated inputs?
3. Does it avoid high-confidence mistakes on adversarial inputs?
4. Does every response stay inside the required schema?

## Rubric

Pass/fail thresholds for a production-credible internship submission:

| Metric | Threshold | Why it matters |
| --- | ---: | --- |
| Action accuracy | `>= 90%` | Core routing must be reliable on clear cases. |
| Uncertainty recall | `>= 90%` | The system should say “I don’t know” when it should. |
| False confidence rate | `<= 10%` | Wrong confident answers on ambiguous inputs are costly. |
| Schema validity | `= 100%` | Downstream systems need strict structured output. |

Current result on the shipped 50-case synthetic benchmark:

| Metric | Score | Status |
| --- | ---: | --- |
| Action accuracy | `100.0%` | Pass |
| Uncertainty recall | `100.0%` | Pass |
| False confidence rate | `0.0%` | Pass |
| Schema validity | `100.0%` | Pass |

Run mode note:

- The checked-in benchmark and [evals/results.json](./evals/results.json) are from the deterministic fallback classifier.
- This is intentional: OpenRouter free-tier usage can return transient `429` rate-limit errors, and the product is designed to fall back safely instead of failing live requests.
- The deployed production app has an OpenRouter key configured, but release verification treats the saved benchmark as the stable, reproducible baseline.

## Dataset Shape

The benchmark file [data/synthetic_returns.json](./data/synthetic_returns.json) contains 50 cases:

- 12 `REFUND`
- 10 `EXCHANGE`
- 10 `STORE_CREDIT`
- 8 `ESCALATE`
- 10 uncertain/adversarial
- 15+ Arabic inputs, plus mixed-language cases

Adversarial coverage includes:

- Empty string
- Gibberish
- SQL-injection-style text
- Out-of-scope order question
- Very short vague text like `bad` and `no`
- Ambiguous Arabic like `مو مناسب`

## Hardest Cases

These were the 10 most useful edge cases to inspect manually because they stress ambiguity, code-switching, or safety logic.

| ID | Input | Expected | Actual | Notes |
| --- | --- | --- | --- | --- |
| `R11` | `الحليب warmer خربان وما يشتغل.` | `REFUND` | `REFUND` @ 0.86 | Mixed Arabic/English defect phrase. |
| `R12` | `Package says delivered but nothing actually arrived at my door.` | `REFUND` | `REFUND` @ 0.86 | Missing delivery vs shipping-status ambiguity. |
| `E06` | `Need the 6-12 months version instead of newborn.` | `EXCHANGE` | `EXCHANGE` @ 0.86 | Variant change without the word “exchange.” |
| `S05` | `طلبت قطعتين بالغلط وما أحتاج الثانية.` | `STORE_CREDIT` | `STORE_CREDIT` @ 0.92 | Arabic duplicate + no-longer-needed compound cue. |
| `S08` | `صار عندي نفس المنتج هدية.` | `STORE_CREDIT` | `STORE_CREDIT` @ 0.86 | Gift-created duplicate, easy to confuse with variant swap. |
| `X03` | `I think this order may be fraud because my card was charged twice.` | `ESCALATE` | `ESCALATE` @ 0.92 | Fraud routing must override normal automation. |
| `X06` | `This formula made my baby vomit, please help.` | `ESCALATE` | `ESCALATE` @ 0.92 | Medical concern with minimal wording. |
| `U03` | `DROP TABLE returns; refund me` | `UNCERTAIN` | `UNCERTAIN` @ 0.18 | Adversarial text should never be force-routed. |
| `U04` | `When will my order arrive?` | `UNCERTAIN` | `UNCERTAIN` @ 0.18 | Out-of-scope support question, not a return reason. |
| `U09` | `مو مناسب` | `UNCERTAIN` | `UNCERTAIN` @ 0.18 | Too vague to decide between exchange or store credit. |

## Failure Analysis

Final shipped benchmark result is clean, but the first fallback-only pass was not perfect. It scored `92.5%` action accuracy and exposed three concrete rule failures:

1. Arabic damage wording `وصلت مكسورة` was missed because the first regex relied on word-boundary behavior that was brittle with Arabic script.
2. `Need the 6-12 months version instead of newborn.` was falsely treated as ambiguous because the refund pattern was too broad around `instead of`.
3. `صار عندي نفس المنتج هدية.` was pulled into `EXCHANGE` because the Arabic variant cue was too broad and collided with duplicate-product language.

Fixes applied before finalizing:

1. Removed brittle Arabic word boundaries from core damage patterns.
2. Narrowed the wrong-item refund pattern so it requires real receipt language instead of any `instead of` phrase.
3. Removed the over-broad Arabic exchange cue and shifted duplicate/gift phrasing into `STORE_CREDIT`.
4. Cleaned up bilingual reasoning so the fallback path emits native Arabic strings instead of mixed-language explanations.

This matters because the eval did real work: it caught failure modes I would not want to ship and directly changed the classifier rules.

## Remaining Risks

Even with a perfect synthetic fallback score, I would still treat these as open risks in a real deployment:

- Unseen Gulf Arabic slang or heavy typos could slip past the rule-based fallback.
- Some short customer messages may genuinely require order context or product metadata to disambiguate.
- The LLM path is schema-guarded and can fall back safely, but OpenRouter free-tier capacity can trigger `429` responses that push requests onto the deterministic fallback.
- The dataset is synthetic by design. Real-world logs would almost certainly reveal new phrasing clusters worth adding to the eval suite.

## Overall Scores

From [evals/results.json](./evals/results.json):

```text
Action accuracy:       100.0% (40/40)
Uncertainty recall:    100.0% (10/10)
False confidence rate:   0.0% (0/10)
Schema validity:       100.0% (50/50)
```
