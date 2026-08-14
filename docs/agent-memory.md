# Agent Memory

## Scope

Market Pilot uses structured SQL memory rather than RAG or a vector database. The current memory requirements are exact: retain public report conversations, reuse explicit merchant facts, and compare canonical metrics across analyses of the same project.

## Stored Data

- `AnalysisConversation`: one conversation per persisted analysis.
- `AnalysisMessage`: public user questions and final public answers, including mode, evidence references, and sanitized read-only tool calls.
- `ProjectProfile`: confirmed store identity, stage, city, category, merchant targets, cost assumptions, presentation preferences, observation time, and field sources.

The application does not store chain-of-thought, API keys, full provider responses, or rejected candidate output as conversation memory. Tool-call persistence only allows the tool name and a bounded canonical metric path.

## Retrieval Rules

- Follow-up prompts receive at most the latest six public messages.
- Historical messages are labeled as untrusted context and cannot serve as factual evidence.
- The current persisted report is supplied independently on every request.
- Confirmed project targets are merged into report targets without overwriting values already saved on that report.
- `read_metric_history` retrieves the same canonical metric from the latest prior analysis of the same project.
- Historical comparisons require a registered metric definition and numeric values. Returned evidence identifies both the current metric and the exact prior analysis.

## Why No Vector Database

Current retrieval keys are analysis ID, project ID, message order, and canonical metric path. SQL queries are deterministic, inspectable, and sufficient for those access patterns. Embeddings would add infrastructure and non-deterministic retrieval without solving a current requirement.
