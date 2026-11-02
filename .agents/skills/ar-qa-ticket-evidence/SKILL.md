---
name: ar-qa-ticket-evidence
description: >-
  AR / AR4PRA ticket QA when the user says test this ticket / help me test this
  ticket: read Jira, plan steps, run UI in visible Cursor Browser, ask DB type +
  credentials for read-only vals/xvals/sums/rets queries (Excel on request), and
  for API tickets offer browser apidocs (manual) vs Postman-style tooling with
  user watch/take-control. Pass/Fail evidence folder; Jira comment only after confirm.
---

# AR QA ticket evidence playbook

Canonical pattern when the user (or Qata) says **“test this ticket”** / **“help me test this ticket”**.
Do not skip user confirmation before the Jira comment.

## Gate 0 — Product from Jira key (mandatory first)

Read the **project key in the ticket header** before picking env/DB:

| Key prefix | Product | Do not assume |
|---|---|---|
| **`AR4PRA-*`** | **Agile Reporter (AR)** | — use AR UI + AR DB (e.g. `AR_USER_18`) |
| **`CR4PRA-*`** | **CR Compliance Reporter** | **not AR** — different app + **different DB**; do not run AR OF01CAR / `AR_USER_18` as the ticket Pass path |

Say the product in the plan (“This is CR4PRA → Compliance Reporter, not AR”). If CR and you only have AR creds → plan CR steps + ask for CR env/DB, or verdict **CANNOT TELL** (wrong product access), not an AR Fail.

## Gate 0b — Xray / linked Test steps first (mandatory)

**Before inventing a plan**, open **Test Coverage** / linked **Test** issues (e.g. `AR4PRA-4121`) and read **Test Details → Manual Steps**.

1. Those steps are the **canonical plan** — copy them into `notes/plan.md` and follow them in order.
2. You may **add** extra steps afterward for stronger evidence (DB dropdown markers, Excel/PDF export compare, cyan-highlighted full screenshots, etc.) — label them **Extra (QA)** so they are clearly additive.
3. Do **not** replace or skip Xray steps with a plan “from your mind” only.
4. If there is **no** linked Test / empty steps → say so, then derive a plan from description + Dev evidence.

## Gate 0c — Explain + plan + wait (mandatory)

**Do not run UI/DB/API tests until the user confirms the plan** (unless they already said “full permission / just run it”).

In chat, before testing:

1. **Explain the ticket** in plain language: product (AR vs CR from key), what is broken/changed, which return/map/rule/STBITEM, fix version/build, what “done” looks like.
2. **Proposed test plan** (numbered): start with **Xray Manual Steps**, then any Extra (QA) steps.
3. Ask: **Confirm this plan (yes / change X)?**
4. Only after confirmation (or explicit skip) continue.

Save under `notes/ticket-explained.md`, `notes/plan.md`, and paste Xray steps into `notes/xray-<TEST-KEY>-steps.md`.

## Entry — branch by ticket type

After the plan is confirmed:

| Ticket needs… | Do this |
|---|---|
| UI / returns / validation | `ar-qa-browser-visible` — create/open return, run validation & cross-validation, export results, **full** screenshots with highlight of the rule/cell |
| DB vals, xvals, sums, rets, CFG_* | `ar-qa-db-readonly` — SELECT-only; **screenshot query+result**; every result → Excel |
| API / REST / swagger / Postman | `ar-qa-api-apidocs` — manual apidocs vs tool |
| Mixed | All needed branches; one evidence folder + Canvas |

Never invent DB rows or API responses. If creds or login are missing → **CANNOT TELL** and ask.

## Folder naming

From `https://jira.agilereporter.com/browse/AR4PRA-4002` → key **AR4PRA-4002**:

```text
C:\WORK\qa-evidence\AR4PRA-4002_QA_evidence\
C:\WORK\qa-evidence\AR4PRA-4002_QA_evidence.zip
```

### Subfolders

```text
<KEY>_QA_evidence/
  notes/           # ticket summary, env, plan, verdict draft
  comments/        # prior QA comments baseline
  attachments/     # ticket attachments
  screenshots/     # UI / apidocs / validation
  exports/         # Excel packs (query results, return exports)
  validation/      # AR Validation results
  sql/             # .sql + .json/.xlsx query evidence
  packs/           # prior vs this run
```

## Step 1 — Open and read the ticket

1. Open Jira (MCP if Cloud; else Cursor Browser for jira.agilereporter.com DC).
2. Record product, form/build, environment (e.g. QA AR `.18`).
3. Read description + linked SUPs until the fix is clear.
4. Note returns (OF07CRSA…), entity, labels, whether DB/API/UI checks are required.

## Step 2 — Prior QA evidence → mimic

1. Old QA comments (Pass/Fail, env, ReturnId, rule IDs).
2. Attachments (prior zip, validation Excel, SQL sheets).
3. Plan = same returns / ReturnIds / val-xval IDs / DB checks / validation paths.
4. Re-test those checks on the named env/build.
5. Compare to prior evidence.

No prior evidence → derive from description + Dev + defect packs; say so in `notes/`.

## Step 3 — DB when required (vals / xvals / sums / rets)

If the plan needs SQL:

1. Ask: **DB type**, host, database, username, password (chat is OK; never print password back).
2. Follow `ar-qa-db-readonly` — connect read-only, catalog, curry queries.
3. If user asks to **download results** → write Excel under `exports/` (and/or `sql/`).
4. No working login → **CANNOT TELL** for DB portion; continue UI/API if possible.

## Step 4 — API when required

1. Ask: **manual in AR apidocs (Cursor Browser)** or **Postman / API tool**.
2. Manual: open `{AR}/apidocs/`, navigate to the API, fill try-it params visibly; user may **Take control** anytime.
3. Tool: run equivalent requests; still narrate what is called; user can interrupt and finish in browser.
4. Report works / fails with status + evidence screenshots or response files.

## Step 5 — UI when required

`ar-qa-browser-visible`: permanent visible browser, slow type, action strip, screenshots. User watches or Take control.

## Step 6 — Verdict

| Result | Verdict |
|--------|---------|
| Must-change checks match expected fix (and prior Pass baseline if any); no unexpected neighbour breaks | **PASS** |
| Must-change mismatch or regression | **FAIL** |
| Wrong build/env, missing ReturnId, or cannot read vals/xvals/DB/API | **CANNOT TELL** — name the gap; do not Pass |

Empty validation screen alone ≠ Pass. Prefer CFG_RPT_Vals / CFG_RPT_XVals (+ Script type) plus live Validation and SQL.

## Step 7 — Evidence + Canvas

Capture screenshots, exports, validation, SQL/Excel. Update the QA Canvas board. Draft `notes/verdict-draft.md`.

## Step 8 — Full review in chat (mandatory before asking for Jira post)

Write a clear chat summary the user can read without opening files:

1. Ticket in one paragraph  
2. What was tested (checklist)  
3. Evidence produced (paths: screenshots, validation exports, SQL Excel)  
4. Match vs prior/Dev QA evidence (match / mismatch / not comparable)  
5. **PASS / FAIL / CANNOT TELL** and why  
6. Gaps / next steps if not Pass  

Also save as `notes/full-review.md`.

## Step 9 — User review (mandatory)

1. Give folder path.
2. Ask them to review evidence and confirm.
3. **Do not** post Jira until they approve comment/attach.

## Step 10 — Jira comment + attach

Only after go-ahead: Pass/Fail, env, product/build, returns/ReturnIds, short checklist, attach zip. No invented IDs. No passwords.

## Domain reminders

- ReturnId is numeric; return name ≠ Vals/XVals FK.
- Vals = CFG_RPT_Vals; XVals = CFG_RPT_XVals.
- Prefer Type = Script after Complex→Script fixes.
- Entity in Excel often **3999** for PRA.
- Data Criticals that prove a rule fires ≠ product Fail.

## Companions

- `ar-qa-browser-visible` · `ar-qa-db-readonly` · `ar-qa-api-apidocs`
- Canvas in workspace `canvases/` · prefer Cursor-native over hosted QA Studio

## Product desk

Team ticket-review pattern for AR QA. Formal `desk.qata` may still be TBD; still follow this when asked to test an AR ticket.
