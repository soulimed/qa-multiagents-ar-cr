# Push to GitHub (`soulimed`)

Local commit is ready on branch `main` in this folder.

**Blocked:** Git Credential Manager has a `gho_` token for `soulimed` that returns **401** on the GitHub API, so this agent cannot create the remote repo. Device login was canceled.

## Option A — you create the empty repo (fastest)

1. Open https://github.com/new  
2. Owner: **soulimed**  
3. Repository name: **`qa-multiagents-ar-cr`**  
4. Public (or Private), **without** README/gitignore (repo is already committed locally)  
5. Tell the agent “repo created” — or run:

```powershell
cd "C:\WORK\QA_MultiAgents for AR &CR"
git remote remove origin 2>$null
git remote add origin https://github.com/soulimed/qa-multiagents-ar-cr.git
git push -u origin main
```

(Sign in when Git Credential Manager prompts; use a PAT with `repo` if asked.)

## Option B — PAT with `repo` scope

1. https://github.com/settings/tokens → classic token with **`repo`**  
2. Paste the token to the agent (or store it in GCM) and ask to push again.

## What will be on GitHub

- Product desk agents (Olga/Clara/Qata/Rela) + rules  
- AR QA skills (visible browser, API, DB read-only, ticket evidence)  
- Spec Kitty / spk skills present in the project  
- Postman collection (no passwords)  
- Full docs under `docs/`  

**Not included:** passwords, `.env`, `local_secrets.json`, large `qa-evidence` binaries.
