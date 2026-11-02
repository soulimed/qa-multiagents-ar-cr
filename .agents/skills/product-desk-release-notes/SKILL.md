---
name: product-desk-release-notes
description: >
  Rela's release-notes desk for any product team. Checks whether a fix version
  is ready (open tickets, empty release-notes fields, release date, release
  ticket, Qata's verdicts), drafts the customer release notes for a fix version
  in the team's own entry format (title, intro, sections such as Problem and
  Solution, module headings), writes each note back into the tracker's
  release-notes field, exports Markdown / HTML / PDF / Word and a per-customer
  variant, and pushes the page body to the team's wiki after a page-title check.
  Everything team-specific (the tracker host and field ids, the fix-version
  pattern, the entry format, the authoring tactic and style guide, the wiki
  host and labels, the login files) comes from the team's desk settings,
  desk.rela.readiness and desk.rela.release_notes. Every write is a dry run
  until --apply, and only the team's configured hosts are used.
---

# Product desk release notes (Rela)

Rela (`release-rela`) turns the tickets of one fix version into the team's customer release notes, and checks first that the version is ready for them.
This skill is the execution path: the scripts, the publish plumbing and the step order.
The writing rules belong to the team: its authoring tactic (`desk.rela.release_notes.tactic`), style guide and worked example (`style_guide`, `worked_example`, asset ids in the team's packs).
Read them before drafting; they win over anything in this file.

`scripts/` is Python 3 with PyYAML, `requests` and, for Word export, `python-docx`.
`tools/` holds the PowerShell and Node tools the scripts call; they write next to their input, never into the skill folder.

## Is it set up for this team?

| Commands | Capability |
|---|---|
| `readiness.py` | `rela.readiness` (the board part also needs `clara.tickets`; without it the release ticket and customers are reported unknown) |
| `rn_export.py`, `rn_tools.py` | `rela.release_notes` |

When the capability is not on, the command prints its message ("not set up for this team -- ask Olga", with the onboarding section) and stops with exit code 3.
A setting the command needs and the team has not filled in is named in the message; nothing is guessed and nothing falls back to another team.
`selftest` runs without settings.

The settings file: `--settings <file>` anywhere on the command line, else `PRODUCT_DESK_SETTINGS`, else the lookup of `product-desk-capability`.

## What the settings carry

| Key | What it does |
|---|---|
| `tracker.instance` | The only tracker host; `tracker.read_only_archives` hosts are refused by name |
| `tracker.projects` | The development project (the fix version's tickets) and the support project (customer variant) |
| `tracker.fix_version_pattern` | The fix-version value, `{v}` the bare version |
| `tracker.fields.release_notes`, `.exclude_from_release_notes`, `.organizations` | Field ids on this instance |
| `desk.rela.readiness.release_ticket_project`, `.blocking` | Where the release ticket lives; blocking priorities (default: `desk.clara.tickets.blocking`) |
| `desk.rela.release_notes.title`, `section_heading`, `intro` | The page title (`{v}` the version), the heading above the entries, the line under it |
| `desk.rela.release_notes.wiki.page_title` | The wiki page's title when it differs from `title` (default: `title`) |
| `desk.rela.release_notes.sections`, `section_sources`, `group_by`, `module_headings`, `missing_evidence` | The entry format, and where each section's text comes from |
| `desk.rela.release_notes.done_statuses`, `exclude_value`, `output_file` (or `product_tag`) | The pull query's statuses, the exclude option, the file names |
| `desk.rela.release_notes.wiki.labels` | Labels every release-notes page carries |
| `desk.rela.release_notes.pdf_subtitle`, `pdf_footer` | The branded PDF's subtitle and footer |
| `desk.rela.release_notes.customer_variant` | `client_map` (a YAML file mapping support organizations to clients) and `client_lists` (dotted keys of its client lists, earlier wins) |
| `credentials.jira_release_notes`, `credentials.wiki`, `tracker.write_env_file` | The login files: field pull / push, wiki page check and push, read-only tracker search |

## Workflow

1. **Readiness.** `python scripts/readiness.py --version <X.Y.Z> [--qat <verdict files>] [--out ready.md]`.
   It reads, all read-only, the fix version's tickets with their release-notes and exclude fields, the version's release date, the release ticket and the customers per ticket from Clara's board, and Qata's verdict files (`verdict: PASS | FAIL | CANNOT TELL`, `run`, `commit`, `evidence`, optional `tickets:`).
   It prints READY or NOT READY with each blocker and its owner (the ticket assignee, `qa-qata` or release management); exit 3 means NOT READY.
2. **Pull.** `python scripts/rn_tools.py fields pull --version <X.Y.Z> [--with-commits] [--all-statuses]` writes `<tag>-<v>-tickets.json` (every field the drafter needs) and the seed `<tag>-<v>-rn.json`.
3. **Draft.** Start `output_file` from `rn_tools.py skeleton --version <v>`: the page title as the H1, the section heading in bold, then the intro.
   Draft each ticket in the team's entry format, from the sources `section_sources` names, following the team's tactic.
   When the evidence gives no real content for a section, write the team's `missing_evidence` text and list the ticket; never a note that only restates the title.
   Honour the exclude field, and list every excluded ticket with a reason, never dropped silently.
   Group the entries under the team's module headings and write `output_file`.
4. **Sign-off.** The Markdown is for human review first. Nothing below runs until the user says "publish" for that version.
5. **Write the notes into the tracker field.** Fill the `release_notes` strings in `<tag>-<v>-rn.json`, then `rn_tools.py fields push --version <v>` (dry run: review `<tag>-<v>-push-preview.md`), then the same with `--apply`.
   A field that already holds text is skipped unless `--overwrite`. Writing the field does not publish.
6. **Wiki page.** `rn_tools.py confluence --md <notes>.md` builds the storage body; `rn_tools.py wiki --page <id> --body <stem>.confluence.xml --version <v>` checks the page title names that version (exit 4 when it names another one; confirm the page id with the user), then shows the version bump and missing labels; `--apply` on the user's go-ahead.
   The page keeps its title; `--title auto` sets the team's page title for that version.
   `rn_tools.py paste --md <notes>.md` gives a copy for pasting into the editor instead; never paste the storage body into the editor.
7. **The portal**, when the team publishes there, is the release capability's step (`desk.rela.release`), with its own approvals.

## Exports

```powershell
python scripts/rn_export.py export  --md <notes>.md --format docx|html|pdf|md [--out DIR] [--apply]
python scripts/rn_export.py variant --md <notes>.md --customer "<customer>" [--apply]
python scripts/rn_tools.py pdf --md <notes>.md [--title "<title>"]
```

- **Variant** keeps the notes whose ticket is linked to a support case of that customer: the ticket's links to the support project, then the case's organization field, mapped to clients through `customer_variant.client_map`. The text is unchanged and names no customer; only the file name does. The internal / excluded section is dropped.
- **PDF / HTML** use `tools/make-pdf.ps1` and `tools/md-to-branded-html.mjs` with the branding of the doctrine-org pack (`SPEC_KITTY_PACK_HOME`), printed by headless Chrome or Edge.
- Every export is a dry run until `--apply`.

## Tools

| Tool | Called by | What it does |
|---|---|---|
| `tools/rn-fields.ps1` | `rn_tools.py fields` | Pull a fix version's tickets; push notes and the exclude flag into the tracker fields (REST, curl for the PUT); refuses any host but the configured one |
| `tools/wiki-push.ps1` | `rn_tools.py wiki` | PUT a storage body to a wiki page and ensure its labels |
| `tools/md-to-confluence.mjs`, `tools/md-to-plain-html.mjs` | `rn_tools.py confluence`, `paste` | Storage body for the REST API; rich HTML for pasting |
| `tools/make-pdf.ps1`, `tools/md-to-branded-html.mjs` | `rn_export.py export`, `rn_tools.py pdf` | Branded HTML and PDF |

`rn_tools.py --show <command>` prints the tool's command line with the team's values and runs nothing.

## Rules

- The team's tracker and wiki only; an archive is never a source or a target.
- Every write (tracker field, wiki page, export file) is a dry run until `--apply`, and `--apply` follows the user's go-ahead for that version.
- Never invent a regulatory citation, a setting value or a fix's behaviour beyond the ticket evidence.
- Never print a token. The login files are read, never shown.
- Customer names stay out of the note text.

## Tests

```powershell
python scripts/readiness.py selftest      # offline, invented names
python scripts/rn_export.py selftest
python tests/negative_test.py              # not set up -> ask Olga; refused hosts; no team facts
python tests/parity_test.py                # against the installed original, when there is one
```
