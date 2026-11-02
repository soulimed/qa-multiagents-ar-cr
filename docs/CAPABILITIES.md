# Capabilities

## Working today (with caveats)

### Product desk agents (doctrine-product base)

- **Olga / Clara / Qata / Rela** greetings and Cursor subagent wiring.  
- Consult handoffs between desk agents.  
- Desk settings file (`product-desk/product-desk.yaml`) — may still contain TBD until Olga onboarding is finished.

### Visible browser workflow

- Open AR (login, dashboard, return editor, apidocs).  
- Keep the browser **open** for the whole run so the user can learn or correct.  
- Narrate steps on Canvas + `notes/browser-actions.md`.  
- Prefer Cursor IDE browser when MCP is attached; otherwise headed Chromium/Chrome on the machine (e.g. Try Live / desktop).

### Canvas supervision

- Live React canvas beside chat: current step, endpoints, pass/fail, action strip.  
- Updated as gates and API results land.

### Database (read-only)

- Skill `ar-qa-db-readonly`: connect to the named env SQL Server using credentials already on the machine.  
- **SELECT / WITH only** — reject INSERT/UPDATE/DELETE/DDL.  
- Does **not** change DB infrastructure or AR deploy topology.

### API testing

- Discover endpoints from AR apidocs / Return swagger (`/agilereporter/rest/...`).  
- Session auth via `j_security_check` + `JSESSIONID`.  
- Proven example: resolve `returnId` then `PUT .../returns/{id}/lock`.  
- Postman collection checked in under `postman/` for desktop import.  
- Gate before create: latest form version, user/entity availability, open reporting dates.

### Evidence & reporting

- Machine evidence under `C:\WORK\qa-evidence\<KEY>_QA_evidence\`.  
- Example full report style: create/lock/Postman findings with secrets redacted.

## Explicitly not ready / needs improvement

This project is **not fully tested end-to-end**. Expect gaps, brittle UI selectors, and environment-specific failures. Treat every new env as a fresh validation.

Known gaps from recent AR API work:

- Create/delete return APIs need valid form version + Available reporting dates; wrong dates fail at job level.  
- Return OpenAPI may not expose DELETE — confirm path before claiming delete coverage.  
- Postman MCP OAuth may fail (`No sign-in link`) on some Cursor workers — use Postman Desktop or local runner.  
- Cursor IDE browser MCP may be missing on private workers — fall back to headed desktop browser and keep it open.

## Roadmap (requested next)

| Item | Intent |
|------|--------|
| **Remote Desktop to remote VM** | Drive / observe AR (or tools) on a remote Windows VM via RDP from the agent workflow, with the same “keep session visible” rule |
| **Understand complex reporter** | Deeper AR / Agile Reporter domain understanding (multi-page returns, editions, validations, cross-vals, workflows) so agents reason about complex returns, not only smoke API/UI |

Also desirable: harden Postman MCP auth, stabilize browser automation, expand delete/create API recipes, richer QA Studio / Canvas templates.
