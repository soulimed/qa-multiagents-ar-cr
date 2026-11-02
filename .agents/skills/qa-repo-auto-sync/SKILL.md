---
name: qa-repo-auto-sync
description: >-
  After the user teaches or corrects AR/QA multi-agent behavior, update repo
  docs/skills/rules and push to github.com/soulimed/qa-multiagents-ar-cr.
  Use when finishing a teaching turn, adding MCP/plugin usage, or changing
  browser/canvas/API/SQL workflow.
---

# QA repo auto-sync

## Steps

1. Apply the teaching to the right skill/rule/doc (often `ar-qa-browser-visible`, gotchas, `docs/FEATURES_FULL.md`).
2. `cd` to `C:\WORK\QA_MultiAgents for AR &CR`.
3. Run:

```powershell
.\scripts\sync-to-github.ps1 -Message "<short conventional message>"
```

4. Report push result + https://github.com/soulimed/qa-multiagents-ar-cr

## Auth

Prefer existing git remotes + GCM. Else `$env:GITHUB_TOKEN` with `repo` scope for the push only — do not write the token into the repo.
