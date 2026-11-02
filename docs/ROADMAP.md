# Roadmap

## Near term

- Stabilize visible-browser automation (IDE browser MCP vs headed desktop).  
- Reliable Postman path (Desktop import; fix MCP OAuth where possible).  
- Create/delete return API recipes with Available-date gates.  
- Stronger Canvas templates for ticket + API + DB runs.  
- Complete Olga onboarding so `product-desk.yaml` is not TBD.

## Requested next capabilities (must add)

### 1. Remote Desktop to remote VMs

Allow the agent workflow to **connect to remote Windows VMs through Remote Desktop**, keep that session visible for supervision (same rule as local browser: do not hide work), and run AR / CR / tools there when the target env is not local.

### 2. Configure Compliance Reporter

Add the ability for agents to **configure Compliance Reporter (CR)** — guided and/or automated setup of CR so QA can prepare an environment without guessing menus and privileges.

### 3. Understand all Compliance Reporter features

Build deep agent knowledge of **every major Compliance Reporter feature** (configuration, reporting flows, privileges, UI ↔ API mapping) so the desk can test and explain CR end-to-end, not only smoke paths.

### 4. (Related) Complex Agile Reporter returns

Continue improving AR domain understanding: multi-page forms, editions, validation / cross-validation, locks, submit, entity/group privileges, and REST job/status mapping.

## Maturity statement

**This project is not fully tested yet and needs a lot of improvement.**  
Treat it as an evolving Cursor + doctrine-product + AR/CR QA toolkit. Validate on each environment before relying on results.

## License

This repository is **Regnology-only** proprietary material. See [LICENSE](../LICENSE).
