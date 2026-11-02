---
name: product-desk-tickets
description: >
  Clara's ticket desk for any product team. Finds tickets by customer, by
  release (fix version, release date and release ticket, open and blocking
  tickets), by product class, rule or report cell, or by topic (template
  family, regulation, function); groups related tickets and proposes links;
  lists duplicates, stale tickets, hygiene gaps, "what changed for customer X
  in release Y" and a weekly digest; counts and splits any JQL across every
  result page, each ticket once; and checks whether a ticket (or a fix
  version's tickets) is on each release line of the team's repos. Everything
  team-specific (the board export, priorities, done statuses, template
  families, the topic sources, the repos and their release lines, the tracker
  host) comes from the team's desk settings, desk.clara.tickets and
  desk.clara.branch_check. Reads a local board export and local git clones;
  read-only against the tracker.
---

# Product desk tickets (Clara)

Clara (`clerk-clara`) answers ticket questions from the team's ticket board export.
This skill reads the export and never rebuilds it; the team's own refresh command (`desk.clara.tickets.data.refresh`) does that.
`scripts/ticket_desk.py` is Python 3 with the standard library, plus PyYAML for the settings and `requests` for the read-only tracker calls.

## Is it set up for this team?

Every command first asks skill `product-desk-capability` whether the team switched the capability on:

| Commands | Capability |
|---|---|
| `customer`, `release`, `cell`, `topic`, `group`, `dupes`, `stale`, `hygiene`, `changed`, `digest`, `search` | `clara.tickets` |
| `branches` | `clara.branch_check` (and `clara.tickets` too with `--release`) |

When it is not on, the command prints the capability's message ("not set up for this team -- ask Olga", with the onboarding section) and stops with exit code 3.
Nothing is read from another team, and nothing falls back to a built-in team.

The settings file: `--settings <file>` anywhere on the command line, else `PRODUCT_DESK_SETTINGS`, else the lookup of `product-desk-capability`.
`--product <id>` picks one product when several have settings.

## What the settings carry

`desk.clara.tickets`:

| Key | What it does |
|---|---|
| `data` | The board export: `format: po-board`, `folder` (one path or a list of candidates; the first whose `$VARIABLES` are all set wins; a relative path is under `~/GIT`), `dry_run` (a JSON export used when it is newer than the first customer page), `sections` (`id`, `kind` customer / internal / roadmap, `page`, `const`), `refresh` (named in the "no data" message) |
| `blocking`, `blocking_label` | Priorities counted as blocking, and how the release line names them |
| `done_statuses` | Statuses that close a ticket |
| `excluded_projects` | Tracker projects left out of every answer |
| `stale_after_days`, `duplicate_similarity` | Defaults of `stale --days` and `dupes --threshold` |
| `separate_lines` | Words that mark a separate product line in a version name; a version with the word matches only when the question names it |
| `template_families` | Regexes tried in order; `label` is a template with `{0}` the match, `{1}`.. its groups, `{first}` its first letter (default: the match upper-cased) |
| `term_patterns` | A family term searched loosely on the board: `term` regex, `search` regex template (`{1}`.. the term's groups) |
| `title_prefixes` | Product prefixes stripped before the duplicate comparison (bracketed tags are always stripped) |
| `grouping` | `link_families` (which cluster names may get link proposals), `max_members`, `skip_versions` |
| `topic` | `taxonomy` (asset id or path of a Markdown file with a families table), `taxonomy_section`, `template_code` and `code_term` (search terms from the template codes), `functions` (asset id or path of a JSON function catalogue) |
| `cell_lookup` | The class / rule / cell lookup: `skill` + `script` in this repo (or `path`), extra `args`, a `fields` map when its JSON names differ |
| `watch_list`, `digest_title` | The digest's default watch list and title |

An asset id resolves through its sidecar in the team's own product pack, then `extensions.packs`, then this repo's pack.

`desk.clara.branch_check`: `products` (short name -> `repo` id in `code.repos`, `name`, and `branches: resolve` or `default` for a repo read per run; a product with no `branches` and no release lines whose repo says `develop_branch: origin/HEAD` or `default` is read per run too), `clone_url` (`{project}` and `{slug}`, lower-cased).
`code.repos` gives each repo's `clone_env`, `project`, `slug` and `release_lines`; the default clone is `~/GIT/<slug>`.

The tracker comes from `tracker`: `instance` (the only host the client talks to), `write_env_file` (the login file; `JIRA_API_URL`, `JIRA_API_EMAIL`, `JIRA_API_TOKEN` in the environment win), the `projects` with role development or support (the text search), and `fix_version_pattern` (shortened in the branch table).

## Fresh data first

Run the team's refresh command (`desk.clara.tickets.data.refresh`) in the board folder.
The export holds customer data. It stays on this machine.

## Commands

All in `scripts/ticket_desk.py`:

| Question | Command |
|---|---|
| What does customer X have open? | `customer "<customer>" [--release <version>]` |
| What is in release V, when does it ship, what blocks it? | `release <version> [--jira]` |
| Which tickets involve this cell, class or rule? | `cell "<REPORT>\|<ROW>\|<COL>"` · `cell <CLASS>` · `cell <rule-id>` |
| Which tickets are about this topic? | `topic "<family, regulation or function>"` |
| Which tickets belong together? | `group [--board <section>\|all] [--jira]` |
| Which tickets look like duplicates? | `dupes [--threshold T]` |
| What has been open too long? | `stale [--days N]` |
| Which tickets are missing fields or links? | `hygiene` |
| What changed for customer X in release Y? | `changed --customer <name> --release <version>` |
| Weekly digest and watch list | `digest [--since 7] [--watch <file>]` |
| Is this ticket on each release line? | `branches <KEY> [--jira] [--fetch]` |
| Which tickets of a fix version or JQL are on which branch? | `branches --release <version>` · `branches --jql "<JQL>"` |
| How many tickets match, and how do they split? | `search --jql "<JQL>" [--by status\|priority\|fixVersion\|label\|assignee\|project] [--count]` |

`--jira` adds read-only tracker calls: text search for `cell` and `topic`, existing issue links for `group`, and the release ticket's links for `release`.
The client refuses any host other than the one in `tracker.instance`, and has no write call.

### Searches and counts: `search`, never one MCP page

Answer every tracker list or count ("which open tickets carry label X", "how many are in progress", "split them by status") with `ticket_desk.py search`, not with a single MCP search call.
An MCP search returns one result page, so a count from it stops at the page size without saying so.
`search` reads every result page (`nextPageToken`, or `startAt` + `total`), keeps each issue key once, and prints TRUNCATED when `--limit` (1000) stops it.
A JQL without `ORDER BY` is read in key order, so no ticket moves between pages while they are read.
`--by` puts each ticket in exactly one group: a ticket with two fix versions or labels counts once, under the combined value, so the groups add up to the total it prints.
Never add up the results of several searches (one per status, say) to get a total; one search with `--by` gives the split.
The `--jira` text search of `cell` and `topic` reads every page the same way, up to 500.

### How the lookups work

- **Customer** comes only from the board's client field. A customer is never inferred from a ticket title.
- **Release**: the date and the release ticket come from the board's roadmap section. A release without a date says so; no date is estimated.
- **Cell, class or rule** goes through the team's `cell_lookup`, then the classes, rule ids and template family are searched on the board and, with `--jira`, in the development and support projects.
- **Topic** is matched against the team's families table and function catalogue.
- **Grouping** clusters tickets that share a support case, or a template family in the same fix version.
  - Link proposals come only from clusters whose name matches `grouping.link_families`, with at most `max_members` tickets, in a planned release.
  - With `--jira`, pairs that are already linked are left out.
  - A proposal is a list for the user. A link is created only on the user's go-ahead, and not by this script.
- **Dupes** compares titles after stripping bracketed tags and the team's `title_prefixes`.

### Branch check (`branches`, in `scripts/branch_check.py`)

A ticket is on a branch when a commit reachable from that branch names its key anywhere in the subject or body.
That also catches cherry-picks and merge-forward commits that repeat the key.
It is evidence that work landed, not proof the change is complete; a commit that forgot the key is not found.

- One ticket prints each branch with the commits found. Several tickets print a table (`--detail` gives the per-ticket list); `--md` / `--json` also write it to a file.
- `--fetch` runs `git fetch` in each clone first. Without it the output states when each clone was last fetched.
- A repo that isn't cloned, or a branch that isn't there, shows as `?` (not checked), never as "not on the branch". The message gives the clone command.
- A product read per run (`branches: resolve` / `default`, or `develop_branch: origin/HEAD` / `default`): the default develop branch comes from the clone's `origin/HEAD` (`--fetch` refreshes it), else the newest `develop/*`; a newer `develop/*` than the default is named in a note and not checked; the newest `release/*` is the second column.
- When a ticket is missing from a checked branch, the detail view lists other remote branches that carry it, so an unmerged fix shows.
- `--jql` pages through the tracker up to `--limit` (500) and says TRUNCATED when it stops early.
- Branch names can name customers. Keep the output local.

## Rules

- The team's tracker only; archives are not sources.
- Never invent a customer, a date or a link.
- The output names customers. Keep it local: don't paste it into shared pages without the user's say-so.
- Nothing here writes to the tracker. Link creation, a comment or a field change is a separate step on the user's go-ahead.

## Tests

```powershell
python scripts/ticket_desk.py --settings none selftest   # offline, invented names
python tests/negative_test.py                            # not set up -> ask Olga; no borrowing; no team facts
python tests/parity_test.py                              # against the installed original, when there is one
```
