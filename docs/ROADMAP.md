# Roadmap

## Near term

- Stabilize visible-browser automation (IDE browser MCP vs headed desktop).  
- Reliable Postman path (Desktop import; fix MCP OAuth where possible).  
- Create/delete return API recipes with Available-date gates.  
- Stronger Canvas templates for ticket + API + DB runs.  
- Complete Olga onboarding so `product-desk.yaml` is not TBD.

## Requested next capabilities

### 1. Remote Desktop to remote VM

Allow the agent workflow to connect to a **remote Windows VM via Remote Desktop**, keep that session visible for supervision (same rule as local browser: do not hide work), and run AR / tools there when the target env is not local.

### 2. Understand complex reporter

Improve domain understanding of **Agile Reporter** complex returns: multi-page forms, editions, validation / cross-validation, locks, submit, entity/group privileges, and how UI state maps to REST (`returnId`, jobs, statuses) — so Qata can reason about non-trivial reporter scenarios, not only smoke tests.

## Maturity statement

**This project is not fully tested yet and needs a lot of improvement.**  
Treat it as an evolving Cursor + doctrine-product + AR QA toolkit. Validate on each environment before relying on results.
