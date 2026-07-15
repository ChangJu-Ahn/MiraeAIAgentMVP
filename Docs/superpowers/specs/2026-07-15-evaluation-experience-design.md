# Evaluation Experience Design

## Goal

Expose the customer-provided evaluation dataset and its versioned Azure AI
Evaluation results from the Chainlit header, and add an optional live answer
evaluation that never delays answer streaming.

## Scope

This change adds two related user experiences:

1. A public, read-only `Evaluation` dashboard linked beside Chainlit's Readme
   entry.
2. A default-off `답변 평가` setting that evaluates a completed answer in the
   background and exposes the result through a Chainlit action and sidebar.

The existing five-metric batch evaluation contract remains unchanged. The
feature does not add authentication, persistent server-side result storage,
new judge models, or automatic evaluation of every answer.

## Decisions

### Published evaluation snapshot

The dashboard uses a curated JSON snapshot generated from the latest batch
artifact. It includes:

- dataset title, item count, evaluation time, judge deployment, and threshold;
- aggregate average and pass rate for each metric;
- question, review answer, generated answer, score, pass flag, and judge reason
  for each item; and
- citation presence and question type.

It excludes exact judge context, retrieval traces, OData filters, source
records, source snippets, internal recommendations, and failure-cluster
implementation details. Publication is an explicit build-time operation, so a
new batch run cannot silently change the customer-facing dashboard.

The UI describes Groundedness, Relevance, Similarity, Coherence, and Fluency as
five evaluator criteria backed by Azure AI Evaluation. It must not imply that
five different judge models were used; all current evaluators use the recorded
judge deployment.

### Live evaluation policy

Every enabled live evaluation runs these four metrics:

- Groundedness: original question, collected evidence/source snippets, answer
- Relevance: original question and answer
- Coherence: original question and answer
- Fluency: answer

Similarity runs only when the stripped original question exactly matches a
question in the published customer snapshot and that row has a nonblank review
answer. The application never creates a synthetic reference answer. A
nonmatching question shows Similarity as `N/A` with the reason that no customer
review answer exists.

Scores use the existing 1-5 scale and pass at 3 or higher. Live results have a
separate contract that permits exactly four core metrics plus optional
Similarity; the strict five-metric `EvalArtifact` contract is not weakened.

## Architecture

### Snapshot publisher

`eval/publication.py` reads a validated `EvalArtifact`, projects only approved
fields, computes aggregate metric summaries, and writes deterministic JSON.
It also provides a CLI so a reviewed batch artifact can regenerate
`public/evaluation-data.json`.

### Static dashboard

`public/evaluation.html` fetches the colocated snapshot and renders an
operations-style evaluation dashboard. It contains a compact methodology
header, aggregate metric table, search, status filter, and expandable item
details. All untrusted strings are inserted with DOM text APIs rather than
HTML interpolation. The layout is responsive and uses the required Clawpilot
theme variables in light and dark modes.

`.chainlit/config.toml` registers an official `UI.header_links` entry targeting
`/public/evaluation.html`. No custom DOM manipulation is used.

### Live evaluator

`eval/live.py` owns:

- the live result model and validation;
- exact-match lookup of a customer review answer from the public snapshot;
- evaluation of an already-generated answer without calling `ask()`; and
- Markdown formatting for the result sidebar.

The synchronous Azure evaluator calls retain the existing retry and pacing
behavior and are invoked through `cl.make_async`, keeping them off the Chainlit
event loop. Evaluators are built per live job to avoid sharing uncertain SDK
state across worker threads.

### Chainlit integration

`app/chat.py` adds `answer_evaluation` to `ChatSettings` with `initial=False`
and stores it in the user session. After answer streaming, reflection,
visualization, and citations finish, the app sends a small evaluation status
message and retains an `asyncio.create_task` job.

The job evaluates the original user question and final answer with the final
round's evidence and source snippets. On success it stores formatted Markdown
in a per-session, ten-item FIFO store and updates the status message with a
`show_evaluation` action. The callback opens the stored result in the existing
`ElementSidebar` pattern. On failure it logs the exception and updates only the
status message; the answer remains available.

## Data Flow

### Published batch results

1. Run the existing batch evaluator and review its strict artifact.
2. Run the publication CLI against the approved JSON artifact.
3. Validate that the public snapshot contains only the allowlisted schema.
4. Build the container with `public/` and the runtime `eval/` package.
5. Chainlit serves the versioned dashboard and JSON from `/public`.

### Live answer results

1. Stream the answer and collect the normal `TraceRecorder` data.
2. Finish reflection, visuals, citations, and optional debug output.
3. If `답변 평가` is off, stop with no evaluator work or status message.
4. If enabled, send a pending status message and schedule a retained task.
5. Resolve an exact customer reference answer, if one exists.
6. Run four or five synchronous evaluators outside the event loop.
7. Store and expose the formatted result through an action and sidebar.

## Error Handling

- Missing or invalid public JSON renders a clear dashboard error without
  affecting chat.
- Invalid public projection input fails publication rather than emitting a
  partial snapshot.
- A missing reference answer skips Similarity; it is not an error.
- Invalid judge scores, retry exhaustion, authentication failures, and rate
  limits fail only that live evaluation job and are logged server-side.
- Background tasks are retained until completion and remove themselves from
  the retention set when done.
- Session result history is capped at ten entries, matching debug history.

## Security And Privacy

The deployed Container App is publicly reachable. The dashboard therefore
publishes only fields explicitly listed in this design. It does not fetch raw
`reports/` artifacts at runtime and does not expose retrieval internals. Live
evaluation results remain in Chainlit user-session memory and are not written
to a shared public file or telemetry payload by this feature.

## Testing

- Publication tests prove aggregate values and exact allowlisted row keys, and
  prove that context, traces, filters, and sources are absent.
- Live evaluator tests prove the four-metric contract, optional Similarity,
  exact customer-question matching, existing-answer evaluation without an
  agent call, and formatted `N/A` output.
- Chainlit tests prove default-off settings, no scheduling while disabled,
  background dispatch after rendering, successful action creation, isolated
  failure handling, history capping, and sidebar reopening.
- Static asset tests prove header-link configuration, required methodology
  text, safe DOM rendering, and Docker inclusion.
- The focused tests run first, followed by the full Python suite and container
  build. Playwright checks desktop and mobile layouts, text fit, asset loading,
  and browser console errors.

## Acceptance Criteria

- `Evaluation` is visible in the Chainlit header and opens the deployed
  dashboard.
- The dashboard shows all 16 customer questions and the recorded batch results
  for all five metrics without exposing internal context or traces.
- `답변 평가` is off for every new chat unless the user enables it.
- Enabled evaluation starts only after answer streaming completes and does not
  run the agent a second time.
- General questions receive four metrics; exact customer-dataset questions
  receive Similarity as a fifth metric.
- Completion exposes a reusable result action; evaluation failure does not
  remove or replace the answer.
- Existing batch evaluation behavior and its strict five-metric validation
  remain intact.