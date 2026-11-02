# What is missing / what must be added

## Maturity

**This project is not fully tested.** Many paths are brittle or env-specific. Expect failures on a new AR host until gates and credentials are re-validated.

## Missing or weak today

| Gap | Detail |
|-----|--------|
| Cursor IDE Browser on every worker | Sometimes only headed desktop Chrome is available; must still stay open |
| Postman MCP OAuth | Sign-in link often missing; Desktop import required |
| Create/delete return API recipes | Create needs Available dates; DELETE not in Return OpenAPI |
| Olga onboarding completeness | `product-desk.yaml` may still be TBD |
| Automatic RDP | Not implemented yet |
| Deep “complex reporter” reasoning | Partial (lock/lookup/gates); not full vals/xvals/edition intelligence |
| Auto-push without token | Needs `repo` PAT or working GCM login for unattended push |
| Full evidence in git | Large screenshots stay under `C:\WORK\qa-evidence\` (by design) |

## Needed next (user-requested)

1. **Remote Desktop to remote VM** — agent connects via RDP, keeps session visible so you can review workflow on the remote machine.  
2. **Understand complex reporter** — multi-page returns, editions, validation/cross-validation, privileges/groups, mapping UI ↔ REST jobs/statuses.  
3. **Hardening** — browser never closed; Canvas always updated; stop-and-ask on form/date blockers; sync teachings to GitHub automatically.  
4. **Stable Postman path** — fix MCP auth or standardize Desktop + CI Newman with working cookie jar.  
5. **DB profile pack** — documented read-only profiles per env without secrets in git.

## How to track progress

Update this file when a gap is closed. Repo auto-sync rule should commit those updates.
