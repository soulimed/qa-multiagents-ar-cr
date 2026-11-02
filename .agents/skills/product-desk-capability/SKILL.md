---
name: product-desk-capability
description: >
  Says whether one desk capability is set up for this team, and returns the
  team's own settings for it when it is. Clara, Qata and Rela carry no team's
  way of working: how a team handles tickets, does QAT, cuts a release and
  writes release notes lives in its product-desk.yaml under desk.clara,
  desk.qata and desk.rela, one block per capability with status on, off or
  TBD. Only on switches a capability on (Clara's tickets is on by default once
  the tracker is set up, unless off); anything else is answered "not set
  up for <product> -- ask Olga", with the onboarding section that sets it up.
  Use before any capability's work, in a team skill before it reads its
  settings, and at the end of Olga's interview to show what is now on.
  Its settings_review.py lists every current setting of a team already set
  up, with where each value comes from and whether it is still open, for
  Olga's review mode; secrets show only as stored or not stored.
---

# Product desk capability

The gate every desk agent and team skill asks first.
`scripts/capability.py` is Python 3 with the standard library, plus PyYAML to
read the desk settings.

## The capabilities

| Agent | Capability | Needs before it counts as on | Onboarding section |
|---|---|---|---|
| Clara | `tickets` | on by default once `tracker.instance`, `tracker.read_tools` and `tracker.projects` are set; `status: off` wins | `tracker`, then `clara-tickets` to switch off or add rules |
| Clara | `lookup` | `skill`, `command` | `clara-tickets` |
| Clara | `branch_check` | `repos` | `clara-tickets` |
| Qata | `qat` | `process`, `results.location` | `qata-qat` |
| Qata | `fix_verification` | `method`, and `qat` on | `qata-qat` |
| Rela | `readiness` | `blockers` | `rela-release` |
| Rela | `release` | `skill`, `profiles_file`, `steps`, `approver` | `rela-release` |
| Rela | `release_notes` | `source_jql`, `sections`, `format` | `rela-release-notes` |
| Rela | `announcement` | `channel` | `rela-release` |
| Rela | `documentation` | `skill` | `rela-release` |

The agent may be named by key (`qata`), profile id (`qa-qata`) or name (`Qata`).

## Commands

```powershell
python scripts/capability.py check --agent rela --capability release_notes   # exit 0 on, 3 not set up
python scripts/capability.py check --agent qata --capability qat --json      # the team's block, or why not
python scripts/capability.py list                                            # every capability of the desk
python scripts/capability.py selftest
```

`--settings <file>` names the settings file; otherwise `PRODUCT_DESK_SETTINGS`,
then the lookup of toolguide `product-desk-settings` (`PRODUCT_DESK_HOME`, the
project's `product-desk/`, the registered packs' `product-desk/`, through skill
`product-desk-consult` when it is installed beside this one).
With several products, `--product <product.id>` picks one.

## The answers

| State | Means | The agent says |
|---|---|---|
| `on` | status on and every needed value answered -- or Clara's `tickets` with no status and the tracker set up | nothing extra; it works from the returned block |
| `off` | the team said it does not use it | it is off for this product; if that changed, ask Olga |
| `not-set-up` | TBD, a missing block, or a capability it builds on is not on; for Clara's `tickets`, the tracker keys still TBD | not set up yet; ask Olga, section named |
| `incomplete` | on, but a needed value is still TBD | which value; ask Olga, section named |
| `unresolved` | on and complete, but its `skill` or `tactic` is not in the pack chain | which name is missing; install or register its pack, or ask Olga |
| `agent-off` | `desk.agents.<profile>` is off | the agent is off for this product |
| `old-schema` | a `1.0` file with no `desk.<agent>` block | not set up; ask Olga to move it to the per-agent shape |
| `no-settings` | no settings file found | not set up; ask Olga to run the interview |

Only `on` and `incomplete` carry settings, and only this team's own block, so
nothing downstream can run on another team's values by accident.

## Bound names must resolve

A capability's `skill` and `tactic` (`none` binds nothing) must exist, not only be named.
`check` and `list` look each one up in the pack chain of the settings file:
its own pack, the packs it extends (`extends` in each `org-charter.yaml`),
the packs under `extensions.packs`, the packs registered in the project's
`.kittify/config.yaml`, then doctrine-product.
A skill is a folder `skills/<name>/` or `skills/<group>/<name>/` with a
`SKILL.md` in one of those repositories, or installed beside this skill; a
tactic is `pack/tactics/<name>.tactic.yaml`.
A name found nowhere answers `unresolved` and the capability does not run.
In code, `resolve(doc, agent, capability, source)` runs the same check when
`source` is the settings file; pass `roots=` to name the repositories
yourself.

## In a team skill

A team skill (for example a product pack's QAT or release-notes skill) reads
its values from the block this returns, not from its own defaults:

```python
ans = capability.resolve(doc, "rela", "release_notes")
if not ans.on:
    raise SystemExit(ans.message)
jql = ans.settings["source_jql"]
```

## Reviewing a team's current settings

Olga's review mode (procedure `product-desk-onboarding`) reads a team's
current values instead of asking every question again.
`scripts/settings_review.py` collects them into one table, in the
interview's section order:

```powershell
python scripts/settings_review.py show --project <folder holding .kittify>             # the whole review table
python scripts/settings_review.py show --section qata-qat --json                       # one section, for an agent
python scripts/settings_review.py set --settings <file> --key product.owners.product_owner --value "<name>"  # dry run: the diff
python scripts/settings_review.py set ... --apply                                      # after the user's go-ahead
python scripts/settings_review.py selftest
```

Each row has the setting, its current value, where it comes from and its state.
The sources are the settings file, the template (a key the file lacks), the
environment variables the settings name (`*_env` keys, `$NAME` and `~` paths),
the database hosts file (`database_server.hosts_file`, else the user-level copy
`~/.regnology/<server>/`, else `--db-hosts`), Credential Manager target names
(per database target when `database_server.credential_target` gives the
pattern), the credential files `credentials` names, and the project's
`.kittify/config.yaml`.
A row is `open` when its value is TBD, `partial`, missing from the file, a
variable that is not set, or a login that is not stored.
A key that names a password, token or secret, or a value shaped like one, is
shown only as `stored` or `not stored`.

`set` writes one confirmed correction back where the value came from: `--settings`
for a settings key (one scalar or inline value, comments kept, read back before
writing), `--env-file` for a user-local env file such as the hosts file, and
`--user-env` for a user environment variable.
It refuses a secret, a customer name in a settings file (`--customer-names`
or `PRODUCT_DESK_CUSTOMER_NAMES`), a value inside a list or a block, and an
env file that git tracks.
Without `--apply` it only prints the diff.

## Self-test

`settings_review.py selftest` runs offline on a synthetic team: secrets in the
hosts and credential files never reach the table or the JSON, TBD, partial and
missing settings are open, and `set` keeps comments and refuses each case above.

`capability.py selftest` runs offline on synthetic settings: on, off, TBD, incomplete,
missing block, a `1.0` file, no settings, an agent switched off, a capability
whose dependency is off, unknown names, a bound skill or tactic that resolves
nowhere, and a blank team that must borrow nothing.
`tests/negative_test.py` adds the same unresolved case end to end, through
`check` on a settings file in a temporary pack chain. For Clara's `tickets`: on by default with the tracker set up (no
status, TBD, no block), not set up with a tracker key missing, off when the
team wrote off, and agent-off over the default. It also checks the template `pack/templates/product-desk/
product-desk.template.yaml` has a block and every needed key for each
capability, and switches nothing on.
