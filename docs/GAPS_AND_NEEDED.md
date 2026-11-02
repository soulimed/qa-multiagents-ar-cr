# What is missing / what must be added

## Maturity

**This project is not fully tested.** Many paths are brittle or env-specific. Expect failures on a new AR/CR host until gates and credentials are re-validated.

## Missing or weak today

| Gap | Detail |
|-----|--------|
| Cursor IDE Browser on every worker | Sometimes only headed desktop Chrome is available; must still stay open |
| Postman MCP OAuth | Sign-in link often missing; Desktop import required |
| Create/delete return API recipes | Create needs Available dates; DELETE not in Return OpenAPI |
| Olga onboarding completeness | `product-desk.yaml` may still be TBD |
| Automatic RDP to remote VMs | **Not implemented** — connect via Remote Desktop, keep session visible |
| Configure Compliance Reporter | **Not implemented** — agent cannot yet configure CR end-to-end |
| Full Compliance Reporter feature understanding | **Not implemented** — need deep coverage of all CR features (setup, reports, workflows, privileges) |
| Deep Agile Reporter “complex return” reasoning | Partial (lock/lookup/gates); not full vals/xvals/edition intelligence |
| Auto-push without token | Needs `repo` PAT or working GCM login for unattended push |
| Full evidence in git | Large screenshots stay under `C:\WORK\qa-evidence\` (by design) |

## Needed next (user-requested — must add)

1. **Connect to remote VMs through Remote Desktop** — agent opens / drives an RDP session to the target Windows VM, keeps that desktop visible so you can review the workflow on the remote machine (same rule as local browser: never hide or close mid-run).  
2. **Configure Compliance Reporter** — teach and automate CR configuration (env/product setup paths agents need for real CR QA, not only AR).  
3. **Understand all Compliance Reporter features** — full domain model of CR: every major feature, screens, privileges, and how UI maps to APIs/jobs so Qata (and desk) can reason about CR like a specialist, not smoke-only.  
4. **Hardening** — browser never closed; Canvas always updated; stop-and-ask on form/date blockers; sync teachings to GitHub automatically.  
5. **Stable Postman path** — fix MCP auth or standardize Desktop + CI Newman with working cookie jar.  
6. **DB profile pack** — documented read-only profiles per env without secrets in git.

## How to track progress

Update this file when a gap is closed. Repo auto-sync rule should commit those updates.
