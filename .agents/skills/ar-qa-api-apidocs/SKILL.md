---
name: ar-qa-api-apidocs
description: >-
  API ticket QA in Cursor: ask manual AR apidocs (visible browser, fill try-it,
  user can Take control) vs Postman/other API tool; narrate and evidence either
  path. Use when testing REST/swagger/Postman for AR or API Jira tickets.
---

# AR QA API — browser or Postman-style

When an API ticket (or ticket step) needs API checks, **ask once**:

> Test this API **manually in AR apidocs** (Cursor Browser — you can watch or Take control), or via **Postman / HTTP tool**?

Default if unclear: **manual apidocs** (easiest to supervise).

## Path A — Manual (Cursor Browser)

Follow `ar-qa-browser-visible`:

1. Open `{AR_BASE}/apidocs/` with visible focus (permanent tab for the run).
2. Ask which definition/API if not on the ticket: IDAM / Job / Return / Product / Settings (or named path).
3. Navigate to the endpoint; expand; fill required fields/params/body **visibly** (slow type when useful).
4. Execute Try it / equivalent; screenshot request + response.
5. Say **works** or **fails** with HTTP status and short reason.
6. If user Take control / interrupts: stop automation, wait, then resume from their state or their instruction.

## Path B — Postman / API tool

1. Narrate the exact method + URL + auth approach (no secret echo).
2. Prefer collection/script already in the repo or ticket; else build minimal requests from swagger.
3. Prefer non-destructive methods first (GET). POST/PUT/DELETE only if the ticket/user requires it — confirm before mutating.
4. Still keep apidocs open in browser so the user can cross-check or Take control and finish manually.
5. Save response JSON under `exports/` or `notes/api-*.json`.

## Auth note

Raw `swagger.json` or REST calls may return **401** without AR session/cookie. Prefer browser session for Try-it, or ask how the user authenticates APIs on that env.

## Evidence

- Screenshots: `screenshots/api-*.png`
- Notes: `notes/api-smoke.md` (endpoint, mode manual|tool, result)
- Canvas action strip: OPEN / TYPE / CLICK / SEE / FAIL lines

## Never

- Claim API tested without opening browser or running a real request
- Invent response bodies
- Skip the manual-vs-tool question when both are reasonable
