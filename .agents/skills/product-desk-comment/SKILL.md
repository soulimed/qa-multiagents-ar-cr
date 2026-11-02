---
name: product-desk-comment
description: >
  Writes a desk agent's Jira Cloud comment in that agent's own voice: its
  opener, an executive summary in an info panel, the full analysis folded in
  one collapsed section, and its sign-off. Who is speaking, the Jira host, the
  login file and the ticket keys shown as smart links all come from the
  product's desk settings (product-desk.yaml), so Clara, Qata, Rela and the
  product's specialist share one helper. Dry run by default; writes only with
  --post, through REST, and reads the comment back. Use when an agent posts or
  updates an analysis comment on a ticket.
---

# Product desk comment

One helper for every desk agent's ticket comment.
`scripts/desk_comment.py` is Python 3 with the standard library, plus PyYAML to
read the desk settings.
It is the general form of the RA LQR hub's `lena_comment.py`: same layout, same
checks, with the agent's words read from the settings instead of written into
the script.

## The comment

The analysis is Markdown with two sections:

```markdown
## Executive summary
- one line per finding, with the action it needs (1 to 5 lines)

## Full analysis
...headings, paragraphs, lists, tables, code blocks, > notes...
```

The comment is the agent's opener, the executive summary in an info panel, one
collapsed section holding the full analysis, and the agent's sign-off.
A Jira expand cannot hold another expand, so the full analysis uses headings for
its own structure.
An opener or sign-off line the author typed into the Markdown is dropped, so it
never appears twice.
The skill refuses an empty or over-long summary (more than 5 lines), a missing
section, a two-line title and a comment over 30,000 characters.

## Where the agent's words come from

`product-desk.yaml`, the `comment:` block of the agent under `extensions`, on top
of the shared `extensions.all.comment` (template `product-desk.template.yaml`):

| Key | Used for | When unset |
|---|---|---|
| `name` | how the agent names itself; also helps drop a typed sign-off | the profile id |
| `opener` | first line of the comment | the skill refuses |
| `sign_off` | last line, in italics | the skill refuses |
| `card_projects` | ticket keys shown as smart links | every `tracker.projects` key |

From the rest of the settings: the Jira host is `tracker.instance`, the login
file is `tracker.write_env_file` (relative to `~/GIT`), and `tracker.markup`
must be `cloud-markdown`.
An agent with no `comment:` block cannot post: fill it during onboarding rather
than letting the helper invent a greeting.

The settings file is found as in toolguide `product-desk-settings`:
`--settings`, else `PRODUCT_DESK_SETTINGS`, else `PRODUCT_DESK_HOME`, else
`<project>/product-desk/`, else the `product-desk/` folder beside each product
pack registered in `<project>/.kittify/config.yaml`.
`--product <id>` picks one when several are found.

## Commands

```powershell
cd <doctrine-product>\skills\desk\product-desk-comment\scripts

python desk_comment.py identity --agent demo-specialist          # who would speak, from which settings
python desk_comment.py render --agent demo-specialist --in analysis.md --out body.json
python desk_comment.py post --agent demo-specialist --in analysis.md --key <KEY>          # dry run
python desk_comment.py post --agent demo-specialist --in analysis.md --key <KEY> --post   # writes
python desk_comment.py post ... --key <KEY> --replace <comment id> --post                 # edits one
python desk_comment.py selftest
```

`--agent` takes the profile id or the `comment.name` (`Dora`); `PRODUCT_DESK_AGENT`
sets a default.
`--title` names the collapsed section (default `Full analysis`).

## Writing

- **Dry run by default.** `post` prints the preview and writes nothing without
  `--post` (`--apply` is the same flag, as in `lena_comment.py`).
- **REST only**, never an MCP write tool: Jira Cloud REST v3, to the settings'
  host and nowhere else; any other host is refused.
- **Credentials** come from `JIRA_API_URL` / `JIRA_API_EMAIL` / `JIRA_API_TOKEN`,
  else the env file named in the settings (or `--env-file`). They stay in
  variables and are never printed.
- **Read-back:** after a write the comment is read back and checked for the
  collapsed section, the summary and the sign-off; a mismatch exits 2.

## Tests

```powershell
python scripts\desk_comment.py selftest   # offline, synthetic settings and analysis
python tests\parity_test.py               # against the installed lena_comment.py
```

`parity_test.py` runs the original `lena_comment.py` in place (read-only, no
bytecode written, its SHA-256 checked before and after) and this copy on the
same synthetic analyses, with the RA LQR desk settings and with a synthetic file
holding the original's constants.
Render output, ADF body, dry-run output and refusals must match; the only
allowed difference is the dry-run hint naming `--post`.
Clara, Qata and Rela from the RA LQR settings must give the same output with
their own opener and sign-off in place of Lena's, and their own smart-link
projects; an agent without a `comment:` block must be refused.
It never posts, removes `JIRA_API_*` from the children's environment, and is
skipped with a message when the original is not installed.
