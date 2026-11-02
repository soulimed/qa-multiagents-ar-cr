# Team knowledge sync — how it really works

Short answer: **yes, teammates can share the same agent knowledge through this GitHub repo — but only if teachings are written into files and pushed/pulled with git.** The model does **not** permanently “memorize” chat into itself for the whole company.

## What the agent remembers vs what the team shares

| Where | Shared with Regnology colleagues? | Survives new chat / new PC? |
|-------|-----------------------------------|-----------------------------|
| Chat history in one Cursor session | No | No (session-local) |
| Files in this repo (skills, rules, docs, Postman) | **Yes** — after push + their pull | **Yes** |
| Fine-tuned / retrained LLM weights | Not used here | N/A |

“Training” in this project means: **teach → agent updates skills/rules/docs → commit → push.**  
It does **not** mean uploading weights to GitHub.

## Does the repo update each time you add a feature or teach?

**Intended yes**, by rule — not by magic background daemon.

1. You teach or add a feature in Cursor.  
2. The agent **must** persist it under this project (`docs/`, `.agents/skills/`, `.cursor/rules/`, `postman/`, …).  
3. The agent runs `scripts/sync-to-github.ps1` (or git push) when credentials allow.  
4. GitHub `soulimed/qa-multiagents-ar-cr` gets the new commit.

Enforced by:

- Rule: `.cursor/rules/repo-auto-sync.mdc`  
- Skill: `.agents/skills/qa-repo-auto-sync/`  
- Doc: [REPO_AUTO_UPDATE.md](REPO_AUTO_UPDATE.md)

If the agent only answers in chat and **does not write files + push**, that knowledge is **not** in the repo and **colleagues will not get it**.

## Can a Regnology colleague clone, install, teach, and share back?

**Yes — bidirectional — if everyone uses the same GitHub repo and git write/read access.**

```text
You teach ──► files in your clone ──► push ──► GitHub
                                              │
Colleague pull ◄──────────────────────────────┘
     │
     ▼
Their Cursor agents load updated skills/rules/docs
     │
They teach ──► files ──► push ──► GitHub ──► you pull ──► your agents
```

### Their setup (once)

1. Clone https://github.com/soulimed/qa-multiagents-ar-cr  
2. Open that folder in Cursor (so `.cursor/agents`, `.cursor/rules`, `.agents/skills` load).  
3. Install / enable the same MCPs/plugins listed in [FEATURES_FULL.md](FEATURES_FULL.md) as needed.  
4. Use a GitHub account with **push** access (collaborator) or open PRs.  
5. Set auth for push (GCM or `GITHUB_TOKEN` with `repo` scope) — never commit the token.

### Day-to-day (both directions)

| You / they | Action |
|------------|--------|
| Start of day | `git pull` so local agents see latest team knowledge |
| After teaching | Agent writes files → `.\scripts\sync-to-github.ps1` → push |
| Conflict | Resolve merge like any shared repo, then push |

**You get their knowledge** after you **pull**.  
**They get yours** after they **pull**.  
GitHub is the shared brain; each machine must sync.

## What automatically updates vs what does not

**Updates the shared project (when the workflow is followed):**

- New or corrected skills (e.g. keep browser open)  
- Rules, gotchas, FEATURES / GAPS docs  
- Postman collections, scripts, agent desk configs in-repo  

**Does not auto-update alone:**

- Chat-only answers never written to disk  
- Secrets / passwords / PATs (blocked on purpose)  
- Local evidence under `C:\WORK\qa-evidence\` (by design)  
- Other clones until someone runs `git pull`  
- Cursor cloud chat memory outside this repo  

## Practical limits

1. **Discipline** — auto-sync is an agent rule; if push fails (no token), knowledge stays local until auth works.  
2. **Access** — colleagues need clone + preferably write access (or PR workflow).  
3. **Pull** — cloning once is not enough; keep pulling.  
4. **No silent model training** — knowledge is text/files the next agent session reads.  
5. **License** — Regnology-only; see [LICENSE](../LICENSE).

## Bottom line

| Question | Answer |
|----------|--------|
| Can the repo update when I add features / teach? | **Yes**, if the agent writes files and pushes (rule + script). |
| Does the agent memorize everything forever by itself? | **No** — only what is stored in repo files (plus local chat). |
| Can colleagues install and share the same knowledge? | **Yes** — clone, use Cursor on this repo, teach → push; others pull. |
| Bidirectional (them → you and you → them)? | **Yes**, via GitHub as the single source of truth. |
