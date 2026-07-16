# MVP Dialog Offset Design

## Problem

The persistent MVP notice occupies the top 36 pixels on desktop and 52 pixels on narrow mobile screens. Chainlit renders full-screen dialogs through a body-level Radix portal instead of inside `#root`, so the existing root offset does not affect those dialogs. The Readme close button remains at `y=16..32` behind the notice at `y=0..36`.

## Decision

Keep the MVP notice visible while dialogs are open and constrain body-level dialog portals to the viewport area below it. Apply the existing `--mvp-notice-height` variable to both the dialog content and its overlay so their top edge begins at the notice boundary and their height ends at the viewport bottom.

This preserves the persistent-notice requirement, keeps the close button visible, and avoids coupling the fix to Chainlit's generated close-button classes.

## Scope

- Add a CSS contract test for an active-notice dialog and overlay offset.
- Update `public/custom.css` only after the test fails for the missing contract.
- Verify the Readme dialog and close button at desktop and 390-pixel mobile widths.
- Confirm the normal chat root offset and single-banner behavior remain unchanged.

## Success Criteria

- The dialog and overlay start at `var(--mvp-notice-height)` while the notice is active.
- The Readme close button top is at or below the notice bottom.
- The Readme content remains scrollable without horizontal overflow.
- Desktop uses a 36-pixel offset and mobile uses a 52-pixel offset.