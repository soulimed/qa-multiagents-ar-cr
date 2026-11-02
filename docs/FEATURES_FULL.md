# Full feature catalog — agents, skills, MCP, plugins

This is the **complete inventory** of what this project includes for Agile Reporter (AR) / CR QA multi-agents.  
Base desk comes from [RAF/doctrine-product](https://bitbucket.regnology.net/projects/RAF/repos/doctrine-product/browse). Everything under **AR QA extensions** was added for Mohamed’s workflow.

---

## 1. Supervision surfaces (must stay visible)

### 1.1 Browser stays open (mandatory)

**Skill:** `ar-qa-browser-visible`  
**Rule:** `.cursor/rules/ar-qa-cursor-native.mdc`

**Why it exists:** So **you** can review the agent workflow live — not trust a silent shell.

| Rule | Behavior |
|------|----------|
| Open / focus browser before UI work | Cursor IDE Browser (`cursor-ide-browser` MCP) with visible focus, **or** headed desktop Chrome/Chromium if IDE browser MCP is missing |
| **Never close mid-run** | Tab/window stays open for the whole ticket/API session so you can watch, Take control, or correct |
| Slow type | Username/password/filters typed slowly when supported |
| Narrate | Short lines: OPEN / TYPE / CLICK / SEE / FAIL |
| Screenshots | Full viewport evidence under `C:\WORK\qa-evidence\...` |
| Action strip | Same steps mirrored on **Canvas** + `notes/browser-actions.md` |

If the agent closes the browser or works headless-only for UI claims → that is a **defect** against this project’s doctrine (also in `C:\WORK\qa-evidence\_agent_gotchas.md`).

### 1.2 Live Canvas

**Tooling:** Cursor Canvas (`WriteCanvas` / `cursor/canvas`)

Beside chat, a durable board shows:

- Current step  
- Scenario params (entity, form, date, endpoints)  
- Pass / fail pills  
- Action strip (same as browser narration)  
- Blockers (e.g. form version missing, MCP auth)

You use Canvas to **review** what the agent thinks it is doing without reading the whole transcript.

### 1.3 Evidence packs

Machine-local (not always in git): `C:\WORK\qa-evidence\<KEY>_QA_evidence\`  
Screenshots, redacted JSON, Postman/Newman/local runner outputs, gate findings.

---

## 2. Product desk agents (doctrine-product base)

| Agent | File | Greeting | Job |
|-------|------|----------|-----|
| Olga | `.cursor/agents/onboarding-olga.md` | `Hey Olga` | Onboard desk settings |
| Clara | `.cursor/agents/clerk-clara.md` | `Hey Clara` | Tickets |
| Qata | `.cursor/agents/qa-qata.md` | `Hey Qata` | QA / test evidence |
| Rela | `.cursor/agents/release-rela.md` | `Hey Rela` | Release notes / readiness |
| Desk router | `.cursor/agents/desk.md` | multi-name | Route multi-agent asks |

**Rules:** `product-desk-invocation.mdc`, `product-desk-auto-route.mdc` (unlabeled “test this ticket” → Qata).

**Desk skills:** `product-desk-consult`, `product-desk-comment`, `product-desk-capability`, `product-desk-tickets`, `product-desk-release-notes`, `product-desk-auto-route`.

---

## 3. AR QA skills (added for this project)

| Skill | What it does |
|-------|----------------|
| **`ar-qa-browser-visible`** | Visible browser, keep open, narrate, screenshot, Canvas strip |
| **`ar-qa-api-apidocs`** | Test AR REST via apidocs Try-it and/or Postman/HTTP; capture status/body redacted |
| **`ar-qa-db-readonly`** | Connect to env SQL Server; **SELECT-only**; never change infra or write data |
| **`ar-qa-ticket-evidence`** | Ticket → plan → UI/DB/API evidence pack + verdict draft |
| `product-desk-auto-route` | Route product-desk intents without `Hey <name>` |

Also on the machine (user skills): `jira-qa-review-agent`, `job-match-finder` (not AR-core).

---

## 4. Spec Kitty / spk skills (governance)

Large set under `.agents/skills/` (`spec-kitty-*`, `spk-*`, `ad-hoc-profile-load`, `adversarial-squad`) for missions, charter, gates, team sync. They support Spec Kitty workflows layered with the desk; see skill map `spk-meta-skill-map`.

---

## 5. MCP servers & plugins used here

| MCP / plugin | Role in this project |
|--------------|----------------------|
| **`user-regnology-mcp` / regnology-mcp** | Jira Cloud, Bitbucket (doctrine-product, PRs), Confluence |
| **`cursor-ide-browser`** | Official Cursor Browser tiles (preferred for visible AR UI) |
| **Postman plugin** (`plugin-postman-postman`) | Drive Postman collections when OAuth works |
| **Atlassian** (plugin) | Alternate Jira/Confluence when configured |
| **Regnology Disco / Juno** | Optional Regnology MCP (auth may be required) |
| **regnology-hello** | Sample marketplace plugin |
| **cursor-subscriptions / cursor-cloud** | Subscriptions / cloud-agent diagnostics when available |

**Known MCP pain:** Postman MCP may fail with *“No sign-in link is available for this MCP server”* — fall back to Postman Desktop + collection in `postman/`, or local session runner. IDE browser MCP may be missing on some workers — fall back to headed desktop browser **still kept open**.

---

## 6. API testing features

- Swagger discovery: `/agilereporter/apidocs/` → Return / Job / IDAM / Product / Settings.  
- REST base: `/agilereporter/rest/`.  
- Auth: `j_security_check` → `JSESSIONID`.  
- Lookup return: `GET /api/v1/returns?prefix&entityCode&formCode&formVersion&referenceDate`.  
- Lock: `PUT /api/v1/returns/{returnId}/lock` (proven on returnId 2947).  
- Create: `POST /api/v1/returns/retrieve` (job-based; needs available form version + open reporting date).  
- Collection: `postman/CRGB-v10-lock-return.postman_collection.json`.  
- **Gates before create:** latest version, user/entity access, Available dates — stop and ask the user (gotcha).

---

## 7. SQL / DB features

- Skill `ar-qa-db-readonly` + helper scripts.  
- Credentials from user / env / local secrets — **never committed**.  
- Read-only connection intent; reject writes.  
- Results saved under qa-evidence.  
- **Does not change** AR or DB infrastructure.

---

## 8. Repo auto-update (teach → git)

When you teach a correction or add a capability, the agent must:

1. Update the matching skill/rule/doc (and `_agent_gotchas.md` if behavioral).  
2. Commit under this repo.  
3. Push to `https://github.com/soulimed/qa-multiagents-ar-cr`.

See `docs/REPO_AUTO_UPDATE.md` and rule `.cursor/rules/repo-auto-sync.mdc`.
