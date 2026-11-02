# Install / setup

## Prerequisites

- Cursor IDE on Windows  
- Access to AR environments (example used in QA: `http://10.98.54.18:8080/agilereporter/`)  
- Optional: Spec Kitty pack home with doctrine-product (`SPEC_KITTY_PACK_HOME`)  
- Optional: `regnology-mcp` (Jira / Bitbucket / Confluence)  
- Credentials stored **locally** (never commit): env files, password manager, or QA Studio `local_secrets.json`

## Clone

```powershell
git clone https://github.com/soulimed/qa-multiagents-ar-cr.git
cd qa-multiagents-ar-cr
```

Open the folder in Cursor.

## Doctrine-product pack (base agents)

If you have Bitbucket access to [RAF/doctrine-product](https://bitbucket.regnology.net/projects/RAF/repos/doctrine-product/browse):

1. Clone or extract doctrine-product (branch `team/agile-reporter` or current team branch).  
2. Point `SPEC_KITTY_PACK_HOME` at the parent that contains `doctrine-product`.  
3. Run configure + Cursor wiring (from doctrine-product setup scripts), for example:

```powershell
$env:SPEC_KITTY_PACK_HOME = 'C:\code\.regnology'   # your path
python "$env:SPEC_KITTY_PACK_HOME\doctrine-product\skills\setup\regulatory-pack-setup\scripts\configure_pc.py" --project (Get-Location) --init-desk
python "$env:SPEC_KITTY_PACK_HOME\doctrine-product\skills\setup\regulatory-pack-setup\scripts\install_cursor_wiring.py" --project (Get-Location) --apply
```

This project already mirrors agents/rules/skills under `.cursor/` and `.agents/skills/` for AR QA + desk.

## First run

1. **`Hey Olga`** if `product-desk.yaml` is still TBD.  
2. For AR QA: **`Hey Qata`** or “test this ticket” (auto-routes to Qata).  
3. Keep browser/canvas visible; do not invent secrets.

## Postman

Import `postman/CRGB-v10-lock-return.postman_collection.json` into **Postman Desktop**.  
Set `username` / `password` / `baseUrl` as collection variables locally (not in git).

## Security

- Never commit `.env`, `local_secrets.json`, or real passwords.  
- Redact tokens/cookies/passwords in evidence and reports.
