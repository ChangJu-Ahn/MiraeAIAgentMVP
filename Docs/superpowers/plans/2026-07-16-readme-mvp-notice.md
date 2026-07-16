# Readme and MVP Notice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the complete repository README at the bottom of the Chainlit Readme panel and identify the app as a non-Production PoC/MVP in the Readme, welcome message, and a persistent responsive banner.

**Architecture:** Keep `README.md` as the canonical detailed document and copy it verbatim to the suffix of `chainlit.md`, protected by an exact-suffix test. Load one small idempotent JavaScript asset through Chainlit's supported `UI.custom_js` setting to create an accessible banner outside the React root; CSS reserves the banner height so existing desktop and mobile controls remain usable.

**Tech Stack:** Chainlit 2.11.1, Markdown, vanilla JavaScript DOM APIs, CSS media queries, Python 3.12, pytest.

## Global Constraints

- Keep all existing concise user-facing content in `chainlit.md`.
- The complete current `README.md` must be the exact final suffix of `chainlit.md`.
- Use this full notice in the Readme and welcome message: `본 서비스는 기능과 사용자 경험 검증을 위한 PoC/MVP이며, Production 운영용 서비스가 아닙니다. 중요한 판단에는 답변의 출처와 원본 문서를 함께 확인해 주세요.`
- Use this compact banner copy: `MVP 안내: 기능 검증용 PoC이며 Production 운영용 서비스가 아닙니다.`
- The banner must be idempotent, accessible as a note, visible on desktop and mobile, and must not obscure Chainlit controls.
- Do not stage or commit the three raw evaluation artifacts under `reports/`.

---

### Task 1: Readme and welcome-message contracts

**Files:**
- Modify: `tests/app/test_evaluation_assets.py`
- Modify: `tests/agent/test_streaming.py`
- Modify: `chainlit.md`
- Modify: `app/chat.py`

**Interfaces:**
- Consumes: canonical detailed content from `README.md`.
- Produces: `chainlit.md` whose first block is the MVP notice and whose final bytes equal `README.md`; one existing `cl.Message` welcome message beginning with the same notice.

- [x] **Step 1: Write the failing Readme contract test**

Replace the old developer-content exclusions with an exact source contract:

```python
repository_readme = (ROOT / "README.md").read_text(encoding="utf-8")
notice = (
    "본 서비스는 기능과 사용자 경험 검증을 위한 PoC/MVP이며, "
    "Production 운영용 서비스가 아닙니다."
)

assert readme.startswith("> **MVP 안내**")
assert notice in readme
assert readme.endswith(repository_readme)
```

- [x] **Step 2: Write the failing welcome-message test**

Capture sent messages in `test_chat_start_sends_debug_and_reasoning_settings`:

```python
sent_messages = []

class FakeSendable:
    def __init__(self, content=""):
        self.content = content

    async def send(self):
        if self.content:
            sent_messages.append(self.content)
        return self

assert len(sent_messages) == 1
assert sent_messages[0].startswith("**MVP 안내**")
assert "Production 운영용 서비스가 아닙니다" in sent_messages[0]
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
uv run pytest -q \
  tests/app/test_evaluation_assets.py::test_chainlit_readme_documents_the_verified_user_experience \
  tests/agent/test_streaming.py::test_chat_start_sends_debug_and_reasoning_settings
```

Expected: both tests fail because the MVP notice and exact README suffix are absent.

- [x] **Step 4: Implement the Readme and welcome message**

Prepend this block to `chainlit.md`:

```markdown
> **MVP 안내**
>
> 본 서비스는 기능과 사용자 경험 검증을 위한 PoC/MVP이며, **Production 운영용 서비스가 아닙니다.** 중요한 판단에는 답변의 출처와 원본 문서를 함께 확인해 주세요.
```

After the existing final paragraph, add `---` and then the complete unmodified contents of `README.md`. Prepend this to the existing welcome message in `app/chat.py`:

```python
"**MVP 안내**\n"
"본 서비스는 기능과 사용자 경험 검증을 위한 PoC/MVP이며, "
"**Production 운영용 서비스가 아닙니다.** 중요한 판단에는 "
"답변의 출처와 원본 문서를 함께 확인해 주세요.\n\n"
```

- [x] **Step 5: Run tests and verify GREEN**

Run the Step 3 command again.

Expected: `2 passed`.

### Task 2: Persistent responsive MVP banner

**Files:**
- Modify: `.chainlit/config.toml`
- Create: `public/mvp-notice.js`
- Modify: `public/custom.css`
- Modify: `tests/app/test_evaluation_assets.py`

**Interfaces:**
- Consumes: Chainlit `UI.custom_js` loading `/public/mvp-notice.js`.
- Produces: one `aside#mvp-notice[role="note"]` under `body`, the `mvp-notice-active` body class, and responsive CSS using `--mvp-notice-height`.

- [x] **Step 1: Write the failing asset and DOM contract test**

Add a focused test that checks the public contract:

```python
def test_chainlit_registers_accessible_responsive_mvp_banner():
    config = tomllib.loads(
        (ROOT / ".chainlit" / "config.toml").read_text(encoding="utf-8")
    )
    javascript = (ROOT / "public" / "mvp-notice.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "custom.css").read_text(encoding="utf-8")

    assert config["UI"]["custom_js"] == "/public/mvp-notice.js"
    assert 'notice.id = "mvp-notice"' in javascript
    assert 'notice.setAttribute("role", "note")' in javascript
    assert 'notice.setAttribute("aria-label", "MVP 서비스 안내")' in javascript
    assert 'document.getElementById("mvp-notice")' in javascript
    assert "Production 운영용 서비스가 아닙니다" in javascript
    assert "--mvp-notice-height" in css
    assert "body.mvp-notice-active #root" in css
    assert "#mvp-notice" in css
    assert "@media (max-width: 480px)" in css
```

- [x] **Step 2: Run the test and verify RED**

Run:

```bash
uv run pytest -q tests/app/test_evaluation_assets.py::test_chainlit_registers_accessible_responsive_mvp_banner
```

Expected: fail because `custom_js` and `public/mvp-notice.js` do not exist.

- [x] **Step 3: Implement minimal JavaScript and configuration**

Set `custom_js = "/public/mvp-notice.js"` in `.chainlit/config.toml`. Create an IIFE that mounts once:

```javascript
(() => {
  const mountNotice = () => {
    let notice = document.getElementById("mvp-notice");
    if (!notice) {
      notice = document.createElement("aside");
      notice.id = "mvp-notice";
      notice.setAttribute("role", "note");
      notice.setAttribute("aria-label", "MVP 서비스 안내");

      const label = document.createElement("strong");
      label.textContent = "MVP 안내:";
      notice.append(label, " 기능 검증용 PoC이며 Production 운영용 서비스가 아닙니다.");
      document.body.prepend(notice);
    }
    document.body.classList.add("mvp-notice-active");
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountNotice, { once: true });
  } else {
    mountNotice();
  }
})();
```

- [x] **Step 4: Implement responsive CSS**

Use a 36-pixel desktop and 52-pixel mobile reserved height. Fix the banner at the top, constrain text, and place `#root` below it:

```css
:root {
  --mvp-notice-height: 36px;
}

#mvp-notice {
  position: fixed;
  inset: 0 0 auto;
  z-index: 1000;
  min-height: var(--mvp-notice-height);
}

body.mvp-notice-active #root {
  position: fixed;
  inset: var(--mvp-notice-height) 0 0;
}

@media (max-width: 480px) {
  :root {
    --mvp-notice-height: 52px;
  }
}
```

Complete the visual properties with an amber warning surface, readable contrast, centered desktop text, left-aligned mobile text, stable line heights, and no viewport-scaled font size.

- [x] **Step 5: Run the focused asset tests and verify GREEN**

Run:

```bash
uv run pytest -q tests/app/test_evaluation_assets.py
```

Expected: all tests in the file pass.

### Task 3: Integrated verification

**Files:**
- Verify only; no new production files.

**Interfaces:**
- Consumes: all Task 1 and Task 2 outputs.
- Produces: executable proof for automated contracts and desktop/mobile browser behavior.

- [x] **Step 1: Run focused and full automated gates**

```bash
uv run pytest -q tests/app/test_evaluation_assets.py tests/agent/test_streaming.py
uv run pytest -q
uv lock --check
git diff --check
```

Expected: focused tests pass, full suite reports zero failures, lock is current, and no whitespace errors are reported.

- [x] **Step 2: Start or restart local Chainlit**

```bash
uv run chainlit run app/chat.py --host 127.0.0.1 --port 8001
```

Expected: the app starts and serves `/public/mvp-notice.js`, `/public/custom.css`, and the chat UI.

- [x] **Step 3: Verify desktop browser behavior**

At a desktop viewport, verify:

- exactly one `#mvp-notice` exists and has `role="note"`;
- the banner and application header bounding boxes do not overlap;
- the welcome message starts with the full MVP notice;
- the Readme starts with the full notice and ends with the final `README.md` sentence;
- opening Readme or starting a new chat does not duplicate the banner;
- there is no horizontal overflow.

- [x] **Step 4: Verify 390-pixel mobile behavior**

At `390x844`, verify that the two-line banner is visible, `#root` begins below it, Evaluation and source-document icons remain present, the composer remains usable, and `scrollWidth <= clientWidth`.

- [x] **Step 5: Review and commit implementation**

Stage only the plan, application, public assets, configuration, tests, and `chainlit.md`. Explicitly reject anything under `reports/` before committing:

```bash
git diff --cached --check
git diff --cached --name-only | grep '^reports/' && exit 1 || true
git commit -m "feat: mark chat experience as MVP"
```