# Agent 面试评估证据

记录日期：2026-08-14
验证提交基线：`8a0fbd1` 之后的 Phase 7 工作树

## 离线质量

| 决策指标 | Phase 1 | 当前 | 发布判断 |
| --- | ---: | ---: | --- |
| 案例数 | 30 | 30 | 经营规划与追问各 15 例 |
| Tool precision | 0.7000 | 1.0000 | focused 不再执行全部工具 |
| Tool recall | 1.0000 | 1.0000 | 必需工具未丢失 |
| Tool exact-set | 0.6333 | 1.0000 | 规划集合全部匹配 golden case |
| Evidence validity | 1.0000 | 1.0000 | 引用均能解析到现有证据 |
| Unsupported numeric claims | 0 | 0 | 通过硬门禁 |
| Unsupported normative claims | 0 | 0 | 无基准时不做高低判断 |
| Safety pass rate | 1.0000 | 1.0000 | 30/30 通过 |

## 降级分布

| 结果路径 | 案例数 | 含义 |
| --- | ---: | --- |
| 正常规划/回答 | 28 | 使用预期工具和证据完成 |
| 数据不足 | 1 | 缺少渠道指标时明确拒答 |
| Grounded fallback | 1 | 模型重复读取同一指标时停止空转并使用已有证据 |

## 延迟、Token 与成本

离线套件使用脚本化模型，不伪造 token 或供应商延迟，因此这些值标记为 N/A。生产运行追踪
会记录实际 token、耗时、重试和请求 ID。显式实时评估使用 10 个问题、每题 3 次，输出：

- schema success rate；
- evidence validity；
- tool-selection stability；
- average latency；
- input/output/total tokens；
- 基于显式单价环境变量的 estimated cost。

运行方式见 [Agent 评估文档](agent-evaluation.md#opt-in-live-evaluation)。不把实时评估放进
默认测试，是为了避免 CI 或面试准备过程意外消耗模型额度。

## 可复现命令

```powershell
cd backend
pytest -q
python -m scripts.run_agent_evals

cd ../frontend
npm run build
```

机器生成的逐案例 JSON/Markdown 位于 `outputs/evals/`，该目录内容默认不提交，避免把每次
本地运行产物当作源代码。评估案例、评分器、阈值和本摘要均提交到仓库。
