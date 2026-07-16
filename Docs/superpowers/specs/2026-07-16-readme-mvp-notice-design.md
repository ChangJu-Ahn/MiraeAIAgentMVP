# Chainlit Readme and MVP notice design

## Status

Approved in conversation on 2026-07-16.

## Goal

Explain the agent's full behavior in the Chainlit Readme panel and make it
unmistakable that the application is a PoC/MVP rather than a Production service.

## Content contract

- Keep the existing user-facing content at the start of `chainlit.md`.
- Put the MVP notice at the top of `chainlit.md`, before the product title.
- Add a horizontal divider after the existing user-facing content.
- Append the complete contents of `README.md` after that divider without editing,
  abbreviating, or reordering the source text.
- Treat `README.md` as the canonical detailed technical document. A test must fail
  whenever `chainlit.md` no longer ends with the exact current `README.md` text.

The shared notice copy is:

> **MVP 안내**
> 본 서비스는 기능과 사용자 경험 검증을 위한 PoC/MVP이며, Production 운영용
> 서비스가 아닙니다. 중요한 판단에는 답변의 출처와 원본 문서를 함께 확인해
> 주세요.

The persistent banner uses the shorter form:

> **MVP 안내:** 기능 검증용 PoC이며 Production 운영용 서비스가 아닙니다.

## User experience

### Persistent banner

- Register `/public/mvp-notice.js` through Chainlit's supported `UI.custom_js`
  setting.
- The script adds one `aside#mvp-notice` directly to `document.body` and adds an
  `mvp-notice-active` class to the body. Re-running the script must not duplicate
  the banner.
- Use `role="note"` and an accessible label. The notice is important context but
  is not an urgent live alert.
- Keep the banner fixed above the Chainlit root. Reserve the same height on
  `#root` so the application header, dialogs, and message composer are not
  obscured.
- Use a compact one-line desktop treatment and a fixed two-line mobile treatment.
  The mobile breakpoint must leave the existing Evaluation and source-document
  header icons visible.

### Chat start

- Put the full notice at the beginning of the existing welcome message sent by
  `on_chat_start`.
- Keep one welcome message rather than adding a second message.
- Preserve the existing settings guidance after the notice.

### Readme panel

- Show the full notice as the first visible content in `chainlit.md`.
- Preserve the current concise product guide immediately after the notice.
- Put the repository `README.md` in full at the very bottom so users can inspect
  architecture, indexes, tools, examples, setup, evaluation, and observability.

## Files

- `.chainlit/config.toml`: register the custom JavaScript asset.
- `public/mvp-notice.js`: insert the persistent accessible notice once.
- `public/custom.css`: style the notice and reserve responsive layout space.
- `app/chat.py`: prepend the notice to the existing welcome message.
- `chainlit.md`: add the top notice and exact `README.md` suffix.
- `tests/app/test_evaluation_assets.py`: verify asset registration, notice DOM
  contract, responsive CSS, top notice, and exact README suffix.
- `tests/agent/test_streaming.py`: verify the welcome message contains the notice.

## Verification

- Run the focused app asset and chat-start tests first.
- Run the complete pytest suite, `uv lock --check`, and `git diff --check`.
- Start the local Chainlit app and verify desktop and 390-pixel mobile layouts in
  a browser: banner visible, no overlap or horizontal overflow, Readme notice at
  the top, and the full repository README present at the bottom.
- Verify the banner is not duplicated after navigation or a new chat.

## Out of scope

- Authentication, authorization, or Production-readiness changes.
- Changing the canonical repository README beyond copying its current content.
- Hiding developer commands or infrastructure details from the Readme panel.