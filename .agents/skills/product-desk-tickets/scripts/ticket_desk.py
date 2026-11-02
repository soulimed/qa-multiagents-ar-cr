#!/usr/bin/env python3
"""Clara's ticket desk: read the team's ticket board and answer ticket questions.

  ticket_desk.py customer <name> [--release V]
  ticket_desk.py release <version> [--jira]         # tickets, date, release ticket, open + blocking
  ticket_desk.py cell <REPORT|ROW|COL | CLASS | rule-id> [--jira]
  ticket_desk.py topic <text> [--jira]              # template family, regulation, function
  ticket_desk.py group [--board <section>|all] [--jira]   # clusters + proposed links (never created)
  ticket_desk.py dupes [--threshold T]
  ticket_desk.py stale [--days N]
  ticket_desk.py hygiene
  ticket_desk.py changed --customer <name> --release <version>
  ticket_desk.py digest [--since 7] [--watch <file>]
  ticket_desk.py branches <KEY ...> | --release V | --jql "<JQL>"  [--fetch] [--jira] [--products a,b]
                                                  # is the change on each release line?
  ticket_desk.py search --jql "<JQL>" [--by status|priority|fixVersion|label|assignee|project] [--count]
                                                  # every result page, each key once; groups add up
  ticket_desk.py selftest

Everything team-specific is in the team's desk settings, desk.clara.tickets
(the board export and its sections, blocking priorities, done statuses, the
template families, title prefixes, the topic sources, the cell lookup) and
desk.clara.branch_check. A capability that is not on is refused with the
gate's message. --settings <file> and --product <id> may stand anywhere.

Data: the local board export named in desk.clara.tickets.data (format
po-board). --data <file> overrides. Refresh it first with the command the
settings name.

--jira adds read-only tracker lookups (issue links, text search). Nothing here
writes to the tracker: proposed links are a list for the user; they are created
only on the user's go-ahead, by a separate call.

Never invent a customer or a date. The output names customers; keep it local.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _desk  # noqa: E402  (takes --settings / --product off the command line)

UNPLANNED = "(unplanned)"


# ---------------------------------------------------------------- the team's settings
class Team:
    """The values of desk.clara.tickets (and the tracker) this script reads."""

    def __init__(self, doc: dict | None, source: str = "", tickets: dict | None = None):
        self.doc, self.source = doc or {}, source
        t = tickets if tickets is not None else (_desk.get(doc, "desk", "clara", "tickets", default={}) or {})
        self.t = t if isinstance(t, dict) else {}
        g = lambda *p, default=None: _desk.get(self.t, *p, default=default)  # noqa: E731
        self.done = {str(s).lower() for s in g("done_statuses", default=[]) or []}
        self.blocking = {str(s).lower() for s in g("blocking", default=[]) or []}
        self.blocking_label = str(g("blocking_label", default="/".join(sorted(self.blocking)) or "blocking"))
        self.excluded = tuple(f"{p}-" for p in g("excluded_projects", default=[]) or [])
        self.stale_days = int(g("stale_after_days", default=90) or 90)
        self.dupe_threshold = float(g("duplicate_similarity", default=0.62) or 0.62)
        self.lines = [str(x).lower() for x in g("separate_lines", default=[]) or []]
        self.prefixes = [re.compile(p, re.I) for p in g("title_prefixes", default=[]) or []]
        short = _desk.get(doc, "product", "short_name") or _desk.get(doc, "product", "name") or "Ticket"
        self.digest_title = str(g("digest_title", default=f"{short} ticket digest"))
        self.watch = _desk.expand(g("watch_list"))
        self.data = g("data", default={}) if isinstance(g("data"), dict) else {}
        self.sections = [s for s in self.data.get("sections") or [] if isinstance(s, dict) and s.get("id")]
        grp = g("grouping", default={}) or {}
        self.link_families = re.compile(grp.get("link_families") or r"(?!)")
        self.link_max = int(grp.get("max_members") or 6)
        self.skip_versions = tuple(grp.get("skip_versions") or ())
        self.search_projects = _desk.project_keys(doc, ("development", "support"))
        self.term_patterns = [(re.compile(x["term"]), x["search"]) for x in g("term_patterns", default=[]) or []
                              if isinstance(x, dict) and x.get("term") and x.get("search")]
        self.topic = g("topic", default={}) or {}
        self.lookup = g("cell_lookup", default={}) or {}
        self._families()

    def _families(self):
        """One alternation from desk.clara.tickets.template_families, tried in the settings' order.
        fam_specs: (group number of the family's own wrapper, its inner group count, its label)."""
        parts, self.fam_specs, group = [], [], 1
        for spec in _desk.get(self.t, "template_families", default=[]) or []:
            if not isinstance(spec, dict) or not spec.get("pattern"):
                continue
            inner = re.compile(spec["pattern"]).groups
            self.fam_specs.append((group, inner, spec.get("label")))
            parts.append(f"({spec['pattern']})")
            group += 1 + inner
        self.fam_re = re.compile("|".join(parts), re.I) if parts else None

    def sections_of(self, *kinds: str) -> list[dict]:
        return [s for s in self.sections if s.get("kind") in kinds]


TEAM: Team = Team(None)


def team() -> Team:
    return TEAM


# ---------------------------------------------------------------- board data
def _const(path: Path, name: str):
    if not path.exists():
        return None
    m = re.search(rf"^const {name} = (\{{.*\}});$", path.read_text(encoding="utf-8"), re.M)
    return json.loads(m.group(1)) if m else None


def _folder() -> Path | None:
    return _desk.expand(TEAM.data.get("folder"))


def load_board(data: str | None) -> dict:
    if data:
        return json.loads(Path(data).read_text(encoding="utf-8"))
    if TEAM.data.get("format") != "po-board" or not TEAM.sections:
        raise SystemExit("no ticket board is set up for this product (desk.clara.tickets.data: format po-board, "
                         "folder, sections). Ask Olga (Hey Olga) to run section clara-tickets of procedure "
                         "product-desk-onboarding, or pass --data <file>.")
    folder = _folder()
    if folder is None:
        raise SystemExit("desk.clara.tickets.data.folder names no usable path; pass --data <file>")
    first = (TEAM.sections_of("customer") or TEAM.sections)[0]
    dry = folder / str(TEAM.data.get("dry_run") or "")
    html = folder / str(first.get("page") or "")
    if TEAM.data.get("dry_run") and dry.exists() and (not html.exists() or dry.stat().st_mtime >= html.stat().st_mtime):
        return json.loads(dry.read_text(encoding="utf-8"))
    board = {s["id"]: _const(folder / str(s.get("page") or ""), str(s.get("const") or "")) for s in TEAM.sections}
    if not any(board.values()):
        raise SystemExit(f"no board data under {folder}: run {TEAM.data.get('refresh') or 'the board refresh'}")
    return {k: v or {} for k, v in board.items()}


def _blank(t: dict) -> dict:
    # the board renders an empty value as a dash
    return {k: ("" if isinstance(v, str) and v.strip() in {"—", "–", "-"} else v) for k, v in t.items()}


def tickets(board: dict) -> list[dict]:
    out = []
    for b in [s["id"] for s in TEAM.sections_of("customer")]:
        for t in map(_blank, (board.get(b) or {}).get("tickets") or []):
            out.append({"board": b, "key": t.get("frr") or t.get("sup"), "sup": t.get("sup") or "",
                        "frr": t.get("frr") or "", "title": t.get("title") or "", "customer": t.get("client") or "",
                        "priority": t.get("priority") or "", "status": t.get("jiraStatus") or t.get("supStatus") or "",
                        "supStatus": t.get("supStatus") or "", "frrStatus": t.get("frrStatus") or t.get("jiraStatus") or "",
                        "fixVersions": t.get("fixVersions") or [], "planning": t.get("planning") or "",
                        "assignee": t.get("assignee") or "", "pipeline": t.get("pipeline") or "",
                        "ageDays": t.get("ageDays") or 0, "created": t.get("created") or "",
                        "text": " ".join(str(t.get(k) or "") for k in ("title", "supDescription", "frrDescription")),
                        "url": t.get("frrUrl") or t.get("supUrl") or ""})
    for b in [s["id"] for s in TEAM.sections_of("internal")]:
        for t in map(_blank, (board.get(b) or {}).get("tickets") or []):
            out.append({"board": b, "key": t.get("key"), "sup": t.get("sup") or "", "frr": t.get("key") or "",
                        "title": t.get("summary") or "", "customer": t.get("customer") or "",
                        "priority": t.get("priority") or "", "status": t.get("status") or "",
                        "supStatus": t.get("supStatus") or "", "frrStatus": t.get("status") or "",
                        "fixVersions": t.get("fixVersions") or [], "planning": t.get("planning") or "",
                        "assignee": t.get("assignee") or "", "pipeline": t.get("origin") or "",
                        "module": t.get("module") or "", "ageDays": t.get("ageDays") or 0, "created": t.get("created") or "",
                        "text": " ".join(str(t.get(k) or "") for k in ("summary", "frrDescription", "supDescription")),
                        "url": t.get("url") or ""})
    return [t for t in out if not (TEAM.excluded and str(t["key"]).startswith(TEAM.excluded))]


def is_open(t: dict) -> bool:
    return (t["frrStatus"] or t["status"]).strip().lower() not in TEAM.done


def version_match(want: str, have: list[str]) -> bool:
    w = want.strip().lower()
    num = re.search(r"\d+\.\d+(?:\.\d+)?", w)
    for v in have:
        v2 = str(v).lower()
        if w == v2 or (num and re.search(rf"(?<![\d.]){re.escape(num.group(0))}(?![\d.])", v2)
                       and all((ln in w) == (ln in v2) for ln in TEAM.lines)):
            return True
    return False


def fill(template: str, m: re.Match, *groups) -> str:
    """A settings template: {0} the whole match, {1}.. its groups (literal braces doubled)."""
    return str(template).format(m.group(0), *[g or "" for g in (groups or m.groups())])


def families(text: str) -> set[str]:
    """Template families a text names; the label template also knows {first}, the match's first letter."""
    out = set()
    if TEAM.fam_re is None:
        return out
    for m in TEAM.fam_re.finditer(text or ""):
        s = m.group(0).upper()
        for group, inner, label in TEAM.fam_specs:
            if m.group(group) is None:
                continue
            inner_groups = [m.group(group + i) or "" for i in range(1, inner + 1)]
            out.add(str(label).format(s, *inner_groups, first=s[0]) if label else s)
            break
    return out


def line(t: dict) -> str:
    fv = ",".join(t["fixVersions"]) or "no fix version"
    sup = f" / {t['sup']}" if t["sup"] and t["sup"] != t["key"] else ""
    cust = t["customer"] or "-"
    return (f"{t['key']}{sup} [{t['board']}] {cust} · {t['priority'] or '-'} · {t['status'] or '-'} · {fv} · "
            f"{t['ageDays']}d · {t['title'][:80]}")


# ---------------------------------------------------------------- lookups
def _lookup_script() -> Path:
    lk = TEAM.lookup
    f = _desk.expand(lk["path"]) if lk.get("path") else _desk.skill_script(lk.get("skill"), lk.get("script"))
    f = f if f is not None and f.is_file() else None
    if f is None:
        raise SystemExit("the cell lookup is not set up for this product (desk.clara.tickets.cell_lookup: skill, "
                         "script). Ask Olga (Hey Olga) to run section clara-tickets of procedure "
                         "product-desk-onboarding.")
    return f


def _fields(rows: list[dict]) -> list[dict]:
    """The lookup's records with its field names mapped to class, rule_set, rule_id, classes, family, match."""
    fmap = TEAM.lookup.get("fields") or {}
    if not fmap:
        return rows
    return [{**r, **{ours: r.get(theirs) for ours, theirs in fmap.items() if theirs in r}} for r in rows]


def class_lookup(args: list[str], stdin: str | None = None) -> list[dict]:
    extra = [str(x) for x in TEAM.lookup.get("args") or []]
    r = subprocess.run([sys.executable, str(_lookup_script()), *args, *extra, "--json"], input=stdin,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return _fields(json.loads(r.stdout)) if r.stdout.strip().startswith("[") else []
    except json.JSONDecodeError:
        return []


def _topic_file(key: str) -> Path:
    f = _desk.asset_file(TEAM.doc, TEAM.source, TEAM.topic.get(key))
    if f is None:
        raise SystemExit(f"topic source {key} not found (desk.clara.tickets.topic.{key}: "
                         f"{TEAM.topic.get(key) or 'not set'})")
    return f


def taxonomy() -> list[dict]:
    t = _topic_file("taxonomy").read_text(encoding="utf-8")
    sec = t.split(f"## {TEAM.topic.get('taxonomy_section') or 'Template families'}", 1)[1].split("\n## ", 1)[0]
    rows = []
    for ln in sec.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] not in ("Family", "---") and not set(cells[0]) <= {"-"}:
            rows.append({"family": cells[0], "templates": cells[1], "regulation": cells[2]})
    return rows


def function_catalog() -> dict:
    return json.loads(_topic_file("functions").read_text(encoding="utf-8")) if TEAM.topic.get("functions") else {}


def terms_for_topic(text: str) -> tuple[list[str], list[str]]:
    """Search terms for a topic, and a note per source that produced them."""
    q = text.lower()
    terms, notes = set(), []
    code_re = re.compile(TEAM.topic.get("template_code") or r"(?!)")
    code_term = TEAM.topic.get("code_term") or "{0}"   # {0} the whole match, {1}.. its groups
    for row in (taxonomy() if TEAM.topic.get("taxonomy") else []):
        hay = " ".join(row.values()).lower()
        if row["family"].lower() in q or q in hay:
            terms.add(row["family"])
            terms.update(fill(code_term, m) for m in code_re.finditer(row["templates"]))
            notes.append(f"family {row['family']}: {row['templates']} ({row['regulation']})")
    for name, info in function_catalog().items():
        if q.replace(" ", "") in name.lower() or (len(q) > 4 and q in (info.get("description") or "").lower()):
            terms.add(name)
            notes.append(f"function {name}: {(info.get('description') or '')[:90]}")
    terms.update(families(text))
    if not terms:
        terms.add(text)
    return sorted(terms), notes[:12]


def search_board(ts: list[dict], terms: list[str]) -> list[dict]:
    pats = []
    for term in terms:
        for rx, search in TEAM.term_patterns:
            m = rx.match(term)
            if m:
                pats.append(re.compile(fill(search, m), re.I))
                break
        else:
            pats.append(re.compile(rf"\b{re.escape(term)}\b", re.I))
    return [t for t in ts if any(p.search(t["text"]) for p in pats)]


def jql_text(terms: list[str]) -> str:
    ors = " OR ".join(f'text ~ "\\"{t}\\""' for t in terms[:8])
    return f"project in ({', '.join(TEAM.search_projects)}) AND ({ors}) ORDER BY updated DESC"


def jira():
    return _desk.Tracker(TEAM.doc)


SEARCH_FIELDS = ["summary", "status", "fixVersions", "priority", "assignee", "labels"]


def jira_search(jql: str, limit: int = 500, client=None) -> tuple[list[dict], bool]:
    """Every issue of a JQL across all result pages, each key once; (issues, cut short at `limit`)."""
    return _desk.search_all(client or jira(), stable_order(jql), SEARCH_FIELDS, cap=limit)


def stable_order(jql: str) -> str:
    """A JQL without ORDER BY pages in key order, so no issue moves between pages while they are read."""
    return jql if re.search(r"\border\s+by\b", jql, re.I) else f"{jql.rstrip()} ORDER BY key ASC"


SPLITS = {
    "status": lambda f: (f.get("status") or {}).get("name") or "(no status)",
    "priority": lambda f: (f.get("priority") or {}).get("name") or "(no priority)",
    "fixVersion": lambda f: ", ".join(sorted(v.get("name") or "" for v in f.get("fixVersions") or [])) or "(no fix version)",
    "label": lambda f: ", ".join(sorted(f.get("labels") or [])) or "(no label)",
    "assignee": lambda f: (f.get("assignee") or {}).get("displayName") or "(unassigned)",
    "project": None,
}


def split_by(issues: list[dict], by: str) -> dict[str, list[str]]:
    """Issue keys per value of one field. Each key sits in exactly one group (several fix versions or
    labels form one combined value), so the groups always add up to the number of issues."""
    out: dict[str, list[str]] = defaultdict(list)
    seen = set()
    for iss in issues:
        key = iss.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        value = key.rsplit("-", 1)[0] if by == "project" else SPLITS[by](iss.get("fields") or {})
        out[value].append(key)
    return dict(sorted(out.items(), key=lambda kv: (-len(kv[1]), kv[0])))


def jira_links(keys: list[str]) -> dict[str, set[str]]:
    client, out = jira(), {}
    for k in keys:
        try:
            iss = client.get(f"issue/{k}", fields="issuelinks")
        except Exception as e:  # noqa: BLE001 — report and carry on; a link we cannot read is "not checked"
            print(f"  links not read for {k}: {e.__class__.__name__}")
            continue
        linked = set()
        for ln in (iss.get("fields") or {}).get("issuelinks") or []:
            other = ln.get("outwardIssue") or ln.get("inwardIssue") or {}
            if other.get("key"):
                linked.add(other["key"])
        out[k] = linked
    return out


# ---------------------------------------------------------------- analyses
def clusters(ts: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in ts:
        if t["sup"]:
            groups[f"SUP {t['sup']}"].append(t)
        for fam in families(t["text"]):
            for v in t["fixVersions"] or [UNPLANNED]:
                groups[f"{fam} · {v}"].append(t)
    out = {}
    for k, v in groups.items():
        uniq = {t["key"]: t for t in v}
        if len(uniq) > 1:
            out[k] = list(uniq.values())
    return dict(sorted(out.items(), key=lambda kv: -len(kv[1])))


def norm_title(s: str) -> str:
    s = re.sub(r"\[[^\]]*\]", " ", s or "")
    for p in TEAM.prefixes:
        s = p.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def dupes(ts: list[dict], threshold: float) -> list[tuple[float, dict, dict]]:
    out, seen = [], set()
    items = [(norm_title(t["title"]), t) for t in ts if t["title"]]
    for i, (a, ta) in enumerate(items):
        for b, tb in items[i + 1:]:
            if ta["key"] == tb["key"] or (ta["sup"] and ta["sup"] == tb["sup"]):
                continue
            pair = tuple(sorted((ta["key"], tb["key"])))
            if pair in seen:
                continue
            r = difflib.SequenceMatcher(None, a, b).ratio()
            if r >= threshold:
                seen.add(pair)
                out.append((r, ta, tb))
    return sorted(out, key=lambda x: -x[0])


def hygiene(ts: list[dict]) -> dict[str, list[dict]]:
    internal = {s["id"] for s in TEAM.sections_of("internal")}
    h: dict[str, list[dict]] = defaultdict(list)
    for t in ts:
        if not is_open(t):
            if t["supStatus"] and t["supStatus"].lower() not in TEAM.done and t["board"] not in internal:
                h["development done, support case still open"].append(t)
            continue
        if t["frr"] and not t["fixVersions"]:
            h["open development without a fix version"].append(t)
        if t["frr"] and not t["assignee"]:
            h["open development without an assignee"].append(t)
        if t["priority"].lower() in TEAM.blocking and not t["fixVersions"]:
            h["critical without a fix version"].append(t)
        if t["pipeline"].lower().startswith("still on support") and t["ageDays"] > 30:
            h["support case over 30 days with no development ticket"].append(t)
        if t["board"] in internal and not t.get("module"):
            h["internal item without a module"].append(t)
    return h


def release_row(board: dict, version: str) -> list[dict]:
    rows = []
    for s in TEAM.sections_of("roadmap"):
        rows += [r for r in (board.get(s["id"]) or {}).get("releases") or []
                 if version_match(version, [r.get("versionName") or ""])]
    return rows


# ---------------------------------------------------------------- commands
def cmd_customer(ts, a):
    rows = [t for t in ts if a.name.lower() in t["customer"].lower()]
    if a.release:
        rows = [t for t in rows if version_match(a.release, t["fixVersions"])]
    print(f"{len(rows)} ticket(s) for customer '{a.name}'" + (f" in {a.release}" if a.release else ""))
    for t in sorted(rows, key=lambda t: (-t["ageDays"])):
        print("  " + line(t))
    if not rows:
        print("  none on the board. The customer name must match the board's client field; "
              "nothing is inferred from ticket titles.")


def cmd_release(board, ts, a):
    rows = [t for t in ts if version_match(a.version, t["fixVersions"])]
    for r in release_row(board, a.version):
        print(f"{r.get('versionName')}: {r.get('date') or 'no date'} ({r.get('dateSource') or 'no source'})"
              f" · {'released' if r.get('released') else 'planned'} · release ticket {r.get('releaseTicket') or 'none'}")
    if not release_row(board, a.version):
        print(f"{a.version}: not on the roadmap (no Jira version date); no date is inferred")
    opn = [t for t in rows if is_open(t)]
    blocking = [t for t in opn if t["priority"].lower() in TEAM.blocking]
    print(f"{len(rows)} board ticket(s), {len(opn)} open, {len(blocking)} open at {TEAM.blocking_label} priority")
    for t in sorted(opn, key=lambda t: (t["priority"].lower() not in TEAM.blocking, -t["ageDays"])):
        print(("  ! " if t in blocking else "    ") + line(t))
    if a.jira:
        for r in release_row(board, a.version):
            k = r.get("releaseTicket")
            if k:
                links = jira_links([k]).get(k, set())
                print(f"  {k} links: {', '.join(sorted(links)) or 'none'}")


def cmd_cell(ts, a):
    spec = a.spec
    if "|" in spec:
        hits = class_lookup(["cells", "-"], stdin=spec + "\n")
        classes = [c for h in hits for c in (h.get("classes") or [])]
        fam = hits[0]["family"] if hits else spec.split("|")[0]
        terms = sorted({fam, *families(fam.replace("_", " ")), *classes[:10]})
        print(f"{spec}: match {hits[0]['match'] if hits else 'none'}, {len(classes)} class(es)")
    elif spec.isdigit():
        hits = class_lookup(["rule", spec])
        terms = sorted({h["class"] for h in hits} | {spec})
        print(f"rule {spec}: {len(hits)} class(es) in {sorted({h['rule_set'] for h in hits})}")
    else:
        hits = class_lookup(["class", spec])
        terms = sorted({spec} | {h.get("rule_id") for h in hits if h.get("rule_id")})
        print(f"class {spec}: {len(hits)} hit(s) in {sorted({h['rule_set'] for h in hits})}")
    _board_and_jira(ts, terms, a.jira)


def cmd_topic(ts, a):
    terms, notes = terms_for_topic(a.text)
    for n in notes:
        print(f"  {n}")
    _board_and_jira(ts, terms, a.jira)


def _board_and_jira(ts, terms, use_jira):
    print(f"search terms: {', '.join(terms[:12])}")
    rows = search_board(ts, terms)
    print(f"{len(rows)} board ticket(s) mention them:")
    for t in rows:
        print("  " + line(t))
    jql = jql_text(terms)
    print(f"JQL: {jql}")
    if use_jira:
        res, cut = jira_search(jql)
        print(f"Jira Cloud: {len(res)} issue(s)" + (" — TRUNCATED at 500" if cut else ""))
        for iss in res:
            f = iss.get("fields") or {}
            print(f"  {iss['key']} · {(f.get('status') or {}).get('name')} · "
                  f"{','.join(v['name'] for v in f.get('fixVersions') or []) or 'no fix version'} · "
                  f"{(f.get('summary') or '')[:80]}")


def cmd_search(a, client=None) -> int:
    issues, cut = jira_search(a.jql, a.limit, client)
    print(f"Jira Cloud: {len(issues)} issue(s) for {a.jql}, each counted once"
          + (f" — TRUNCATED at {a.limit}; raise --limit for the rest" if cut else ""))
    if a.by:
        groups = split_by(issues, a.by)
        print(f"by {a.by}:")
        for value, keys in groups.items():
            print(f"  {len(keys):4}  {value}")
        print(f"  {sum(len(k) for k in groups.values()):4}  total")
    if not a.count:
        for iss in issues:
            f = iss.get("fields") or {}
            print(f"  {iss['key']} · {SPLITS['status'](f)} · {SPLITS['fixVersion'](f)} · {(f.get('summary') or '')[:80]}")
    return 0


def cmd_group(ts, a):
    if a.board != "all":
        ts = [t for t in ts if t["board"] == a.board]
    cl = clusters(ts)
    links = jira_links(sorted({t["frr"] for v in cl.values() for t in v if t["frr"]})) if a.jira else None
    proposals = []
    for name, members in list(cl.items())[: a.limit]:
        print(f"{name} ({len(members)})")
        for t in members:
            print("    " + line(t))
        # a shared SUP is already a link; an unplanned or large family cluster is a topic, not one problem
        if name.startswith("SUP ") or name.endswith((UNPLANNED, *TEAM.skip_versions)) or len(members) > TEAM.link_max \
                or not TEAM.link_families.match(name):
            continue
        frrs = sorted({t["frr"] for t in members if t["frr"]})
        for i, x in enumerate(frrs):
            for y in frrs[i + 1:]:
                if links is None or (y not in links.get(x, set()) and x not in links.get(y, set())):
                    proposals.append((x, y, name))
    print()
    if links is None:
        print("Existing links not checked (add --jira). Candidate pairs below may already be linked.")
    print(f"Proposed 'relates to' links ({len(proposals)}), not created. Each needs your go-ahead:")
    for x, y, why in proposals[:40]:
        print(f"  {x} relates to {y}  (shared {why})")


def cmd_dupes(ts, a):
    rows = dupes(ts, a.threshold)
    print(f"{len(rows)} likely duplicate pair(s) at title similarity >= {a.threshold}:")
    for r, x, y in rows[:40]:
        print(f"  {r:.2f}  {x['key']} [{x['customer'] or '-'}]  ~  {y['key']} [{y['customer'] or '-'}]")
        print(f"        {x['title'][:70]}\n        {y['title'][:70]}")


def cmd_stale(ts, a):
    rows = sorted([t for t in ts if is_open(t) and t["ageDays"] >= a.days], key=lambda t: -t["ageDays"])
    print(f"{len(rows)} open ticket(s) older than {a.days} days:")
    for t in rows:
        fam = ",".join(sorted(families(t["text"]))) or "no template family named"
        print(f"  {line(t)}\n      probable group: {fam}")


def cmd_hygiene(ts, a):
    h = hygiene(ts)
    for k, rows in h.items():
        print(f"{k}: {len(rows)}")
        for t in rows[:25]:
            print("    " + line(t))
    if not h:
        print("no hygiene findings")


def cmd_changed(ts, a):
    rows = [t for t in ts if a.customer.lower() in t["customer"].lower() and version_match(a.release, t["fixVersions"])]
    done = [t for t in rows if not is_open(t)]
    print(f"{a.customer} in {a.release}: {len(rows)} ticket(s), {len(done)} done, {len(rows) - len(done)} still open")
    for t in rows:
        print(("  done  " if t in done else "  open  ") + line(t))


def cmd_digest(board, ts, a):
    since = dt.date.today() - dt.timedelta(days=a.since)
    new = [t for t in ts if t["created"][:10] >= since.isoformat()]
    opn = [t for t in ts if is_open(t)]
    by_cust = defaultdict(int)
    for t in opn:
        by_cust[t["customer"] or "(none)"] += 1
    first = (TEAM.sections_of("customer") or [{"id": ""}])[0]["id"]
    as_of = (board.get(first) or {}).get("asOf") or "unknown"
    print(f"# {TEAM.digest_title} — board as of {as_of}")
    print(f"open {len(opn)} · new in the last {a.since} days {len(new)}")
    print("open by customer: " + ", ".join(f"{k} {v}" for k, v in sorted(by_cust.items(), key=lambda kv: -kv[1])))
    for t in new:
        print("  new  " + line(t))
    h = hygiene(ts)
    print("hygiene: " + (", ".join(f"{k} {len(v)}" for k, v in h.items()) or "clean"))
    oldest = sorted(opn, key=lambda t: -t["ageDays"])[:5]
    print("oldest open:")
    for t in oldest:
        print("  " + line(t))
    watch = Path(a.watch) if a.watch else TEAM.watch
    if watch is not None and watch.exists():
        keys = [k.strip() for k in watch.read_text(encoding="utf-8").splitlines() if k.strip() and not k.startswith("#")]
        idx = {t["key"]: t for t in ts} | {t["sup"]: t for t in ts if t["sup"]}
        print(f"watch list ({len(keys)}):")
        for k in keys:
            print("  " + (line(idx[k]) if k in idx else f"{k}: not on the board"))


KEY_ARG = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def cmd_branches(a) -> int:
    import branch_check as bc
    bc.configure(TEAM.doc, TEAM.source)
    keys, info, client = [k.upper() for k in a.keys], {}, None
    bad = [k for k in keys if not KEY_ARG.match(k)]
    if bad:
        print(f"not a ticket key: {', '.join(bad)}")
        return 2
    if a.release:
        _desk.gate("clara", "tickets", TEAM.doc, TEAM.source)
        rows = [t for t in tickets(load_board(a.data)) if version_match(a.release, t["fixVersions"])]
        no_dev = [t for t in rows if not t["frr"]]
        keys += [t["frr"] for t in rows if t["frr"]]
        print(f"board: {len(rows)} ticket(s) with fix version {a.release}"
              + (f"; {len(no_dev)} have no development ticket and are not checked" if no_dev else ""))
    if a.jql:
        client = jira()
        issues, cut = bc.search_all(client, a.jql, ["summary", "status", "fixVersions"], cap=a.limit)
        print(f"Jira Cloud: {len(issues)} issue(s) for {a.jql}"
              + (f" — TRUNCATED at {a.limit}; raise --limit for the rest" if cut else ""))
        for iss in issues:
            f = iss.get("fields") or {}
            keys.append(iss["key"])
            info[iss["key"]] = {"summary": f.get("summary") or "", "status": (f.get("status") or {}).get("name") or "",
                                "fixVersions": [v["name"] for v in f.get("fixVersions") or []]}
    keys = list(dict.fromkeys(keys))
    if not keys:
        print("no tickets to check: give keys, --release or --jql")
        return 2
    if a.jira and len(info) < len(keys):
        client = client or jira()
        info.update(bc.ticket_info(client, [k for k in keys if k not in info]))
    products = [p.strip() for p in (a.products or ",".join(bc.PRODUCTS)).split(",") if p.strip()]
    unknown = [p for p in products if p not in bc.PRODUCTS]
    if unknown:
        print(f"unknown product(s) {unknown}; use {','.join(bc.PRODUCTS)}")
        return 2
    res = bc.check(keys, products, fetch=a.fetch)
    detail = a.detail or len(keys) == 1
    print(bc.render(res, info or None, detail=detail), end="")
    if a.md:
        Path(a.md).write_text(bc.render(res, info or None, detail=detail, md=True), encoding="utf-8")
        print(f"wrote {a.md}")
    if a.json:
        Path(a.json).write_text(bc.to_json(res, info), encoding="utf-8")
        print(f"wrote {a.json}")
    return 0


# ---------------------------------------------------------------- self-test (synthetic, offline)
SYNTHETIC_TICKETS = {
    "status": "on",
    "data": {"format": "po-board", "folder": "~/no-board", "dry_run": "board.json",
             "sections": [{"id": "main", "kind": "customer", "page": "main.html", "const": "DATA"},
                          {"id": "side", "kind": "internal", "page": "side.html", "const": "SIDE_DATA"},
                          {"id": "plan", "kind": "roadmap", "page": "plan.html", "const": "PLAN_DATA"}]},
    "blocking": ["Blocker", "Critical"],
    "done_statuses": ["done", "closed"],
    "excluded_projects": ["SKIP"],
    "separate_lines": ["lite"],
    "title_prefixes": [r"^\s*(DEMO)\s*:\s*", r"\b(DEMO|ABC)\s*:\s*"],
    "template_families": [{"pattern": r"\b(?:T|U)\s?_?(\d{2})(?:[._ ]?(\d{2}))?\b", "label": "{first}_{1}"},
                          {"pattern": r"\bXYZ\s?-?9\b", "label": "XYZ9"},
                          {"pattern": r"\bABC\b"}],
    "term_patterns": [{"term": r"^([TU])[_ ](\d{2})$", "search": r"\b{1}\s?_?{2}\b"}],
    "topic": {"template_code": r"\b([TU])\s(\d{2})\.(\d{2})", "code_term": "{1} {2}"},
    "grouping": {"link_families": r"^([TU]_\d{2}|XYZ9) ", "max_members": 6, "skip_versions": ["LATER"]},
}


def selftest() -> int:
    global TEAM
    fails = []
    doc = {"product": {"short_name": "Demo"},
           "tracker": {"projects": [{"key": "DEV", "role": "development"}, {"key": "HELP", "role": "support"},
                                    {"key": "REL", "role": "releases"}]},
           "desk": {"clara": {"tickets": SYNTHETIC_TICKETS}}}
    TEAM = Team(doc)
    fam = families("Demo: T 73.00 outflow, T_76 reserves and XYZ-9 plus ABC")
    if fam != {"T_73", "T_76", "XYZ9", "ABC"}:
        fails.append(f"families {fam}")
    if not version_match("6.1.0", ["Demo 6.1.0"]) or version_match("6.1.0", ["Demo 6.1.01"]):
        fails.append("version match")
    if version_match("6.0.3", ["Demo lite 6.0.3"]):
        fails.append("a separate line must be asked for explicitly")
    base = dict(board="main", sup="", frr="DEV-1", title="", customer="A", priority="Critical", status="New",
                supStatus="", frrStatus="New", fixVersions=[], planning="", assignee="", pipeline="Jira opened",
                ageDays=40, created="2026-09-01", text="T 73.00 outflows", url="")
    ts = [dict(base, key="DEV-1", title="DEMO: [SF-1] T73 outflow for retail deposits wrong"),
          dict(base, key="DEV-2", frr="DEV-2", title="ABC: T73 outflow for retail deposit wrong", fixVersions=["X 1.0"]),
          dict(base, key="SKIP-9", frr="SKIP-9", title="excluded")]
    ts = [t for t in ts if not t["key"].startswith(TEAM.excluded)]
    if len(dupes(ts, 0.62)) != 1:
        fails.append("dupes")
    h = hygiene(ts)
    if len(h.get("critical without a fix version", [])) != 1 or len(h.get("open development without an assignee", [])) != 2:
        fails.append(f"hygiene {dict((k, len(v)) for k, v in h.items())}")
    if not any(k.startswith("T_73") for k in clusters([dict(t, fixVersions=["X 1.0"]) for t in ts])):
        fails.append("clusters")
    if len(search_board(ts, ["T_73"])) != 2:
        fails.append("search family")
    m = re.search(TEAM.topic["template_code"], "U 80.00 and T 61.00")
    if fill(TEAM.topic["code_term"], m) != "U 80":
        fails.append("topic code term")
    if jql_text(["x"]) != 'project in (DEV, HELP) AND (text ~ "\\"x\\"") ORDER BY updated DESC':
        fails.append(f"jql {jql_text(['x'])}")
    t = tickets({"main": {"tickets": [{"frr": "—", "sup": "HELP-1", "title": "x", "fixVersions": []}]}})[0]
    if t["frr"] or t["key"] != "HELP-1":
        fails.append("a dash must read as empty")
    if Team(doc).digest_title != "Demo ticket digest":
        fails.append(f"digest title {Team(doc).digest_title}")
    blank = Team({"desk": {"clara": {"tickets": {}}}})
    if blank.fam_re is not None or blank.done or blank.blocking or blank.sections or blank.search_projects:
        fails.append("a team with no settings must borrow nothing")
    TEAM = blank
    if families("T 73.00 XYZ-9") or norm_title("DEMO: x") != "demo: x":
        fails.append("no settings: no families, no prefixes")
    try:
        load_board(None)
        fails.append("no board settings must stop")
    except SystemExit as e:
        if "Ask Olga" not in str(e):
            fails.append(f"no board settings: {e}")
    fails += _selftest_tracker_pages()
    for f in fails:
        print("FAIL", f)
    print("selftest OK: families, versions, dupes, hygiene, clusters, search, jql, blanks, no borrowing, "
          "result pages, one count per key" if not fails else "selftest FAILED")
    return 1 if fails else 0


class _Pages:
    """A fake tracker serving fixed result pages; records each request body."""

    def __init__(self, pages: list[dict]):
        self.pages, self.bodies, self.base = pages, [], "https://demo.example/"
        self.s = self

    def post(self, url, timeout=None, json=None):
        self.bodies.append(json)
        page = self.pages[min(len(self.bodies), len(self.pages)) - 1]
        return type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: page})()


def _issue(key: str, status: str, versions: tuple[str, ...] = ()) -> dict:
    return {"key": key, "fields": {"summary": f"s {key}", "status": {"name": status},
                                   "fixVersions": [{"name": v} for v in versions]}}


def _selftest_tracker_pages() -> list[str]:
    import contextlib
    import io

    fails = []
    # three token pages; page 2 repeats DEV-2 from page 1 (the order moved while paging)
    token_pages = [
        {"issues": [_issue("DEV-1", "Open"), _issue("DEV-2", "In Progress", ("1.0",))], "nextPageToken": "p2", "isLast": False},
        {"issues": [_issue("DEV-2", "In Progress", ("1.0",)), _issue("DEV-3", "Open", ("1.0", "2.0"))],
         "nextPageToken": "p3", "isLast": False},
        {"issues": [_issue("DEV-4", "Done")], "isLast": True},
    ]
    fake = _Pages(token_pages)
    issues, cut = jira_search("labels = demo", 500, fake)
    keys = [i["key"] for i in issues]
    if keys != ["DEV-1", "DEV-2", "DEV-3", "DEV-4"] or cut:
        fails.append(f"token pages: {keys} cut={cut}")
    if [b.get("nextPageToken") for b in fake.bodies] != [None, "p2", "p3"]:
        fails.append(f"token pages: tokens sent {[b.get('nextPageToken') for b in fake.bodies]}")
    if not fake.bodies[0]["jql"].endswith("ORDER BY key ASC"):
        fails.append(f"a JQL without ORDER BY is not paged in key order: {fake.bodies[0]['jql']}")
    if stable_order("x ORDER BY updated DESC") != "x ORDER BY updated DESC":
        fails.append("an explicit ORDER BY was replaced")
    st = split_by(issues + [issues[1]], "status")
    if st != {"Open": ["DEV-1", "DEV-3"], "Done": ["DEV-4"], "In Progress": ["DEV-2"]}:
        fails.append(f"status split counts a key twice or loses one: {st}")
    fv = split_by(issues, "fixVersion")
    if sum(len(v) for v in fv.values()) != 4 or fv.get("1.0, 2.0") != ["DEV-3"]:
        fails.append(f"fix-version split puts a ticket in two groups: {fv}")
    if split_by(issues, "project") != {"DEV": keys}:
        fails.append("project split")
    # startAt + total pages, no token
    offset_pages = [{"startAt": 0, "total": 3, "issues": [_issue("HELP-1", "Open"), _issue("HELP-2", "Open")]},
                    {"startAt": 2, "total": 3, "issues": [_issue("HELP-3", "Done")]}]
    fake = _Pages(offset_pages)
    issues, cut = jira_search("project = HELP", 500, fake)
    if [i["key"] for i in issues] != ["HELP-1", "HELP-2", "HELP-3"] or cut or fake.bodies[1].get("startAt") != 2:
        fails.append(f"startAt pages: {[i['key'] for i in issues]} cut={cut} bodies={fake.bodies}")
    # a cap below the result says TRUNCATED
    issues, cut = jira_search("labels = demo", 2, _Pages(token_pages))
    if len(issues) != 2 or not cut:
        fails.append(f"a capped search must say it was cut short: {len(issues)} cut={cut}")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_search(argparse.Namespace(jql="labels = demo", by="status", count=True, limit=500), _Pages(token_pages))
    text = out.getvalue()
    if "4 issue(s)" not in text or not re.search(r"^\s+4\s+total$", text, re.M) or "DEV-1 ·" in text:
        fails.append(f"search --by status --count output:\n{text}")
    return fails


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="board JSON (default: the settings' export)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    boards = [s["id"] for s in TEAM.sections_of("customer", "internal")] + ["all"]
    p = sub.add_parser("customer"); p.add_argument("name"); p.add_argument("--release")
    p = sub.add_parser("release"); p.add_argument("version"); p.add_argument("--jira", action="store_true")
    p = sub.add_parser("cell"); p.add_argument("spec"); p.add_argument("--jira", action="store_true")
    p = sub.add_parser("topic"); p.add_argument("text"); p.add_argument("--jira", action="store_true")
    p = sub.add_parser("group"); p.add_argument("--board", default="all", choices=boards)
    p.add_argument("--jira", action="store_true"); p.add_argument("--limit", type=int, default=15)
    p = sub.add_parser("dupes"); p.add_argument("--threshold", type=float, default=TEAM.dupe_threshold)
    p = sub.add_parser("stale"); p.add_argument("--days", type=int, default=TEAM.stale_days)
    sub.add_parser("hygiene")
    p = sub.add_parser("changed"); p.add_argument("--customer", required=True); p.add_argument("--release", required=True)
    p = sub.add_parser("digest"); p.add_argument("--since", type=int, default=7); p.add_argument("--watch")
    p = sub.add_parser("branches", help="is each ticket's change on each release line?")
    p.add_argument("keys", nargs="*", help="ticket keys")
    p.add_argument("--release", help="every board ticket with this fix version")
    p.add_argument("--jql", help="every tracker issue this JQL returns (read-only)")
    p.add_argument("--limit", type=int, default=500, help="cap for --jql (default 500)")
    p.add_argument("--products", default=None, help="short product names from desk.clara.branch_check.products "
                                                   "(default all)")
    p.add_argument("--fetch", action="store_true", help="git fetch each clone first (needs the VPN)")
    p.add_argument("--jira", action="store_true", help="add status, fix version and summary from the tracker")
    p.add_argument("--detail", action="store_true", help="per-ticket commit list (the default for one ticket)")
    p.add_argument("--md", help="also write the result as Markdown to this file")
    p.add_argument("--json", help="also write the result as JSON to this file")
    p = sub.add_parser("search", help="count and list the issues of a JQL, reading every result page (read-only)")
    p.add_argument("--jql", required=True)
    p.add_argument("--by", choices=sorted(SPLITS), help="split the count by one field; each ticket in one group")
    p.add_argument("--count", action="store_true", help="counts only, no ticket list")
    p.add_argument("--limit", type=int, default=1000, help="cap (default 1000); TRUNCATED is printed when reached")
    sub.add_parser("selftest")
    return ap


def main(argv=None) -> int:
    global TEAM
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    doc, source = _desk.load()
    TEAM = Team(doc, source)
    a = _parser().parse_args(argv)
    if a.cmd == "selftest":
        rc = selftest()
        import branch_check
        return rc | branch_check.selftest()
    if a.cmd == "branches":
        _desk.gate("clara", "branch_check", doc, source)
        return cmd_branches(a)
    _desk.gate("clara", "tickets", doc, source)
    if a.cmd == "search":
        return cmd_search(a)
    board = load_board(a.data)
    ts = tickets(board)
    {"customer": lambda: cmd_customer(ts, a), "release": lambda: cmd_release(board, ts, a),
     "cell": lambda: cmd_cell(ts, a), "topic": lambda: cmd_topic(ts, a), "group": lambda: cmd_group(ts, a),
     "dupes": lambda: cmd_dupes(ts, a), "stale": lambda: cmd_stale(ts, a), "hygiene": lambda: cmd_hygiene(ts, a),
     "changed": lambda: cmd_changed(ts, a), "digest": lambda: cmd_digest(board, ts, a)}[a.cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
