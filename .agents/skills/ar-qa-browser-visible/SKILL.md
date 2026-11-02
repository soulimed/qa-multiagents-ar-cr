---
name: ar-qa-browser-visible
description: >-
  Force visible Cursor Browser for every AR/UI automated QA step: open browser
  permanently, type slowly, narrate each open/click/type, screenshot after key
  actions, log a live action strip for the QA Canvas. Use whenever Qata or the
  user asks to test AR UI, apidocs, login, validation, or watch the agent work.
---

# AR QA visible browser supervision

The user must **see** what the agent opens, types, and clicks. Cursor Browser is the live pane (resizable). Do not run silent API-only UI tests and claim the UI was verified.

## Hard rules

1. **Before any UI action**, open or focus Cursor Browser with `position: "active"` (or keep the existing AR tab locked and visible).
2. **Do not** drive AR only via curl/HTTP and call it a UI test.
3. **Type credentials and filters with `slowly: true`** when the browser tool supports it so the user can follow.
4. **Narrate in chat** in one short line before each meaningful step, e.g. `Browser: typing username…`, `Browser: click Login`, `Browser: open OF08CRIR`.
5. **Screenshots — full screen, highlighted, meaningful only**
   - **Full browser viewport / full screen only** — never save half-screen, cropped strips, black voids, blank white, or loading-only shots. If a capture is bad → **delete and retake**.
   - Before every evidence screenshot: **`browser_highlight`** the exact cell, dropdown, rule id, or value under test (e.g. Country dropdown + open option list). User must see what you care about.
   - Always: AR **login page showing product version** (highlight version text).
   - Always when UI testing a return: create/open return; run **Validation** / **Cross-validation** when relevant; highlight the control/values proven.
   - Export validation / cross-validation / sums from AR into `validation/` or `exports/`.
   - Do **not** keep meaningless screenshots.
6. **Action log** — append each step to the QA Canvas action strip and to `notes/browser-actions.md` under the evidence folder.
7. If the user says **stop**, unlock the browser and halt immediately.

## Permanent browser for automated UI tasks

At the start of a UI QA run:

1. `browser_tabs` list — reuse AR tab if logged in; else new tab.
2. Navigate to AR base URL (from user or secrets) with **visible** focus.
3. Lock the tab while automating; unlock when done or on stop.
4. Keep the tab open for the whole ticket run — do not close it between steps.
5. **Never close the browser** at the end of a “watch” phase either while the user still needs to review the workflow. Prefer leaving the window open (idle) over `browser.close()` / killing Chrome. The point of this skill is human supervision of the agent’s workflow (with Canvas action strip), not a finished headless job.

## Action strip format (Canvas + evidence)

Use one line per action:

```text
[HH:MM:SS] OPEN  <url or page title>
[HH:MM:SS] TYPE  <field> = <value or ••••>
[HH:MM:SS] CLICK <control name>
[HH:MM:SS] SEE   <what appeared>
[HH:MM:SS] FAIL  <what went wrong>
```

## AR login pattern (visible)

1. OPEN login page  
2. TYPE Username (slow)  
3. TYPE Password (slow) — never echo password in chat/canvas  
4. CLICK Login  
5. SEE dashboard / user menu  
6. Screenshot → `screenshots/01-login.png`

## What “little cursor” means here

Cursor Browser already shows real caret/focus. Extra fake mouse sprites are optional later. **Mandatory now:** slow typing + spoken/step log + screenshots so the user can watch, learn, or correct.

## Corrections → learning

If the user corrects a wrong click/menu/filter:

1. Stop.
2. Append a gotcha to `C:\WORK\qa-evidence\_agent_gotchas.md` (or ticket `notes/gotchas.md`): wrong path → right path.
3. On the next similar step, read gotchas first.

## Relation

- Pair with `ar-qa-ticket-evidence` for UI evidence.
- Pair with `ar-qa-db-readonly` for DB — DB does not need the browser unless the user asks to show SSMS-like results on Canvas only.
