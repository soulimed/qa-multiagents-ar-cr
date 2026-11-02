---
name: product-desk-auto-route
description: >-
  Route to Olga, Clara, Qata, or Rela from message context when the user does
  not say Hey <name>. Use on any product-desk request, test-this-ticket, Jira
  URL, release notes, or setup ask without an explicit agent greeting.
---

# Product desk auto-route

Follow workspace rule `product-desk-auto-route`. Summary:

| Intent | Agent |
|---|---|
| Test / QA / retest + ticket | **Qata** |
| Find / create / who’s on ticket | **Clara** (user may type Carla) |
| Release notes / ship | **Rela** |
| Desk setup / onboarding | **Olga** |

Announce once (`Qata — testing this ticket.`), load matching skills, stay until intent shifts or explicit `Hey <other>` / `bye`.
