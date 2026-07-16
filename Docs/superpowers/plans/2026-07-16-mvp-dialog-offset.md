# MVP Dialog Offset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Chainlit full-screen dialog close controls visible below the persistent MVP notice.

**Architecture:** Extend the existing static asset contract, then use CSS selectors for body-level Radix overlays and full-screen dialogs. Reuse `--mvp-notice-height` so desktop and mobile offsets stay synchronized with the banner without changing Chainlit JavaScript or generated close-button classes.

**Tech Stack:** Chainlit 2.11.1, CSS, Python 3.12, pytest, Playwright, Azure Container Apps

## Global Constraints

- Keep the MVP notice visible while dialogs are open.
- Desktop dialog offset is 36 pixels; mobile dialog offset is 52 pixels at widths up to 480 pixels.
- Do not modify or stage the three untracked raw evaluation reports under `reports/`.
- Preserve the existing normal-chat root offset and mobile custom-link behavior.

---

### Task 1: Offset Full-Screen Dialogs Below the MVP Notice

**Files:**
- Modify: `tests/app/test_evaluation_assets.py`
- Modify: `public/custom.css`

**Interfaces:**
- Consumes: `--mvp-notice-height` and `body.mvp-notice-active` from `public/custom.css`
- Produces: a CSS contract that positions body-level Radix overlays and full-screen dialogs below the notice

- [x] **Step 1: Write the failing CSS contract test**

Add this test after `test_chainlit_registers_accessible_responsive_mvp_banner`:

```python
def test_chainlit_fullscreen_dialog_stays_below_mvp_banner():
    css = (ROOT / "public" / "custom.css").read_text(encoding="utf-8")

    assert "body.mvp-notice-active > [data-state].fixed.inset-0" in css
    assert 'body.mvp-notice-active > [role="dialog"].h-screen.w-screen' in css
    assert "top: var(--mvp-notice-height);" in css
    assert "height: calc(100dvh - var(--mvp-notice-height));" in css
    assert "max-height: calc(100dvh - var(--mvp-notice-height));" in css
    assert "transform: translateX(-50%);" in css
```

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/app/test_evaluation_assets.py::test_chainlit_fullscreen_dialog_stays_below_mvp_banner
```

Expected: FAIL because the overlay and dialog selectors are absent.

- [x] **Step 3: Add the minimal CSS implementation**

Add after the existing `body.mvp-notice-active #root` rule:

```css
body.mvp-notice-active > [data-state].fixed.inset-0 {
  top: var(--mvp-notice-height);
}

body.mvp-notice-active > [role="dialog"].h-screen.w-screen {
  top: var(--mvp-notice-height);
  height: calc(100dvh - var(--mvp-notice-height));
  max-height: calc(100dvh - var(--mvp-notice-height));
  transform: translateX(-50%);
}
```

- [x] **Step 4: Verify GREEN and the affected test module**

Run:

```bash
.venv/bin/pytest -q tests/app/test_evaluation_assets.py
```

Expected: all tests pass.

- [x] **Step 5: Verify the rendered desktop and mobile geometry**

Run Chainlit locally, open Readme with Playwright, and assert:

```text
desktop: notice.bottom = dialog.top = overlay.top = 36
mobile 390x844: notice.bottom = dialog.top = overlay.top = 52
closeButton.top >= notice.bottom
dialog.scrollHeight >= dialog.clientHeight
document.documentElement.scrollWidth == viewport width
```

- [x] **Step 6: Run complete local verification and commit**

Run:

```bash
.venv/bin/pytest -q
uv lock --check
node --check public/mvp-notice.js
git diff --check
```

Expected: 436 existing tests plus the new regression test pass; all static checks exit zero.

Commit only the test, CSS, and completed plan:

```bash
git add tests/app/test_evaluation_assets.py public/custom.css docs/superpowers/plans/2026-07-16-mvp-dialog-offset.md
git commit -m "fix: keep dialogs below MVP notice"
```

### Task 2: Deploy and Verify v17

**Files:**
- Modify: `.azure/deployment-plan.md`

**Interfaces:**
- Consumes: the committed dialog-offset image source and existing Bicep deployment
- Produces: a healthy Azure Container Apps revision running `mirae-chat:v17`

- [x] **Step 1: Run Azure preflight**

Compile `infra/main.bicep` and `infra/main.bicepparam`, run resource-group validation, and run what-if with `containerImage=acrmiraev4xy5m5d3ltw6.azurecr.io/mirae-chat:v17`. Require zero Delete changes.

- [ ] **Step 2: Build and deploy the image**

Use the existing ACR remote-build and Bicep deployment flow to push `mirae-chat:v17` plus the short Git SHA tag, then deploy that image to `ca-mirae-v4xy5m5d3ltw6`.

- [ ] **Step 3: Verify production behavior**

Require a healthy, provisioned revision with one replica and 100% traffic. Re-run the desktop and 390-by-844 Readme geometry assertions against the public URL, verify the close button works, and confirm `/health` returns HTTP 200.

- [ ] **Step 4: Record and publish deployment evidence**

Update `.azure/deployment-plan.md` with the image digest, ACR run, ARM deployment and correlation IDs, revision, geometry evidence, smoke tests, workload logs, and Application Insights results. Commit as `docs: record v17 deployment`, push `main`, and verify local `HEAD` equals `origin/main` without staging any `reports/` path.