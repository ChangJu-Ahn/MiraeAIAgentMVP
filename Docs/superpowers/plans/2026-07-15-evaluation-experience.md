# Evaluation Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a customer-visible evaluation dashboard and optional nonblocking live answer evaluation without changing the strict batch evaluation contract.

**Architecture:** Publish a privacy-filtered, versioned JSON projection of the approved batch artifact and render it from a static Chainlit-served dashboard. Add a separate live evaluation module for four core metrics plus optional exact-match Similarity, then schedule it from Chainlit only after the answer is fully rendered.

**Tech Stack:** Python 3.12, Pydantic 2, Azure AI Evaluation 1.17, Chainlit 2.11.1, static HTML/CSS/JavaScript, pytest, Docker, Playwright.

## Global Constraints

- Keep `EvalArtifact` and `validate_eval_rows()` strict at exactly five metrics.
- Never call `ask()` from live evaluation and never generate a synthetic reference answer.
- `답변 평가` must be off at the start of every chat.
- Publish only metadata, aggregate metrics, questions, review answers, generated answers, scores, pass flags, reasons, question type, and citation flag.
- Do not publish judge context, traces, OData filters, source records, source snippets, recommendations, or raw reports.
- Use the exact Clawpilot theme variables and only `var(--cp-*)` color values in the dashboard.
- Do not commit changes; the user did not request a commit for this feature.

---

### Task 1: Public Evaluation Projection

**Files:**
- Create: `tests/eval/test_publication.py`
- Create: `eval/publication.py`
- Generate: `public/evaluation-data.json`

**Interfaces:**
- Consumes: `EvalArtifact.model_validate_json(raw: str)`, `METRICS`.
- Produces: `build_public_snapshot(artifact: EvalArtifact) -> dict[str, object]`.
- Produces: `publish_evaluation(input_path: Path, output_path: Path) -> Path`.
- Produces CLI: `python -m eval.publication INPUT_JSON OUTPUT_JSON`.

- [x] **Step 1: Write failing projection tests**

Create fixtures with all five metrics, context, steps, and sources. Assert this exact row key set:

```python
PUBLIC_ROW_KEYS = {
    "id", "qtype", "question", "ground_truth", "answer",
    "metrics", "passed", "reasons", "cited",
}

snapshot = build_public_snapshot(_artifact())
assert set(snapshot["rows"][0]) == PUBLIC_ROW_KEYS
assert "context" not in json.dumps(snapshot, ensure_ascii=False)
assert snapshot["metrics"][0] == {
    "name": "groundedness",
    "average": 4.0,
    "pass_rate": 100.0,
    "passed": 1,
    "total": 1,
}
```

Also assert metadata has only `dataset_title`, `item_count`, `evaluated_at`,
`judge_deployment`, and `pass_threshold`, and assert CLI output round-trips as
UTF-8 JSON with `allow_nan=False` behavior.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest -q tests/eval/test_publication.py`

Expected: import failure for missing `eval.publication`.

- [x] **Step 3: Implement the deterministic allowlist projection**

Implement:

```python
def build_public_snapshot(artifact: EvalArtifact) -> dict[str, object]:
    validate_eval_rows(artifact.rows)
    metrics = []
    for name in METRICS:
        values = [row.metrics[name] for row in artifact.rows]
        flags = [row.passed[name] for row in artifact.rows]
        metrics.append({
            "name": name,
            "average": sum(values) / len(values),
            "pass_rate": 100.0 * sum(flags) / len(flags),
            "passed": sum(flags),
            "total": len(flags),
        })
    return {
        "schema_version": 1,
        "metadata": {
            "dataset_title": artifact.metadata.dataset_title,
            "item_count": artifact.metadata.item_count,
            "evaluated_at": artifact.metadata.evaluated_at,
            "judge_deployment": artifact.metadata.judge_deployment,
            "pass_threshold": 3.0,
        },
        "metrics": metrics,
        "rows": [
            {
                "id": row.id,
                "qtype": row.qtype,
                "question": row.question,
                "ground_truth": row.ground_truth,
                "answer": row.answer,
                "metrics": row.metrics,
                "passed": row.passed,
                "reasons": row.reasons,
                "cited": row.cited,
            }
            for row in artifact.rows
        ],
    }
```

`publish_evaluation()` must validate the source as `EvalArtifact`, create the
output parent, and write an atomic UTF-8 JSON file using a sibling temporary
file followed by `replace()`.

- [x] **Step 4: Run tests and verify GREEN**

Run: `uv run pytest -q tests/eval/test_publication.py`

Expected: all publication tests pass.

- [x] **Step 5: Generate and inspect the approved snapshot**

Run:

```bash
uv run python -m eval.publication \
  reports/eval-Chatbot_질문지리스트_20260713-deployed-v11-20260715.json \
  public/evaluation-data.json
```

Then assert 16 rows and no forbidden fields with:

```bash
uv run python -c 'import json; p=json.load(open("public/evaluation-data.json")); assert len(p["rows"]) == 16; assert not ({"context", "steps", "sources", "odata_filter"} & set().union(*(r.keys() for r in p["rows"])))'
```

---

### Task 2: Evaluation Dashboard And Container Assets

**Files:**
- Create: `tests/app/test_evaluation_assets.py`
- Create: `public/evaluation.html`
- Create: `public/evaluation-icon.png`
- Modify: `.chainlit/config.toml`
- Modify: `.dockerignore`
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: `/public/evaluation-data.json` schema version 1.
- Produces: `/public/evaluation.html` and a Chainlit `UI.header_links` entry.

- [x] **Step 1: Write failing static-contract tests**

Assert the TOML link has the exact values:

```python
link = config["UI"]["header_links"][0]
assert link == {
    "name": "Evaluation",
    "display_name": "Evaluation",
    "icon_url": "/public/evaluation-icon.png",
    "url": "/public/evaluation.html",
    "target": "_blank",
}
```

Assert the HTML contains the required theme-detection script, every `--cp-*`
variable, fetches `./evaluation-data.json`, renders data with `textContent`,
contains search and status-filter controls, and contains no `innerHTML`.
Assert Docker copies `eval/` and `public/`, and `.dockerignore` no longer
excludes the complete `eval` directory.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest -q tests/app/test_evaluation_assets.py`

Expected: missing public assets and header link assertions fail.

- [x] **Step 3: Add the official Chainlit header link and image asset**

Append:

```toml
[[UI.header_links]]
name = "Evaluation"
display_name = "Evaluation"
icon_url = "/public/evaluation-icon.png"
url = "/public/evaluation.html"
target = "_blank"
```

Generate a transparent 64x64 PNG with three rose chart bars and a dark/light
neutral baseline using Pillow. The image must remain legible at the Chainlit
header's icon size.

- [x] **Step 4: Build the responsive static dashboard**

Create a semantic page with:

- methodology header and the explicit statement that five evaluators are five
  quality criteria, not five different judge models;
- aggregate metric rows with average, pass rate, and stable-width progress
  bars;
- text search and `전체` / `통과` / `검토 필요` segmented status filter;
- an unframed question list whose expandable details show review answer,
  generated answer, five metric chips, and judge reasons; and
- empty, loading, and fetch-error states.

The first script must set `data-theme` from `scoutTheme` or browser preference.
Use only DOM creation plus `textContent` for snapshot strings. Use CSS media
queries at 760px and 480px to collapse metric rows and controls without overlap.

- [x] **Step 5: Include runtime assets in the image**

Remove the standalone `eval` line from `.dockerignore` and add:

```dockerfile
COPY eval/ eval/
COPY public/ public/
```

Keep `reports/` excluded so raw artifacts cannot enter the image.

- [x] **Step 6: Run tests and verify GREEN**

Run: `uv run pytest -q tests/app/test_evaluation_assets.py`

Expected: all static-contract tests pass.

---

### Task 3: Existing-Answer Live Evaluator

**Files:**
- Create: `tests/eval/test_live.py`
- Create: `eval/live.py`

**Interfaces:**
- Consumes: `_build_evaluators()` and `_evaluate_metric()` from `eval.runner`.
- Produces: `LiveEvaluationResult`.
- Produces: `find_reference_answer(question: str, snapshot_path: Path | None = None) -> str | None`.
- Produces: `evaluate_existing_answer(question: str, answer: str, sources: list[RetrievedSource], evidence: list[str] | None = None, ground_truth: str | None = None, evaluators: dict[str, object] | None = None) -> LiveEvaluationResult`.
- Produces: `format_live_evaluation(result: LiveEvaluationResult) -> str`.

- [x] **Step 1: Write failing live-contract tests**

Use callable fake evaluators and assert a no-reference call produces exactly:

```python
assert set(result.metrics) == {
    "groundedness", "relevance", "coherence", "fluency"
}
assert "similarity" not in calls
assert calls["groundedness"] == {
    "query": "질문",
    "context": "구조화 근거\n\n검색 문장",
    "response": "기존 답변",
}
```

With `ground_truth="검토 정답"`, assert Similarity is called with only query,
response, and ground truth. Assert invalid metric sets fail Pydantic validation.
Assert exact stripped question matching returns the review answer while changed
case or punctuation returns `None`. Assert formatted no-reference output includes
`Similarity`, `N/A`, and `일치하는 고객 검토 정답 없음`.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest -q tests/eval/test_live.py`

Expected: import failure for missing `eval.live`.

- [x] **Step 3: Implement the separate live result contract**

Define core metric order as Groundedness, Relevance, Coherence, Fluency. A model
validator must require exactly those four keys in `metrics`, `passed`, and
`reasons`, plus Similarity in all three only when `ground_truth` is nonblank.
It must validate finite scores in 1..5, nonblank reasons, and pass consistency at
threshold 3.

- [x] **Step 4: Implement snapshot lookup and existing-answer evaluation**

Load `public/evaluation-data.json` relative to the repository/app root and cache
the question-to-review-answer map by resolved path. Compare `question.strip()`
to stored `question.strip()` without case folding or punctuation normalization.

Build evaluator kwargs from the already-generated answer. Iterate only the
selected metric names, use the existing judge validation/retry helper, and pace
calls with one second between metrics. Do not import or invoke `ask()`.

- [x] **Step 5: Implement sidebar Markdown formatting**

Render a pass-count summary, optional customer review answer, a score/status
table in stable metric order, and one reason section per executed evaluator.
Always include a Similarity row; render it as `N/A` with the exact missing-review
explanation when omitted.

- [x] **Step 6: Run tests and verify GREEN**

Run: `uv run pytest -q tests/eval/test_live.py tests/eval/test_runner.py`

Expected: new live tests and unchanged batch runner tests pass.

---

### Task 4: Chainlit Background Evaluation UX

**Files:**
- Modify: `tests/agent/test_streaming.py`
- Modify: `app/chat.py`

**Interfaces:**
- Consumes: `find_reference_answer`, `evaluate_existing_answer`, and
  `format_live_evaluation` from `eval.live`.
- Produces action callback: `show_evaluation(action: cl.Action) -> None`.

- [x] **Step 1: Add failing settings tests**

Update startup expectations to include:

```python
"answer_evaluation": False
```

and widget order:

```python
["debug", "reflection", "answer_evaluation", "effort"]
```

Update settings persistence to assert the submitted boolean is stored.

- [x] **Step 2: Run settings tests and verify RED**

Run: `uv run pytest -q tests/agent/test_streaming.py -k 'chat_start or settings_update'`

Expected: missing session value and widget assertions fail.

- [x] **Step 3: Implement the default-off setting and verify GREEN**

Add a `Switch` labeled `답변 평가 (답변 완료 후 품질 평가)` with
`initial=False`, store it at chat start, and persist it from settings updates.
Rerun the command from Step 2 and expect it to pass.

- [x] **Step 4: Add failing dispatch and completion tests**

Assert `answer_and_render()` never calls `_schedule_answer_evaluation` while the
setting is false and calls it once with the original question, final answer,
and final trace while true.

Directly await `_run_answer_evaluation()` with a fake `cl.make_async` wrapper.
Assert it stores formatted Markdown, caps history at ten, changes the pending
message to `답변 평가 완료`, and adds a `show_evaluation` action whose payload ID
exists in the store. Add a failure test asserting exceptions are logged and the
message becomes `답변 평가 실패` without an action. Add a callback test that
reopens the stored Markdown in `ElementSidebar`.

- [x] **Step 5: Run background tests and verify RED**

Run: `uv run pytest -q tests/agent/test_streaming.py -k 'evaluation'`

Expected: missing scheduling, worker, and callback symbols fail.

- [x] **Step 6: Implement retained nonblocking jobs**

Add a module-level `set[asyncio.Task]`. `_schedule_answer_evaluation()` sends a
`답변 평가 중` message, creates a task for `_run_answer_evaluation()`, retains it,
and discards it in a done callback. The worker resolves an optional reference,
calls the synchronous evaluator through `await cl.make_async(...)(...)`, updates
the session FIFO, and updates the same status message.

Call the scheduler at the end of `answer_and_render()` only after visuals,
citations, and optional debug output have completed. Use `original_question`,
the final `answer_text`, and final `trace`.

- [x] **Step 7: Run focused tests and verify GREEN**

Run: `uv run pytest -q tests/agent/test_streaming.py tests/eval/test_live.py`

Expected: all focused live UX tests pass.

---

### Task 5: Documentation And End-To-End Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents the public snapshot command, live metric policy, and privacy scope.

- [x] **Step 1: Update evaluation documentation**

Add the publication command after the batch evaluation commands. Document that
the header dashboard is versioned with the image, that five evaluators are five
criteria on the configured judge deployment, and that live evaluation runs four
metrics plus exact-customer-question Similarity only when the setting is enabled.

- [ ] **Step 2: Run all executable validation**

Run:

```bash
uv run pytest -q
uv lock --check
docker build -t mirae-chat:evaluation-local .
```

Expected: 0 test failures, lock check exit 0, and Docker build exit 0.

Status: `uv run pytest -q` passed 427 tests and `uv lock --check` resolved 250
packages. The Docker build remains unverified because this workstation has no
Docker-compatible CLI installed.

- [x] **Step 3: Start Chainlit and validate with Playwright**

Start `uv run chainlit run app/chat.py --host 127.0.0.1 --port 8000` as a
long-running process. Open both the chat and `/public/evaluation.html` at
1440x1000 and 390x844. Assert the Evaluation header link opens the dashboard,
16 rows load, search and status filtering work, one item expands, no text or
controls overlap, and the browser console has no errors.

Validated on port 8001 at desktop and mobile viewports. The dashboard had no
console errors, overflow, overlap, or clipping; Chainlit itself retained its
pre-existing `*/*` upload MIME warning.

- [x] **Step 4: Inspect the final diff and privacy boundary**

Run:

```bash
git diff --check
git status --short
git diff -- . ':!public/evaluation-data.json'
```

Verify raw report files remain untracked/excluded, no unrelated tracked files
changed, and the generated public JSON contains no forbidden keys.