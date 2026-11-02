# QA MultiAgents for AR & CR

Cursor multi-agent toolkit for **Agile Reporter (AR)** and **CR** QA, built on Regnology’s **doctrine-product** product desk and extended with visible-browser, Canvas, read-only DB, and API testing skills.

> **Status:** Not fully tested end-to-end. Needs substantial improvement. Use as a starting kit; validate on your environment.

## Upstream base

Product desk agents and install model come from:

**[RAF / doctrine-product](https://bitbucket.regnology.net/projects/RAF/repos/doctrine-product/browse)**  
(branch used for install: `team/agile-reporter`)

| Agent | Profile | Role |
|-------|---------|------|
| Olga | `onboarding-olga` | Onboarding interview → pack/settings |
| Clara | `clerk-clara` | Tickets |
| Qata | `qa-qata` | QA / evidence |
| Rela | `release-rela` | Release notes & readiness |

## What we added for AR QA

- **Visible browser that stays open** — user can watch and correct (`ar-qa-browser-visible`).  
- **Live Canvas** — step-by-step QA board beside chat.  
- **Read-only DB query** — SELECT against existing env DB; no infra changes (`ar-qa-db-readonly`).  
- **API testing** — AR apidocs + Postman collections (`ar-qa-api-apidocs`).  
- Cursor-native rule preferring Canvas/skills/browser over a hosted Studio SPA.

## Quick start

1. Clone this repo and open it in Cursor.  
2. Follow [docs/INSTALL.md](docs/INSTALL.md) (doctrine-product wiring + local secrets).  
3. Say **`Hey Qata`** for AR QA, or **`Hey Olga`** for desk onboarding.  
4. Keep browser + Canvas visible during runs.

## Documentation

| Doc | Content |
|-----|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Desk base + AR extensions |
| [docs/CAPABILITIES.md](docs/CAPABILITIES.md) | What works / what doesn’t |
| [docs/AGENTS_AND_SKILLS.md](docs/AGENTS_AND_SKILLS.md) | Inventory |
| [docs/INSTALL.md](docs/INSTALL.md) | Setup |
| [docs/ROADMAP.md](docs/ROADMAP.md) | RDP + complex reporter + maturity |

## Repo layout

```
.cursor/agents/          Olga, Clara, Qata, Rela, desk
.cursor/rules/           greetings, auto-route, AR QA native
.agents/skills/          desk + AR QA + Spec Kitty skills
product-desk/            desk settings (fill via Olga)
postman/                 sample AR API collections (no secrets)
docs/                    full documentation
```

## Security

Do **not** commit passwords, `.env`, or `local_secrets.json`. Redact evidence.

## Roadmap highlights

- Connect to remote VMs via **Remote Desktop** while keeping the session visible.  
- Teach agents to **understand complex Agile Reporter** returns (pages, vals/xvals, workflows).  

See [docs/ROADMAP.md](docs/ROADMAP.md).

## License / ownership

Internal Regnology / personal working copy for Mohamed Souli (`soulimed`). Respect doctrine-product and company IP rules when sharing outside the team.
