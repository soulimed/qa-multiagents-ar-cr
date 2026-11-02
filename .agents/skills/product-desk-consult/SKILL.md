---
name: product-desk-consult
description: >
  The consult contract between product desk agents -- Clara (tickets), Qata
  (quality), Rela (releases) and the product's optional specialist named in
  product-desk.yaml (any agent: a domain specialist such as liquidity-lena, a
  team's own agent, or none). Use when one agent needs another's answer, in
  either direction: how to phrase the request, how to answer, how to start the
  peer as a background subagent, and how to save the exchange as a local
  handoff file so it survives a dropped run. Works for any product team
  onboarded with product-desk-onboarding, regulatory or not.
---

# Product desk consult

One agent asks, another answers, and both halves are saved.
Doctrine: tactic `product-desk-consult-contract`; this skill is its helper.

## Who is on the desk

`python scripts/handoff.py agents` prints the list and where each entry came from:

| Agent | Answers about |
|---|---|
| `clerk-clara` | Tickets: history, customer, release, branch presence |
| `qa-qata` | Test runs: what moved, is it noise, is a fix verified |
| `release-rela` | Releases: content, readiness, notes, publish |
| the specialist (`desk.specialist.profile_id` in `product-desk.yaml`, optional) | The product's domain: which layer owns a behaviour, what a rule, standard or regulation requires |
| `desk` | The router, when one message names several agents |
| `user` | Anything only a person can decide |

`PRODUCT_DESK_AGENTS` (comma-separated profile ids) adds agents a settings file does not name.

## When to consult whom

| From | To | Typical question |
|---|---|---|
| Qata | specialist | Why did this value move? Which layer owns it? Which rule or article? |
| Clara | specialist | What does this ticket touch when it names no rule, class or cell? |
| Rela | Qata | Is each ticket in this fix version verified? |
| Rela | Clara | Which tickets are in this release, or for this customer? |
| Rela | specialist | This ticket has no usable solution text -- what did it change? |
| specialist | Clara | What is the ticket history on this rule or cell? |
| specialist | Qata | Prove this fix in the next run. |
| specialist | Rela | Which release carries this fix, and is it ready? |

The routing runs both ways.
The desk agents reach the specialist by the id in `desk.specialist.profile_id`, so they never hard-code one.
The specialist reaches Clara, Qata and Rela by their fixed ids, whichever pack the specialist comes from.
A specialist does not need to know the desk is there: this skill and the settings file are the whole contract.

**No specialist.** When `desk.specialist.profile_id` is `none` or `TBD`, the rows with "specialist" fall away.
A question that needs diagnosis goes to `user` as an open question, with the evidence gathered so far.
Clara, Qata and Rela still consult each other as usual.

## The request

| Field | Content |
|---|---|
| `id` | Short id; the helper generates `<hhmmss>-<from>-<to>` from the last part of each profile id |
| `from`, `to` | Desk agent ids |
| `product` | Optional product id, when the desk serves more than one product |
| `question` | One question, answerable on its own |
| `inputs` | Ticket keys, cells, classes, rule ids, run id, fix version |
| `evidence_so_far` | What the asker already checked, so the peer does not redo it |
| `expected_output` | The shape of answer wanted |

## The answer

| Field | Content |
|---|---|
| `answer` | The finding, in plain words |
| `evidence_cited` | Where it comes from: pack artifact, ticket, commit, run, cell |
| `confidence` | `confirmed` (evidence settles it), `likely` (strong but indirect), `unknown` |
| `owner` | Who owns the next step |
| `open_questions` | What is still open; **required** when `confidence` is `unknown` |

An `unknown` answer goes back to the user as an open question.
The asker never turns it into a guess.

## How to run a consult in Cursor

1. Save the request: `python scripts/handoff.py new --from qa-qata --to <specialist id> --question "…" --inputs-file inputs.yaml` (from PowerShell, `--inputs-file` avoids JSON quoting trouble).
2. Start the peer through the Task tool by its profile id, in the background when you have other work. Paste the request block into its prompt and ask for an answer in the answer shape.
3. Keep working. When the answer arrives, save it: `python scripts/handoff.py answer <id> --answer "…" --confidence likely --owner <agent> …`.
4. Merge it into your own result and cite the handoff id.

If a background run dies, `python scripts/handoff.py list --open` shows what is still waiting; restart the peer with the saved request.

## Rules

- **A consulted agent does not write.** It answers; it never writes to the tracker, wiki, CI, artifact store or a file outside the handoff folder.
  The **front** agent the user is talking to may write, after a dry run and the user's explicit go-ahead (tactic `product-desk-shared-conduct`).
  Never invent a "read-only agent" refusal for a front-agent write the user asked for.
- **One level of fan-out.** A consulted agent does not start its own consult; it returns what it needs as `open_questions`.
- **No secrets.** The helper refuses anything shaped like a password, token or connection string.
- **Local only.** The handoff folder is gitignored, because a handoff may name customers.

## Handoff folder

`PRODUCT_DESK_HANDOFFS`, else `<PRODUCT_DESK_HOME>/handoffs`, else `<project>/product-desk/handoffs`.
The project is the nearest folder above the current one that holds `.kittify/`.
The folder is never inside a pack repository (a registered pack's `local_path` folder, or any folder holding `pack/org-charter.yaml`), even when the settings come from one.
When the chosen folder lies in one, explicit or not, the script uses `<project>/product-desk/handoffs` instead and prints a one-line notice.
When the project itself is a pack repository, the script refuses and writes nothing; run the desk from a separate project folder (`configure_pc.py --project <folder> [--init-desk]`).

The settings themselves are found as toolguide `product-desk-settings` says: `PRODUCT_DESK_HOME`, the project's `product-desk/`, then the `product-desk/` folder of each product pack in the project's `.kittify/config.yaml`.

```powershell
python scripts/handoff.py agents
python scripts/handoff.py list --open
python scripts/handoff.py show <id>
python scripts/handoff.py validate <id>
python scripts/handoff.py selftest
```

Needs PyYAML.
