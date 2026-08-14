# Agent Evaluation Baseline

## Purpose

Market Pilot separates deterministic business calculation from Agent decision quality. Unit tests verify individual functions and API contracts; the offline evaluation suite measures whether the Agent selects appropriate tools, cites valid evidence, states required facts, and refuses unsupported conclusions.

The suite is deterministic and does not require an external LLM or map API. Scripted model responses exercise the real operating orchestrator and report follow-up Agent against synthetic business fixtures.

## Running The Evaluation

From the project root:

```powershell
cd backend
python -m scripts.run_agent_evals
```

The command writes:

- `outputs/evals/agent-eval-baseline.json`: machine-readable case and aggregate results.
- `outputs/evals/agent-eval-baseline.md`: concise summary and focused planning mismatches.

Generated reports are intentionally ignored by Git because they can be reproduced from the committed cases and fixtures.

## Dataset

The baseline contains 30 cases:

- 15 operating-plan cases covering revenue, menu matrix, reviews, time patterns, discounts, survival line, and channel profitability.
- 15 report follow-up cases covering metric reads, missing data, old report shapes, merchant targets, absent benchmarks, invalid evidence, and prompt-like text embedded in review data.

Golden cases assert structured facts and evidence paths instead of exact prose. This allows wording changes without weakening factual checks.

## Baseline Results

Recorded on 2026-08-13 from commit `0e4a7a3` plus the Phase 1 reporting changes:

| Metric | Result |
| --- | ---: |
| Cases | 30 |
| Tool precision | 0.7000 |
| Tool recall | 1.0000 |
| Tool exact-set accuracy | 0.6333 |
| Evidence validity | 1.0000 |
| Required fact coverage | 1.0000 |
| Correct abstention rate | 1.0000 |
| Benchmark disclaimer accuracy | 1.0000 |
| Unsupported numeric claims | 0 |
| Unsupported normative claims | 0 |
| Safety pass rate | 1.0000 |
| Overall pass rate | 0.6333 |

The primary weakness was deliberate and measurable: a focused operating question executed all seven operating tools. Single-tool questions therefore scored `0.1429` tool precision even though recall was perfect.

## Phase 3 Result

Recorded on 2026-08-14 after introducing explicit `full` and `focused` modes, policy-bounded tool selection, and one bounded replan opportunity:

| Metric | Phase 1 | Phase 3 |
| --- | ---: | ---: |
| Tool precision | 0.7000 | 1.0000 |
| Tool recall | 1.0000 | 1.0000 |
| Tool exact-set accuracy | 0.6333 | 1.0000 |
| Evidence validity | 1.0000 | 1.0000 |
| Required fact coverage | 1.0000 | 1.0000 |
| Safety pass rate | 1.0000 | 1.0000 |
| Overall pass rate | 0.6333 | 1.0000 |

`full` mode still runs all available core tools. `focused` mode accepts one to four policy-validated tools, and the deterministic fallback routes known question types without requiring an LLM. A recoverable required-tool failure can trigger one revised plan; the trace records both plans, the trigger, and the final outcome.

The enforced focused-mode regression thresholds are `0.90` precision, `0.95` recall, and `0.80` exact-set accuracy. Evidence validity and safety pass rate must remain `1.00`.

## Safety Gate

The command exits unsuccessfully when any hard invariant fails:

- an answer cites evidence that does not exist;
- an answer introduces an unsupported numerical claim;
- an answer makes an unsupported normative comparison;
- a case requiring abstention does not state that data is insufficient.

Planning mismatches remain visible in the report but do not fail the safety gate during the baseline phase. This prevents an expected planning limitation from hiding regressions in factual safety.

## Scope And Limitations

- Scripted responses measure orchestration and validation deterministically; they do not estimate live-model variability, latency, or cost.
- The current dataset is synthetic and small enough for fast pull-request checks. It is not a statistically representative benchmark of restaurant operations.
- Provider smoke tests and production traces belong to the later LLM operations phase and must remain separate from the offline safety gate.
