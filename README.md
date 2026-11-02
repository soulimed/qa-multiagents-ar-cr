# QA MultiAgents for AR & CR

Cursor multi-agent project for **Agile Reporter (AR)** and **Compliance Reporter (CR)** QA.

**GitHub:** https://github.com/soulimed/qa-multiagents-ar-cr  

**License:** [LICENSE](LICENSE) — **proprietary, Regnology only.** All rights reserved. Not open source; use only for Regnology work.

> **Not fully tested.** Needs a lot of improvement. See [docs/GAPS_AND_NEEDED.md](docs/GAPS_AND_NEEDED.md).

---

## What you review live (do not skip)

### 1. Browser stays open

Skill **`ar-qa-browser-visible`**. The agent opens AR / apidocs in a **visible** browser and **must not close it** while working so **you can review the workflow**, Take control, or correct mistakes. Silent curl-only is **not** a UI test.

### 2. Canvas

A **live Canvas** beside chat shows current step, endpoints, pass/fail, and the same OPEN/TYPE/CLICK/SEE action strip as the browser.

### 3. API testing

Skill **`ar-qa-api-apidocs`** + Postman collections under `postman/`. Session login → lookup `returnId` → lock/create/etc. against `/agilereporter/rest/...`.

### 4. SQL (read-only)

Skill **`ar-qa-db-readonly`**. Query the env DB with **SELECT only**. No infra changes, no writes.

### 5. MCP / plugins

Regnology MCP (Jira/Bitbucket/Confluence), Cursor IDE Browser, Postman plugin, optional Atlassian / Disco / Juno. Full list: [docs/FEATURES_FULL.md](docs/FEATURES_FULL.md).

---

## Base agents (doctrine-product)

From [RAF/doctrine-product](https://bitbucket.regnology.net/projects/RAF/repos/doctrine-product/browse):

| Say | Agent |
|-----|--------|
| Hey Olga | Onboarding |
| Hey Clara | Tickets |
| Hey Qata | QA |
| Hey Rela | Release |

---

## Documentation map

| Doc | Purpose |
|-----|---------|
| **[docs/FEATURES_FULL.md](docs/FEATURES_FULL.md)** | **Complete** agents, skills, MCP, plugins, browser/Canvas/API/SQL |
| **[docs/GAPS_AND_NEEDED.md](docs/GAPS_AND_NEEDED.md)** | What is missing + what to add (RDP, complex reporter, …) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How layers fit |
| [docs/INSTALL.md](docs/INSTALL.md) | Setup |
| [docs/REPO_AUTO_UPDATE.md](docs/REPO_AUTO_UPDATE.md) | Teach → commit → push to GitHub |
| **[docs/TEAM_KNOWLEDGE_SYNC.md](docs/TEAM_KNOWLEDGE_SYNC.md)** | **Team share:** clone / teach / push / pull — what syncs both ways |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Near-term roadmap |

---

## Teach the agent → GitHub updates

Corrections and new capabilities must be written into this repo and pushed:

```powershell
.\scripts\sync-to-github.ps1 -Message "docs: your teaching summary"
```

Rule: `.cursor/rules/repo-auto-sync.mdc` · Skill: `qa-repo-auto-sync`.

---

## Must add next (explicit)

1. **Remote Desktop to remote VMs** — connect via RDP, keep the remote session visible so you can review the workflow.  
2. **Configure Compliance Reporter** — agents can set up / configure CR for QA.  
3. **Understand all Compliance Reporter features** — full CR domain knowledge (not smoke-only).  
4. Continue deepening **complex Agile Reporter** returns (pages, vals/xvals, editions, workflows).  

Details: [docs/GAPS_AND_NEEDED.md](docs/GAPS_AND_NEEDED.md) · [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Layout

```
.cursor/agents/     Olga Clara Qata Rela desk
.cursor/rules/      greetings, AR native, repo auto-sync
.agents/skills/     AR QA + desk + Spec Kitty + qa-repo-auto-sync
postman/            API collections (no secrets)
docs/               full documentation
scripts/            sync-to-github.ps1
product-desk/       desk settings
```

**Never commit passwords or tokens.**
