# QA MultiAgents for AR & CR

Cursor multi-agent project for **Agile Reporter (AR)** and **CR** QA.

**GitHub:** https://github.com/soulimed/qa-multiagents-ar-cr  

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
| [docs/ROADMAP.md](docs/ROADMAP.md) | Near-term roadmap |

---

## Teach the agent → GitHub updates

Corrections and new capabilities must be written into this repo and pushed:

```powershell
.\scripts\sync-to-github.ps1 -Message "docs: your teaching summary"
```

Rule: `.cursor/rules/repo-auto-sync.mdc` · Skill: `qa-repo-auto-sync`.

---

## Roadmap (explicit)

- Connect to **remote VM via Remote Desktop** and keep that session visible for review.  
- Teach agents to **understand complex Agile Reporter** (pages, vals/xvals, editions, workflows).  

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
