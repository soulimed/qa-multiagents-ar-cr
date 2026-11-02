---
name: ar-qa-db-readonly
description: >-
  Read-only AR/SQL Server curry for QA: read a Jira ticket, connect to the named
  env DB, introspect schema, write SELECT-only queries, save results under
  qa-evidence. Never INSERT/UPDATE/DELETE/DDL. Use when Qata or the user asks
  for DB checks, vals/xvals, ReturnId lookup, or ticket-driven SQL for AR/AR4PRA.
---

# AR QA DB read-only curry

Curries inside the DB for the agent so the user does not open SSMS and paste SQL.
**Hard rule: READ-ONLY. Never write.**

## When to use

- Ticket mentions vals, xvals, rules, ReturnId, CFG_*, sums, reconciliations
- User asks to "check DB", "query vals", "confirm ReturnId", "compare CFG"
- After `ar-qa-ticket-evidence` Step 2 when prior QA used SQL sheets

## Inputs (ask only if missing)

When the user says “test this ticket” and DB checks are needed, **ask clearly**:

1. **DB type** (SQL Server / Oracle / Postgres / …)
2. **Host**, **port** (if not default), **database/schema**
3. **Username** + **password** in chat (or env vars) — **never print passwords back**
4. Optional ticket key / ReturnId / what to curry (vals, xvals, sums, rets)

Also accept env vars or `C:\WORK\QA_studio\data\local_secrets.json` key `db` when already set.

### Default QA `.18` map (override if user names another env)

| Field | Default |
|-------|---------|
| Host | `10.98.54.17` |
| Database | user/env named (often owner DB for `.18`) |
| Auth | SQL login; password = username unless user says otherwise |
| Intent | `ApplicationIntent=ReadOnly` |

Prefer connection from:

- `QA_DB_HOST`, `QA_DB_NAME`, `QA_DB_USER`, `QA_DB_PASSWORD`, optional `QA_DB_PORT`
- or `C:\WORK\QA_studio\data\local_secrets.json` key `db` if present
- or values the user pastes this session (do not write them into skills)

## Forbidden SQL

Reject and rewrite if the statement contains (case-insensitive):

`INSERT`, `UPDATE`, `DELETE`, `MERGE`, `TRUNCATE`, `DROP`, `ALTER`, `CREATE`,
`EXEC`, `EXECUTE`, `xp_`, `sp_`, `GRANT`, `REVOKE`, `INTO` (select-into), `OPENROWSET`,
`BULK`, `BACKUP`, `RESTORE`, `DBCC` (except harmless read diagnostics if user insists — prefer skip).

Only allow statements that start with `SELECT` or `WITH` (CTE ending in `SELECT`).
Always `SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED` or connection `ApplicationIntent=ReadOnly`.

## Workflow

### 1 — Ticket → query intent

From Jira (MCP `jira_cloud_get_issue` or browser):

- Return names (OF08CRIR, …), entity, form version
- ValId / XValId / rule IDs from description + prior QA comments/attachments
- ReturnId if cited; else plan a lookup by return name after schema inspect

Write intent into `C:\WORK\qa-evidence\<KEY>_QA_evidence\notes\db-intent.md`.

### 2 — Connect read-only

Run the helper (prefer over ad-hoc one-liners):

```text
python C:\Users\MohamedSouli\.cursor\skills\ar-qa-db-readonly\scripts\readonly_sql.py --ping
python ...\readonly_sql.py --catalog --like CFG_RPT%
python ...\readonly_sql.py --sql "SELECT ..." --out <evidence>\sql\result.json
```

If helper fails (no ODBC / network), stop with **CANNOT TELL** and name the blocker — do not invent rows.

### 3 — Schema curry

1. List tables matching ticket nouns (`CFG_RPT_Vals`, `CFG_RPT_XVals`, return tables).
2. Describe columns for each needed table.
3. Tell the user (briefly) what you found; put catalog snippet under `sql/schema-notes.md`.

### 4 — Curry queries

Build **small, ticket-scoped** SELECTs. Prefer:

```sql
-- ReturnId lookup (example pattern — adjust names after catalog)
SELECT TOP 50 ReturnId, ReturnName, Version
FROM dbo.<ReturnsTable>
WHERE ReturnName LIKE '%OF08%';

SELECT TOP 200 ReturnId, ValId, Type, LEFT(Formula, 200) AS FormulaPreview
FROM dbo.CFG_RPT_Vals
WHERE ReturnId = @ReturnId
ORDER BY ValId;

SELECT TOP 200 ReturnId, XValId, LEFT(Formula, 200) AS FormulaPreview
FROM dbo.CFG_RPT_XVals
WHERE ReturnId = @ReturnId
ORDER BY XValId;
```

Save every executed statement as `sql/NN-description.sql` and results as `sql/NN-description.json` or `.csv`.

### 5 — Evidence for every query (mandatory)

For **each** ticket-scoped query:

1. Save `sql/NN-name.sql` (exact statement).
2. Run it; save results Excel: `exports/NN-name.xlsx` (and optional `.json`).
3. **Screenshot** that makes the query and result clear (SSMS/Azure Data Studio/tool showing SQL + grid, or clear Canvas/table capture). Prefer full window.
4. Name files so a human can match SQL ↔ Excel ↔ screenshot (`04-vals-CAORR680C010.sql` / `.xlsx` / `.png`).

```text
python ...\readonly_sql.py --sql "SELECT ..." --excel <evidence>\exports\NN-name.xlsx --out <evidence>\sql\NN-name.json
```

### 6 — Canvas + chat

- Summarize row counts and Pass/Fail contribution on the QA Canvas board.
- Never dump huge result sets in chat — sample + path to evidence file.

## Safety checklist (every run)

- [ ] Connection uses ReadOnly intent
- [ ] SQL passed guard (SELECT/WITH only)
- [ ] No password in chat, canvas, or evidence notes
- [ ] Evidence under `C:\WORK\qa-evidence\<KEY>_QA_evidence\sql\`
- [ ] Verdict impact stated (supports PASS / FAIL / CANNOT TELL)

## Relation to other skills

- Use **with** `ar-qa-ticket-evidence` (DB is Step 4 evidence).
- UI steps use `ar-qa-browser-visible`.
- Do not replace formal desk gates; this is the method for DB curry inside Cursor.
