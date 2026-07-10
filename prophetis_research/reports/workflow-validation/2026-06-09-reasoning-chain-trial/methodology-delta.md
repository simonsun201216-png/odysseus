# Methodology Delta ‚Ä?reasoning-chain ablation trial (NEGATIVE RESULT)

- trial_date: 2026-06-09
- method_under_test: 3 reasoning interventions ‚Ä?‚ë?adversarial pass (interaction-kernel), ‚ë?variant-perception Application Chain, ‚ë?quant-trap checklist (data-analysis-quality-gate)
- design: pre-registered multi-arm blind ablation; 38 test-blind generations + 38 blind grades; sanitized `case_a` (pton), `case_b` (tdoc), `case_c` (aapl reverse control)
- runs: 38/38 scored
- **decision: REVERT all three. Do not merge.** Real cards were never modified (treatments live only as trial artifacts).

## Result vs the pre-registered win rule

Win rule (locked before any run): `no_regression` (treatment median ‚â?control on every dim, pooled `case_a`+`case_b`) **AND** `‚â? key dim improves ‚â? median` **AND** `case_c` no erroneous downgrade **AND** BASELINE 12/12 **AND** field-delta ‚â?0.

| arm (intervention) | key deltas (consensus / falsif / timing) | no_regression | key_gain ‚â? | verdict |
| --- | --- | --- | --- | --- |
| arm1 ‚ë?adversarial | +0.5 / 0 / 0  (valuation ‚à?.5) | ‚ù?| ‚ù?| revert |
| arm2 ‚ë?reasoning chain | **‚à?.5** / 0 / 0 | ‚ù?| ‚ù?| revert |
| arm3 ‚ë?quant traps | 0 / 0 / 0  (valuation +0.5) | ‚ú?| ‚ù?| revert (no gain) |
| arm4 all three | **‚à?.5** / 0 / 0  (valuation +0.5) | ‚ù?| ‚ù?| revert |

`case_c` reverse control: **no erroneous downgrade in any arm** (all `watch_only`, no shock/broken framing). Clean ‚Ä?but it also means the reverse control did not discriminate, because control already passes it.

**No arm passes. All three revert.**

## Why ‚Ä?ceiling effect (the honest limitation)

Control (arm0) pooled `case_a`+`case_b` key dims = consensus **4.5**, falsification **5**, downgrade_timing **5**. Opus 4.8 + the *current* Prophetis protocol already reasons at near-ceiling on these cases, so a treatment has no room to show a +1 gain.

This is not a lazy grader: the grader *did* discriminate (it scored `case_c` consensus at 3‚Ä?.5, not a blanket 5). The ceiling is real.

Contributing confound ‚Ä?**identity leakage**: these are famous, recognizable cases. The model likely already "knows the move." The ablation cancels this in the *delta* (it is constant across arms), but it inflates the *absolute* control scores and removes headroom. The residual-identity risk flagged in `blind-packet-build-log.md` is part of why the test cannot discriminate.

## The one real signal: the keystone slightly REGRESSED

‚ë?(the variant-perception Application Chain) was the intervention I had the most conviction in. It scored consensus **‚à?.5** pooled `a`+`b`, and was ‚â?control on `case_c` consensus too. Weak (inside n=2‚Ä? noise) but **directionally consistent across cases**: the rigid 5-step chain sometimes produced a *less* complete consensus articulation than the model's free-form reasoning. This is exactly the **over-proceduralization risk** pre-registered in the plan ("Ê≠ªÊ≠•È™§ÂèØËÉΩËÆ©Ê®°ÂûãÊõ¥Êú∫Ê¢?) ‚Ä?the opposite of the hoped-for effect.

## What this proves / does not prove

- **Proves (this regime):** where the base protocol + a strong model already reason well, these three interventions add no measurable reasoning gain, and the keystone slightly hurts. Merging would be pure complexity for zero gain ‚Ä?a ÂáÄÂáèË¥ü violation.
- **Does NOT prove** the reasoning layer is worthless in general. The test is **underpowered** by the ceiling + identity leakage. It says nothing about hard cases where Opus 4.8 genuinely under-reasons (novel/obscure objects, ambiguous consensus, no name recognition).

## Implication / next blocker

- Revert; leave the three real cards untouched.
- BASELINE re-run **skipped on purpose**: nothing was merged, so the real cards are unchanged and 12/12 is trivially preserved. Re-running would only re-confirm an unchanged state.
- The diagnosis ("Prophetis is reasoning-light") is **not refuted**, but its **value is unproven**. The real blocker is **case design**: we need research objects where current-Prophetis + Opus 4.8 *measurably under-reasons* and where identity cannot leak the answer. Until such a discriminating set exists, there is no evidence to justify adding the reasoning layer, and ÂáÄÂáèË¥ü says do not add it.

## What worked (process)

Pre-registration + blind grading + reverse control + ablation did their job: they stopped three plausible-sounding interventions from shipping as a fake "improvement," and surfaced that the keystone may *hurt*. The rigor is the deliverable here, not a positive result.

## Deeper conclusion: a MODEL-layer capability, not a harness-layer one

The clean read of this negative result (Sky, 2026-06-09): reasoning depth ‚Ä?adversarial self-check, applying a method as a reasoning chain, quantitative care ‚Ä?is a **model-layer** capability, not a **harness-layer** one. A strong model already does it, and it keeps improving **for free** with each model upgrade. So encoding it into the Prophetis protocol is redundant now and brittle later: a rigid recipe constrains a model that already reasons better than the recipe ‚Ä?which is exactly why keystone ‚ë?regressed.

Design line: keep Prophetis to what is genuinely harness-layer ‚Ä?governance, routing, evidence discipline, portability, refresh/state ‚Ä?and let reasoning depth ride the model curve. Do not re-litigate this on each model release; **the upgrade is the optimization.**
