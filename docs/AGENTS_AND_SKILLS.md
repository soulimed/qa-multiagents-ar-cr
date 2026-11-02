# Agents and skills inventory

## Desk agents (from doctrine-product)

Profiles live in doctrine-product `pack/agent_profiles/` and are wired here as Cursor subagents:

- `.cursor/agents/onboarding-olga.md`
- `.cursor/agents/clerk-clara.md`
- `.cursor/agents/qa-qata.md`
- `.cursor/agents/release-rela.md`
- `.cursor/agents/desk.md` (router)

Rules:

- `.cursor/rules/product-desk-invocation.mdc` — `Hey Olga|Clara|Qata|Rela`
- `.cursor/rules/product-desk-auto-route.mdc`
- `.cursor/rules/ar-qa-cursor-native.mdc`
- `.cursor/rules/spec-kitty.mdc` (if present)

## AR QA skills (project additions)

Under `.agents/skills/` (and user skills mirror):

| Skill | When to use |
|-------|-------------|
| `ar-qa-browser-visible` | Any AR UI/apidocs automation — visible browser, keep open |
| `ar-qa-api-apidocs` | REST/Swagger/Postman for AR |
| `ar-qa-db-readonly` | Read-only SQL against env DB |
| `ar-qa-ticket-evidence` | Full ticket QA evidence pack |
| `product-desk-auto-route` | Route unlabeled product-desk intents |

## Spec Kitty / spk skills

The repo may also contain Spec Kitty mission/admin skills (`spk-*`, `spec-kitty-*`) for governance workflows. They come from Spec Kitty / doctrine tooling and support missions, charter, and gates — complementary to the product desk.

## Reference

Upstream doctrine documentation and pack layout:  
https://bitbucket.regnology.net/projects/RAF/repos/doctrine-product/browse
