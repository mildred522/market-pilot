# Model Routing Benchmark

## Decision

Use `deepseek-v4-flash` as the default model for Planner, Synthesizer, Followup,
and Replanner. Do not put `deepseek-v4-pro` on the default synchronous path.

`deepseek-v4-pro` may be introduced later as an explicit deep-report mode. That
mode should be user-selected, asynchronous, and evaluated separately from the
interactive latency target.

## Available Models

The configured DeepSeek-compatible `/models` endpoint returned these model IDs
on 2026-08-21:

- `deepseek-v4-flash`
- `deepseek-v4-pro`

The application must use provider-returned IDs rather than assuming legacy model
names remain available.

## Followup Comparison

Both runs used analysis `223` and the question "根据当前报告推荐一些适合继续主推或测试的菜品方向".

| Metric | v4-flash | v4-pro |
| --- | ---: | ---: |
| Result quality | complete | repaired |
| Agent steps | 1 | 2 |
| Input tokens | 7,903 | 16,512 |
| Output tokens | 2,771 | 6,201 |
| Total tokens | 10,674 | 22,713 |
| Model duration | 27.6 s | 118.6 s |
| Valid claims | 5 | 5 |

Flash produced the complete grounded answer in one step. Pro required a repair
round, used 2.1 times the tokens, and took 4.3 times as long.

## Synthesizer Comparison

The benchmark executed the same seven deterministic operating tools once, then
passed identical metrics and a fixed plan to each model.

| Metric | v4-flash | v4-pro |
| --- | ---: | ---: |
| Structured synthesis | pass | pass |
| Evidence findings | 4 | 4 |
| Actions | 4 | 4 |
| Input tokens | 4,161 | 4,161 |
| Output tokens | 6,361 | 9,415 |
| Total tokens | 10,522 | 13,576 |
| Model duration | 53.5 s | 153.5 s |

Pro included a broader review-topic observation, but both outputs were grounded
and actionable. The modest coverage gain does not justify 2.9 times the latency
on the default report path.

## Reproduction

Followup comparison:

```powershell
cd backend
python -m scripts.evaluate_followup_rag `
  --analysis-id 223 `
  --client live `
  --model deepseek-v4-flash `
  --question "根据当前报告推荐一些适合继续主推或测试的菜品方向"
```

Fixed-input Synthesizer comparison:

```powershell
python -m scripts.benchmark_synthesizer_models `
  --models deepseek-v4-flash deepseek-v4-pro `
  --output ../outputs/evals/synthesizer-model-comparison.json
```

Live results are provider-dependent and should not be part of normal CI. Offline
schema, evidence, and policy tests remain the merge gate.
