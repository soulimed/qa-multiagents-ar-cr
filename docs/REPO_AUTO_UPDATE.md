# Keep GitHub updated when you teach the agent

**Remote:** https://github.com/soulimed/qa-multiagents-ar-cr  

## Rule for every agent in this project

After any of the following:

- User corrects workflow (e.g. “keep browser open”, gate before create)  
- New skill / rule / MCP usage pattern  
- New Postman collection or doc  
- Gap closed or roadmap item started  

the agent **must**:

1. Write the change into the repo (`docs/`, `.agents/skills/`, `.cursor/rules/`, `postman/`, gotchas mirrored under `docs/gotchas/` if needed).  
2. Run `scripts/sync-to-github.ps1` (or equivalent git add/commit/push).  
3. Confirm the GitHub URL + commit in chat.

## Script

```powershell
cd "C:\WORK\QA_MultiAgents for AR &CR"
.\scripts\sync-to-github.ps1 -Message "docs: teach browser-open + canvas sync"
```

Auth: Git Credential Manager, or env `GITHUB_TOKEN` / `GH_TOKEN` with `repo` scope.  
**Never** commit the token.

## Cursor rule

`.cursor/rules/repo-auto-sync.mdc` — alwaysApply so agents do not “forget” to push teachings.

## Team / bidirectional

See **[TEAM_KNOWLEDGE_SYNC.md](TEAM_KNOWLEDGE_SYNC.md)** — how Regnology colleagues clone, teach, push, and how your agent picks up their knowledge (and vice versa).
