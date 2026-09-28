# Conversation History And Recovery

## Purpose

Users can leave the frontend and later recover a saved project, report, follow-up
conversation, answer versions, and approved correction results without running an
agent again. History reads are database-only operations and do not call the LLM,
map provider, or knowledge retrieval service.

## Persistence Boundary

```text
User
  -> Project (project-level profile and revision lessons)
    -> AnalysisResult (immutable saved report)
      -> AnalysisConversation (one conversation per report)
        -> AnalysisMessage (ordered user/assistant transcript)
        -> AnswerVersion (full, revision-aware answer artifact)
```

An `AnalysisConversation` belongs to exactly one `AnalysisResult`. It is not
shared across reports because each report has a distinct evidence snapshot and
metrics context. `ProjectProfile` and `RevisionLesson` remain project-scoped and
are the only cross-report memory inputs.

## Write Flow

1. `/analysis/{analysis_id}/chat` obtains or creates the report conversation.
2. The agent creates an `AnswerVersion` before the exchange is committed.
3. The assistant `AnalysisMessage` stores `answer_version_id`, making the
   transcript entry traceable to the complete answer, sources, and revision parent.
4. The project and conversation update timestamps are refreshed in the same
   database transaction.

Existing historical messages remain valid: their new `answer_version_id` and
`status` fields are nullable/additive migration fields.

## Read Flow

- `GET /projects`: current user's project directory, ordered by recent activity.
- `GET /projects/{project_id}/analyses`: immutable reports for an owned project.
- `GET /analysis/{analysis_id}/conversation`: paged chronological transcript for
  an owned report. It deliberately does not create an empty conversation.
- `GET /analysis/{analysis_id}/answer-versions`: full answer artifacts, including
  revision lineage.

Every route derives access from the authenticated user and uses the existing
project/analysis ownership guards. No client-supplied user identifier participates
in access control.

## UI Recovery

`/history` is the entry point: choose a project, then a saved report, and open the
existing report page. The report's follow-up panel reloads the persisted transcript,
answer versions, and correction state. The current report remains the execution
context for the next question; reopening it does not merge unrelated report data.

## Explicit Non-goals

- No RAG is used to retrieve user history; relational lookup is exact, cheaper,
  and auditable.
- No global chat thread spans multiple reports.
- A failed in-flight request is not shown as a completed message. A future
  reliability iteration can add client request IDs and `pending` messages when
  durable interruption recovery is required.
