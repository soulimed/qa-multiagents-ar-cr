#!/usr/bin/env python3
"""Rela's release readiness check: is version X ready for its notes and its release?

  readiness.py --version 1.2.0 [--prefix "<fix-version prefix>"] [--qat verdict.yaml ...] [--out file.md]
  readiness.py selftest

Everything team-specific comes from the team's desk settings (capability rela.readiness):
the tracker, its development project, the fix-version pattern, the release-notes and
exclude field ids, the release-ticket project and the blocking priorities.

Inputs, all read-only:
  * the tracker: every issue of the development project in the fixVersion (all statuses)
    with status, assignee, priority, the release-notes field and the exclude field;
    the tracker version itself (release date, released flag).
  * Clara's board (product-desk-tickets, when clara.tickets is on): the release ticket
    and the customers per ticket.
  * Qata's verdicts: YAML/JSON files with `verdict: PASS | FAIL | CANNOT TELL` plus `run`, `commit`
    and `evidence`, optionally per ticket (`tickets: {KEY-n: PASS}`). No verdict is a blocker.

Output: READY or NOT READY, then every blocker with its owner. Nothing is written
anywhere except --out. Exit 3 = NOT READY, or the capability is not set up.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "product-desk-tickets" / "scripts"))
import _desk  # noqa: E402  (takes --settings / --product off the command line)

RN_FIELD, EXCL_FIELD = "release_notes", "exclude_from_release_notes"
BLOCKING_PRIO = {"blocker", "critical", "highest"}
RELEASE_PROJECT = "release"


def configure(doc: dict | None) -> None:
    """Field ids, blocking priorities and the release-ticket project from the settings."""
    global RN_FIELD, EXCL_FIELD, BLOCKING_PRIO, RELEASE_PROJECT
    RN_FIELD = str(_desk.get(doc, "tracker", "fields", "release_notes", default="release_notes"))
    EXCL_FIELD = str(_desk.get(doc, "tracker", "fields", "exclude_from_release_notes",
                               default="exclude_from_release_notes"))
    prio = _desk.get(doc, "desk", "rela", "readiness", "blocking") \
        or _desk.get(doc, "desk", "clara", "tickets", "blocking", default=[])
    BLOCKING_PRIO = {str(p).lower() for p in prio or []}
    RELEASE_PROJECT = str(_desk.get(doc, "desk", "rela", "readiness", "release_ticket_project", default="release"))


def read_text_any(path: Path | str) -> str:
    """Text from a file written by Python, PowerShell `>` (UTF-16 LE BOM) or Excel (UTF-8 BOM)."""
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def adf_text(node) -> str:
    """Flatten an Atlassian Document Format node to plain text."""
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        sep = "\n" if node.get("type") in ("paragraph", "heading", "listItem", "tableRow", "panel") else ""
        return "".join(adf_text(c) for c in node.get("content", [])) + sep
    if isinstance(node, list):
        return "".join(adf_text(c) for c in node)
    return ""


def load_verdicts(files: list[str]) -> list[dict]:
    import yaml
    out = []
    for f in files:
        data = yaml.safe_load(read_text_any(f)) or {}
        for item in data if isinstance(data, list) else [data]:
            item["_file"] = Path(f).name
            out.append(item)
    return out


def adf_or_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return adf_text(v).strip()


def excluded(v) -> bool:
    if not v:
        return False
    vals = v if isinstance(v, list) else [v]
    return any((x.get("value") if isinstance(x, dict) else str(x)) for x in vals)


def assess(issues: list[dict], version: dict | None, verdicts: list[dict], release_ticket: str | None,
           customers: dict[str, set[str]], case_prio: dict[str, str] | None = None) -> dict:
    case_prio = case_prio or {}
    blockers, rows = [], []
    for iss in issues:
        f = iss.get("fields") or {}
        key = iss["key"]
        status = (f.get("status") or {}).get("name") or "?"
        done = ((f.get("status") or {}).get("statusCategory") or {}).get("key") == "done"
        owner = (f.get("assignee") or {}).get("displayName") or "unassigned (PO to assign)"
        prio = (f.get("priority") or {}).get("name") or ""
        rn = adf_or_text(f.get(RN_FIELD))
        excl = excluded(f.get(EXCL_FIELD))
        rows.append({"key": key, "summary": f.get("summary") or "", "status": status, "done": done, "owner": owner,
                     "priority": prio, "rn": bool(rn), "excluded": excl,
                     "customers": sorted(customers.get(key, set()))})
        if not done:
            cp = case_prio.get(key, "")
            sev = "blocking" if prio.lower() in BLOCKING_PRIO or cp.lower() in BLOCKING_PRIO else "open"
            why = f", support case {cp}" if cp else ""
            blockers.append({"what": f"{key} not done ({status}, {prio or 'no priority'}{why}, {sev})", "owner": owner})
        elif not excl and not rn:
            blockers.append({"what": f"{key} done but its Release Notes field is empty", "owner": owner})
    if version is None:
        blockers.append({"what": "fix version not found in Jira", "owner": "release management"})
    elif not version.get("releaseDate"):
        blockers.append({"what": f"{version.get('name')} has no release date in Jira", "owner": "release management"})
    if not release_ticket:
        blockers.append({"what": f"no {RELEASE_PROJECT} release ticket found for this version",
                         "owner": "release management"})
    qat = [v for v in verdicts if str(v.get("verdict", "")).upper() in ("PASS", "FAIL", "CANNOT TELL")]
    if not qat:
        blockers.append({"what": "no Qata verdict for this release", "owner": "qa-qata"})
    for v in qat:
        if str(v["verdict"]).upper() != "PASS":
            blockers.append({"what": f"Qata verdict {v['verdict']} ({v.get('run') or v['_file']}): "
                                     f"{str(v.get('evidence') or '')[:100]}", "owner": "qa-qata"})
        for k, tv in (v.get("tickets") or {}).items():
            if str(tv).upper() != "PASS":
                blockers.append({"what": f"{k}: Qata verdict {tv}", "owner": "qa-qata"})
    return {"rows": rows, "blockers": blockers, "ready": not blockers}


def render(version_name: str, version: dict | None, release_ticket: str | None, res: dict) -> str:
    rows = res["rows"]
    done = sum(r["done"] for r in rows)
    out = [f"# Release readiness — {version_name}", "",
           f"**{'READY' if res['ready'] else 'NOT READY'}** — {len(res['blockers'])} blocker(s)", "",
           f"- Release date (Jira): {(version or {}).get('releaseDate') or 'none'}"
           f"{' · released' if (version or {}).get('released') else ''}",
           f"- Release ticket: {release_ticket or 'none'}",
           f"- Tickets: {len(rows)} · done {done} · open {len(rows) - done} · "
           f"excluded {sum(r['excluded'] for r in rows)} · with release note {sum(r['rn'] for r in rows)}", ""]
    if res["blockers"]:
        out += ["## Blockers", "", "| Blocker | Owner |", "|---|---|"]
        out += [f"| {b['what']} | {b['owner']} |" for b in res["blockers"]]
        out.append("")
    out += ["## Tickets", "", "| Ticket | Status | Owner | Release note | Customers |", "|---|---|---|---|---|"]
    for r in rows:
        note = "excluded" if r["excluded"] else ("yes" if r["rn"] else "missing")
        out.append(f"| {r['key']} {r['summary'][:60]} | {r['status']} | {r['owner']} | {note} | "
                   f"{', '.join(r['customers']) or '-'} |")
    return "\n".join(out) + "\n"


def selftest() -> int:
    saved = (RN_FIELD, EXCL_FIELD, BLOCKING_PRIO, RELEASE_PROJECT)
    configure({"tracker": {"fields": {"release_notes": "cf_rn", "exclude_from_release_notes": "cf_x"}},
               "desk": {"clara": {"tickets": {"blocking": ["Blocker", "Critical", "Highest"]}},
                        "rela": {"readiness": {"release_ticket_project": "REL"}}}})

    def iss(key, cat, rn=None, excl=None, prio="Medium", who="Ann"):
        return {"key": key, "fields": {"summary": key, "status": {"name": cat, "statusCategory": {"key": cat}},
                                       "assignee": {"displayName": who} if who else None,
                                       "priority": {"name": prio}, RN_FIELD: rn, EXCL_FIELD: excl}}
    fails = []
    try:
        issues = [iss("A-1", "done", rn="note"), iss("A-2", "done"), iss("A-3", "done", excl=[{"value": "Yes"}]),
                  iss("A-4", "indeterminate", prio="Critical", who=None)]
        res = assess(issues, {"name": "V", "releaseDate": "2026-10-13"}, [{"verdict": "PASS", "_file": "q"}], "REL-1", {})
        whats = " ".join(b["what"] for b in res["blockers"])
        if "A-2" not in whats or "A-1" in whats or "A-3" in whats or "A-4 not done" not in whats or "blocking" not in whats:
            fails.append(f"ticket blockers: {whats}")
        if not any(b["owner"].startswith("unassigned") for b in res["blockers"]):
            fails.append("unassigned owner")
        r4 = assess([iss("A-5", "indeterminate", prio="Major")], None, [], None, {}, {"A-5": "Critical"})
        if "support case Critical, blocking" not in r4["blockers"][0]["what"]:
            fails.append(f"a critical support case must make its open ticket blocking: {r4['blockers'][0]}")
        res2 = assess([iss("A-1", "done", rn="n")], {"name": "V"}, [], None, {})
        w2 = " ".join(b["what"] for b in res2["blockers"])
        if "no Qata verdict" not in w2 or "no release date" not in w2 or "no REL release ticket" not in w2 or res2["ready"]:
            fails.append(f"release blockers: {w2}")
        res3 = assess([iss("A-1", "done", rn="n")], {"name": "V", "releaseDate": "x"},
                      [{"verdict": "PASS", "_file": "q"}], "REL-1", {})
        if not res3["ready"]:
            fails.append(f"clean release must be READY: {res3['blockers']}")
        if adf_or_text({"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x"}]}]}) != "x":
            fails.append("a rich-text release note must count as filled")
    finally:
        configure_from(saved)
    for f in fails:
        print("FAIL", f)
    print("selftest OK: ticket, release and QAT blockers with owners" if not fails else "selftest FAILED")
    return 1 if fails else 0


def configure_from(saved: tuple) -> None:
    global RN_FIELD, EXCL_FIELD, BLOCKING_PRIO, RELEASE_PROJECT
    RN_FIELD, EXCL_FIELD, BLOCKING_PRIO, RELEASE_PROJECT = saved


def search_all(jira, jql: str, fields: list[str]) -> list[dict]:
    issues, token = [], None
    while True:
        body = {"jql": jql, "maxResults": 100, "fields": fields}
        if token:
            body["nextPageToken"] = token
        r = jira.s.post(jira.base + "search/jql", json=body, timeout=60)
        r.raise_for_status()
        page = r.json()
        issues += page.get("issues", [])
        token = page.get("nextPageToken")
        if not token or page.get("isLast", True):
            return issues


def read_board(doc: dict | None, source: str, version: str, prefix: str):
    """(release ticket, customers per ticket, board) from Clara's board, or Nones when it cannot be read."""
    import ticket_desk
    ans = _desk.capability().resolve(doc, "clara", "tickets", source)
    if not ans.on:
        raise SystemExit(ans.message.splitlines()[0] if ans.message else "ticket handling is not set up")
    ticket_desk.TEAM = ticket_desk.Team(doc, source)
    board = ticket_desk.load_board(None)
    line = next((w for w in ticket_desk.TEAM.lines if w.upper() in prefix), None)
    rel = ticket_desk.release_row(board, version if line is None else f"{line.upper()} {version}")
    release_ticket = next((r.get("releaseTicket") for r in rel if r.get("releaseTicket")), None)
    customers: dict[str, set[str]] = {}
    for t in ticket_desk.tickets(board):
        if t["frr"] and t["customer"]:
            customers.setdefault(t["frr"], set()).add(t["customer"])
    return release_ticket, customers, board


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    doc, source = _desk.load()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="check", choices=["check", "selftest"])
    ap.add_argument("--version")
    ap.add_argument("--prefix", default=_desk.fix_version_prefix(doc))
    projects = _desk.project_keys(doc, ("development",))
    ap.add_argument("--project", default=projects[0] if projects else None)
    ap.add_argument("--qat", nargs="*", default=[])
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    _desk.gate("rela", "readiness", doc, source)
    if not a.version:
        ap.error("--version is required")
    if not a.project or not a.prefix:
        print("tracker.projects (role development) and tracker.fix_version_pattern are not set in the desk "
              "settings; ask Olga to finish onboarding section rela-release", file=sys.stderr)
        return _desk.NOT_SET_UP
    configure(doc)
    import ticket_desk  # noqa: F401  (fails here, before any tracker call, when the tickets skill is missing)
    name = f"{a.prefix} {a.version}"
    jira = _desk.Tracker(doc)
    issues = search_all(jira, f'project = {a.project} AND fixVersion = "{name}" ORDER BY key ASC',
                        ["summary", "status", "assignee", "priority", RN_FIELD, EXCL_FIELD])
    version = next((v for v in jira.get(f"project/{a.project}/versions") if v.get("name") == name), None)
    try:
        release_ticket, customers, board = read_board(doc, source, a.version, a.prefix)
    except SystemExit as e:
        print(f"board not read ({e}); {RELEASE_PROJECT} ticket and customers unknown")
        release_ticket, customers = None, {}
        board = None
    case_prio: dict[str, str] = {}
    rank = {"blocker": 0, "highest": 0, "critical": 1, "high": 2, "major": 2, "medium": 3}
    if board:
        import ticket_desk
        internal = {s["id"] for s in ticket_desk.TEAM.sections_of("internal")}
        for t in ticket_desk.tickets(board):
            if t["frr"] and t["board"] not in internal and t["priority"]:
                old = case_prio.get(t["frr"])
                if old is None or rank.get(t["priority"].lower(), 9) < rank.get(old.lower(), 9):
                    case_prio[t["frr"]] = t["priority"]
    res = assess(issues, version, load_verdicts(a.qat), release_ticket, customers, case_prio)
    text = render(name, version, release_ticket, res)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0 if res["ready"] else 3


if __name__ == "__main__":
    sys.exit(main())
