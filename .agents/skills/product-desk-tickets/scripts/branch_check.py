#!/usr/bin/env python3
"""Clara's branch check: is a ticket's change on each release line of the team's repos?

  ticket_desk.py branches <KEY> [<KEY> ...] [--fetch] [--jira]
  ticket_desk.py branches --release <version> [--fetch]   # tickets of a fix version on the board
  ticket_desk.py branches --jql "<JQL>" [--fetch]
  branch_check.py selftest

A ticket counts as on a branch when a commit reachable from that branch names its key in the
message (subject or body, anywhere). That also finds cherry-picks and squash merges, which carry
the key but not the original commit. It does not prove the change is complete: a ticket with
several commits shows every commit found, and a commit that forgot the key is not found.

Repos are read from local clones (read-only git; `--fetch` runs `git fetch` first). Which repos,
under which short names, comes from the team's settings: desk.clara.branch_check.products names
each product's repo id; code.repos gives its clone variable, project, slug and release lines.
A product marked `branches: resolve` (or `default`), or with no `branches` and no release lines
whose repo says `develop_branch: origin/HEAD` (or `default`), is read per run: the repo's default
develop branch (origin/HEAD, else the newest develop/*) and the newest release/*.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _desk  # noqa: E402

HOME = Path.home()
PRODUCTS: dict[str, dict] = {}
VERSION_PREFIX = re.compile(r"(?!)")
SEP_F, SEP_R = "\x1f", "\x1e"
RESOLVE = {"resolve", "default"}
DEFAULT_BRANCH = {"default", "origin/head", "head"}


def products_from(doc: dict | None) -> dict[str, dict]:
    """{short: {name, env, default, clone, branches}} from desk.clara.branch_check and code.repos."""
    bc = _desk.get(doc, "desk", "clara", "branch_check", default={}) or {}
    repos = {r.get("id"): r for r in _desk.get(doc, "code", "repos", default=[]) or [] if isinstance(r, dict)}
    clone_url = str(bc.get("clone_url") or "")
    out = {}
    for short, spec in (bc.get("products") or {}).items():
        spec = spec if isinstance(spec, dict) else {"repo": spec}
        repo = repos.get(spec.get("repo"), {})
        slug, project = str(repo.get("slug") or spec.get("repo") or short), str(repo.get("project") or "")
        lines = repo.get("release_lines")
        resolve = str(spec.get("branches") or "").strip().lower() in RESOLVE or (
            "branches" not in spec and not isinstance(lines, list)
            and str(repo.get("develop_branch") or "").strip().lower() in DEFAULT_BRANCH)
        branches = None if resolve else [
            (str(x["name"]), str(x["branch"])) for x in (lines if isinstance(lines, list) else []) if isinstance(x, dict)]
        out[str(short)] = {"name": str(spec.get("name") or short), "env": repo.get("clone_env") or "",
                           "default": HOME / "GIT" / slug,
                           "clone": clone_url.format(project=project.lower(), slug=slug.lower()) if clone_url else slug,
                           "branches": branches}
    return out


def configure(doc: dict | None, source: str = "") -> None:
    global VERSION_PREFIX
    PRODUCTS.clear()
    PRODUCTS.update(products_from(doc))
    prefix = _desk.fix_version_prefix(doc)
    VERSION_PREFIX = re.compile(rf"^{re.escape(prefix)}\s+") if prefix else re.compile(r"(?!)")


def git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip()
                           else f"git {args[0]} failed")
    return r.stdout


def _vkey(ref: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", ref.rsplit("/", 1)[-1])) or (0,)


def resolved_branches(repo: Path, name: str) -> tuple[list[tuple[str, str]], list[str]]:
    """The default develop branch and the newest release/* branch, plus notes worth stating."""
    notes = []
    head = git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False).strip()
    develop = head.replace("refs/remotes/", "", 1) if head else ""
    devs = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/develop/").split()
    if not develop and devs:
        develop = max(devs, key=_vkey)
        notes.append(f"{name}: the repo's default branch is not known locally; using the newest develop branch "
                     f"{develop} (run with --fetch to read the default)")
    newer = [d for d in devs if develop and _vkey(d) > _vkey(develop)]
    if newer:
        notes.append(f"{name}: {', '.join(sorted(newer, key=_vkey))} is newer than the default branch {develop}; "
                     f"it is not checked")
    rels = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/release/").split()
    out = [(develop.replace("origin/", "", 1), develop)] if develop else []
    if rels:
        rel = max(rels, key=_vkey)
        out.append((rel.replace("origin/", "", 1), rel))
    else:
        notes.append(f"{name}: no release/* branch found")
    return out, notes


def key_pattern(keys: list[str]) -> re.Pattern:
    alt = "|".join(re.escape(k.upper()) for k in sorted(set(keys), key=len, reverse=True))
    return re.compile(rf"(?<![A-Z0-9])({alt})(?!\d)", re.I)


def branch_commits(repo: Path, ref: str) -> list[dict]:
    raw = git(repo, "log", ref, f"--format=%H{SEP_F}%cs{SEP_F}%an{SEP_F}%s{SEP_F}%b{SEP_R}")
    out = []
    for rec in raw.split(SEP_R):
        parts = rec.strip("\n").split(SEP_F)
        if len(parts) >= 4:
            out.append({"sha": parts[0], "date": parts[1], "author": parts[2], "subject": parts[3],
                        "body": parts[4] if len(parts) > 4 else ""})
    return out


def match(keys: list[str], commits: list[dict]) -> dict[str, list[dict]]:
    pat, hits = key_pattern(keys), {k.upper(): [] for k in keys}
    for c in commits:
        for k in {m.group(1).upper() for m in pat.finditer(c["subject"] + "\n" + c["body"])}:
            hits[k].append(c)
    return hits


def columns(products: list[str], fetch: bool, repos: dict[str, Path] | None = None) -> tuple[list[dict], list[str]]:
    """One column per product branch, each with its repo, ref, tip and any reason it cannot be read."""
    cols, notes = [], []
    for p in products:
        spec = PRODUCTS[p]
        repo = (repos or {}).get(p) or Path((spec["env"] and os.environ.get(spec["env"])) or spec["default"])
        if not (repo / ".git").exists() and not (repo / "HEAD").exists():
            reason = f"repo not cloned at {repo} (git clone --no-checkout {spec['clone']} \"{repo}\")"
            for label, ref in spec["branches"] or [("develop", ""), ("release", "")]:
                cols.append({"product": p, "name": spec["name"], "label": label, "repo": repo, "ref": ref, "error": reason})
            continue
        if fetch:
            try:
                git(repo, "fetch", "origin", "--prune", "--quiet")
                if spec["branches"] is None:
                    git(repo, "remote", "set-head", "origin", "--auto", check=False)
            except RuntimeError as e:
                notes.append(f"{spec['name']}: fetch failed ({e}); the local copy is used")
        branches = spec["branches"]
        if branches is None:
            branches, extra = resolved_branches(repo, spec["name"])
            notes += extra
        for label, ref in branches:
            col = {"product": p, "name": spec["name"], "label": label, "repo": repo, "ref": ref, "error": None}
            tip = git(repo, "log", "-1", "--format=%h %cs", ref, check=False).split()
            if not tip:
                col["error"] = f"branch {ref} not found locally (run with --fetch)"
            else:
                col["tip"], col["tip_date"] = tip[0], tip[1]
            cols.append(col)
    last_fetch = {}
    for c in cols:
        fh = Path(c["repo"]) / ".git" / "FETCH_HEAD"
        if fh.exists() and c["product"] not in last_fetch:
            last_fetch[c["product"]] = dt.datetime.fromtimestamp(fh.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    for p, when in last_fetch.items():
        notes.insert(0, f"{PRODUCTS[p]['name']}: local clone last fetched {when}")
    return cols, notes


def check(keys: list[str], products: list[str], fetch: bool = False,
          repos: dict[str, Path] | None = None) -> dict:
    keys = [k.upper() for k in dict.fromkeys(keys)]
    cols, notes = columns(products, fetch, repos)
    cache: dict[tuple, list[dict]] = {}
    for c in cols:
        c["hits"] = {}
        if c["error"]:
            continue
        ck = (str(c["repo"]), c["ref"])
        if ck not in cache:
            cache[ck] = branch_commits(Path(c["repo"]), c["ref"])
        c["hits"] = {k: [{"sha": x["sha"][:10], "date": x["date"], "subject": x["subject"][:100]} for x in v]
                     for k, v in match(keys, cache[ck]).items() if v}
    return {"keys": keys, "columns": cols, "notes": notes}


def elsewhere(result: dict, key: str, limit: int = 5) -> list[str]:
    """Other remote branches (not the checked ones) that carry a commit naming the ticket."""
    out, seen = [], set()
    checked = {c["ref"] for c in result["columns"]}
    for c in result["columns"]:
        if c["error"] or str(c["repo"]) in seen:
            continue
        seen.add(str(c["repo"]))
        repo = Path(c["repo"])
        raw = git(repo, "log", "--remotes", "-F", f"--grep={key}", "--format=%H", check=False).split()
        pat = key_pattern([key])
        shas = [s for s in raw[:20]
                if pat.search(git(repo, "log", "-1", "--format=%s%n%b", s, check=False))][:3]
        for s in shas:
            br = [b.strip() for b in git(repo, "branch", "-r", "--contains", s, check=False).splitlines()
                  if b.strip() and "->" not in b and b.strip() not in checked]
            if br:
                more = f" (+{len(br) - limit} more)" if len(br) > limit else ""
                out.append(f"{c['name']} {s[:10]} is also on {', '.join(br[:limit])}{more}")
    return out


def short_version(v: str) -> str:
    return VERSION_PREFIX.sub("", v)


# ---------------------------------------------------------------- tracker (read-only)
def search_all(client, jql: str, fields: list[str], cap: int = 500) -> tuple[list[dict], bool]:
    """Every issue a JQL returns, each key once, up to `cap`; the flag says whether the cap cut it short."""
    return _desk.search_all(client, jql, fields, cap=cap)


def ticket_info(client, keys: list[str]) -> dict[str, dict]:
    info = {}
    for i in range(0, len(keys), 50):
        chunk = keys[i:i + 50]
        issues, _ = search_all(client, f"key in ({','.join(chunk)})", ["summary", "status", "fixVersions"], cap=50)
        for iss in issues:
            f = iss.get("fields") or {}
            info[iss["key"]] = {"summary": f.get("summary") or "", "status": (f.get("status") or {}).get("name") or "",
                                "fixVersions": [v["name"] for v in f.get("fixVersions") or []]}
    return info


# ---------------------------------------------------------------- render
def _head(c: dict) -> str:
    return f"{c['name']} {c['label']}"


def render(result: dict, info: dict[str, dict] | None = None, detail: bool = False, md: bool = False) -> str:
    cols, keys = result["columns"], result["keys"]
    lines = []
    lines.append("Branches checked:")
    for c in cols:
        where = c["error"] or f"{c['ref']} (tip {c['tip']} {c['tip_date']})"
        lines.append(f"  {_head(c)}: {where}")
    for n in result["notes"]:
        lines.append(f"  note: {n}")
    lines.append("")
    yes, dash = ("✓", "—") if md else ("yes", "-")
    if detail:
        for k in keys:
            t = (info or {}).get(k)
            lines.append(f"{k}" + (f" · {t['status']} · {', '.join(map(short_version, t['fixVersions'])) or 'no fix version'} · "
                                   f"{t['summary'][:80]}" if t else ""))
            missing = False
            for c in cols:
                if c["error"]:
                    lines.append(f"  {_head(c)}: not checked")
                    continue
                hits = c["hits"].get(k, [])
                if not hits:
                    missing = True
                    lines.append(f"  {_head(c)}: {dash} not on {c['ref']}")
                for h in hits[:4]:
                    lines.append(f"  {_head(c)}: {yes} {h['sha']} {h['date']} {h['subject'][:70]}")
                if len(hits) > 4:
                    lines.append(f"  {_head(c)}: … {len(hits) - 4} more commit(s)")
            if missing:
                other = elsewhere(result, k)
                if not any(c["hits"].get(k) for c in cols):
                    lines.append("  not on any checked branch" + (": found elsewhere" if other else
                                                                      "; no commit on any remote branch names it"))
                elif other:
                    lines.append("  other branches carrying it:")
                lines += [f"    {o}" for o in other]
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
    head = ["Ticket"] + (["Status", "Fix version"] if info else []) + [_head(c) for c in cols]
    rows = []
    for k in keys:
        t = (info or {}).get(k, {})
        cells = [k] + ([t.get("status", "?"), ", ".join(map(short_version, t.get("fixVersions", []))) or "-"]
                       if info else [])
        for c in cols:
            if c["error"]:
                cells.append("?")
            else:
                h = c["hits"].get(k)
                cells.append(f"{yes} {h[0]['date']}" if h else dash)
        rows.append(cells)
    if md:
        lines.append("| " + " | ".join(head) + " |")
        lines.append("|" + "---|" * len(head))
        lines += ["| " + " | ".join(r) + " |" for r in rows]
    else:
        w = [max(len(str(x)) for x in col) for col in zip(head, *rows)] if rows else [len(h) for h in head]
        lines.append("  ".join(h.ljust(n) for h, n in zip(head, w)))
        lines += ["  ".join(str(x).ljust(n) for x, n in zip(r, w)) for r in rows]
    found = sum(1 for k in keys if any(c["hits"].get(k) for c in cols))
    lines.append("")
    lines.append(f"{len(keys)} ticket(s); {found} have a commit on at least one checked branch. "
                 f"A date is the newest commit naming the ticket on that branch; '{dash}' means no commit names it.")
    return "\n".join(lines) + "\n"


def to_json(result: dict, info: dict | None) -> str:
    cols = [{k: (str(v) if isinstance(v, Path) else v) for k, v in c.items()} for c in result["columns"]]
    return json.dumps({"keys": result["keys"], "columns": cols, "notes": result["notes"], "tickets": info or {}},
                      indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- self-test (synthetic, offline)
SYNTHETIC = {
    "tracker": {"fix_version_pattern": "Demo Suite {v}"},
    "code": {"repos": [
        {"id": "core", "project": "GRP", "slug": "demo-core", "clone_env": "DEMO_CORE_REPO",
         "release_lines": [{"name": "v1", "branch": "origin/DEMO-1.0.0"}, {"name": "v2", "branch": "origin/DEMO-2.0.0"},
                           {"name": "v3", "branch": "origin/DEMO-3.0.0"}]},
        {"id": "side", "project": "GRP", "slug": "demo-side", "clone_env": "DEMO_SIDE_REPO"},
        {"id": "app", "project": "APP", "slug": "app", "clone_env": "DEMO_APP_REPO", "release_lines": "TBD"}]},
    "desk": {"clara": {"branch_check": {
        "status": "on", "clone_url": "ssh://git@example.invalid/{project}/{slug}.git",
        "products": {"co": {"repo": "core", "name": "Core"}, "si": {"repo": "side", "name": "Side"},
                     "ap": {"repo": "app", "name": "App", "branches": "resolve"}}}}},
}


def selftest() -> int:
    fails = []
    saved = (dict(PRODUCTS), VERSION_PREFIX)
    configure(SYNTHETIC)
    if PRODUCTS["co"]["clone"] != "ssh://git@example.invalid/grp/demo-core.git" or PRODUCTS["ap"]["branches"] is not None \
            or [b for b, _ in PRODUCTS["co"]["branches"]] != ["v1", "v2", "v3"]:
        fails.append(f"products from settings {PRODUCTS}")
    for label, spec, repo in (("branches: default", {"repo": "x", "branches": "default"}, {}),
                              ("develop_branch: origin/HEAD", {"repo": "x"}, {"develop_branch": "origin/HEAD"}),
                              ("develop_branch: default", {"repo": "x"}, {"develop_branch": "default"})):
        doc = {"code": {"repos": [{"id": "x", "slug": "x", **repo}]},
               "desk": {"clara": {"branch_check": {"products": {"x": spec}}}}}
        if products_from(doc)["x"]["branches"] is not None:
            fails.append(f"{label} must resolve the default branch")
    fixed = {"code": {"repos": [{"id": "x", "slug": "x", "develop_branch": "origin/develop"}]},
             "desk": {"clara": {"branch_check": {"products": {"x": {"repo": "x"}}}}}}
    if products_from(fixed)["x"]["branches"] is None:
        fails.append("develop_branch: origin/develop must not resolve")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        origin, co, ap = root / "origin", root / "co", root / "ap"

        def run(repo, *a):
            subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)

        def commit(repo, msg):
            run(repo, "commit", "--allow-empty", "-q", "-m", msg)

        for r in (origin,):
            r.mkdir()
            run(r, "init", "-q", "-b", "base")
            run(r, "config", "user.email", "t@t")
            run(r, "config", "user.name", "t")
            run(r, "config", "commit.gpgsign", "false")
        commit(origin, "init")
        run(origin, "checkout", "-q", "-b", "DEMO-1.0.0")
        commit(origin, "DEV-7405: v1 fix")
        commit(origin, "DEV-74: an older ticket with a prefix key")
        run(origin, "checkout", "-q", "-b", "DEMO-2.0.0", "base")
        commit(origin, "XYZ9 update\n\n(cherry picked) DEV-7405: v2 fix in the body")
        run(origin, "checkout", "-q", "-b", "DEMO-3.0.0", "base")
        commit(origin, "DEV-74050: a longer key must not match")
        run(origin, "checkout", "-q", "-b", "feature/DEV-7409", "base")
        commit(origin, "DEV-7409: not merged anywhere yet")
        run(origin, "checkout", "-q", "-b", "develop/7.19.0", "base")
        commit(origin, "DEV-6827")
        run(origin, "checkout", "-q", "-b", "develop/7.20.0", "base")
        run(origin, "checkout", "-q", "-b", "release/7.9.0", "base")
        run(origin, "checkout", "-q", "-b", "release/7.10.0", "base")
        commit(origin, "Issue: DEV-6827 released")
        run(origin, "checkout", "-q", "develop/7.19.0")
        for r in (co, ap):
            subprocess.run(["git", "clone", "-q", str(origin), str(r)], check=True, capture_output=True)
        res = check(["DEV-7405", "dev-74", "DEV-7409", "DEV-6827"], ["co", "ap"], repos={"co": co, "ap": ap})
        by = {(c["product"], c["label"]): c for c in res["columns"]}
        if [c["label"] for c in res["columns"] if c["product"] == "ap"] != ["develop/7.19.0", "release/7.10.0"]:
            fails.append(f"resolved columns {[c['label'] for c in res['columns'] if c['product'] == 'ap']} "
                         "(default develop + newest release by version, 7.10 > 7.9)")
        if not any("develop/7.20.0" in n and n.startswith("App:") for n in res["notes"]):
            fails.append("a develop branch newer than the default must be named in a note")
        if not by[("co", "v1")]["hits"].get("DEV-7405"):
            fails.append("subject key on v1")
        if not by[("co", "v2")]["hits"].get("DEV-7405"):
            fails.append("a key in the body (cherry-pick) must count")
        if by[("co", "v3")]["hits"].get("DEV-7405"):
            fails.append("DEV-74050 must not match DEV-7405")
        if len(by[("co", "v1")]["hits"].get("DEV-74", [])) != 1:
            fails.append(f"DEV-74 must match only its own commit: {by[('co', 'v1')]['hits'].get('DEV-74')}")
        if not (by[("ap", "develop/7.19.0")]["hits"].get("DEV-6827")
                and by[("ap", "release/7.10.0")]["hits"].get("DEV-6827")):
            fails.append("resolved develop and release hits")
        if any(c["hits"].get("DEV-7409") for c in res["columns"]):
            fails.append("an unmerged feature branch must not count")
        other = elsewhere(res, "DEV-7409")
        if not any("feature/DEV-7409" in o for o in other):
            fails.append(f"elsewhere should name the feature branch: {other}")
        if elsewhere(res, "DEV-7405"):
            fails.append(f"elsewhere must leave out the checked branches: {elsewhere(res, 'DEV-7405')}")
        if short_version("Demo Suite Lite 6.0.3") != "Lite 6.0.3" or short_version("Other 3.6.0") != "Other 3.6.0":
            fails.append("short version names")
        txt = render(res)
        if "DEV-7409" not in txt or "1 have" in txt:
            fails.append("table render")
        if "not on any checked branch: found elsewhere" not in render(res, detail=True):
            fails.append("detail render for an unmerged ticket")
        miss = check(["DEV-1"], ["si"], repos={"si": root / "nope"})
        if not all(c["error"] and "not cloned" in c["error"] for c in miss["columns"]) or "?" not in render(miss):
            fails.append("a missing repo must show as not checked, never as 'not on the branch'")
        run(co, "branch", "-r", "-d", "origin/DEMO-3.0.0")
        gone = check(["DEV-7405"], ["co"], repos={"co": co})
        if not [c for c in gone["columns"] if c["label"] == "v3" and "not found" in (c["error"] or "")]:
            fails.append("a missing branch must be reported")
    configure({})
    if PRODUCTS or short_version("Demo Suite 1.0") != "Demo Suite 1.0":
        fails.append("no settings must give no products and no version prefix")
    PRODUCTS.clear()
    PRODUCTS.update(saved[0])
    globals()["VERSION_PREFIX"] = saved[1]

    class S:
        def __init__(self):
            self.n = 0

        def post(self, url, timeout, json):
            self.n += 1
            more = self.n < 3
            return type("R", (), {"raise_for_status": lambda s: None,
                                  "json": lambda s: {"issues": [{"key": f"K-{self.n}"}],
                                                     "nextPageToken": "t" if more else None, "isLast": not more}})()

    cl = type("C", (), {"s": S(), "base": "https://x/"})()
    iss, cut = search_all(cl, "q", [], cap=500)
    if len(iss) != 3 or cut:
        fails.append(f"pagination {len(iss)} {cut}")
    cl2 = type("C", (), {"s": S(), "base": "https://x/"})()
    iss, cut = search_all(cl2, "q", [], cap=2)
    if not cut:
        fails.append("a capped search must say it was cut short")
    for f in fails:
        print("FAIL", f)
    print("selftest OK: release-line refs, body keys, key boundaries, resolved develop + latest release, newer-develop "
          "note, unmerged branch, missing repo/branch, products from settings, pagination"
          if not fails else "selftest FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:] == ["selftest"]:
        sys.exit(selftest())
    import ticket_desk
    sys.exit(ticket_desk.main(["branches", *sys.argv[1:]]))
