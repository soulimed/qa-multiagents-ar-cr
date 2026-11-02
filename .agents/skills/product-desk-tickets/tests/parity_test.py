#!/usr/bin/env python3
"""Side-by-side parity: the installed ra-lqr-ticket-desk against product-desk-tickets with the
RA LQR desk settings (packs/doctrine-product-reg-liquidity-ralqr/product-desk/product-desk.yaml).

Both run the same commands on the same synthetic inputs and must give the same exit code,
stdout, stderr and written files:

  * customer, release, dupes, stale, hygiene, changed, digest, group on a synthetic board
  * cell (class, rule, cells) and topic, with the copy pinned to the original's class lookup
    and taxonomy file
  * release / topic / cell / group --jira with no credentials (both refuse the same way)
  * branches on throwaway synthetic git repos (three products, keys, --release, --md, --json,
    a missing clone)
  * argument errors

Intentional differences, reported and not failed:
  * the selftests: each passes on its own; the copy's uses invented names
  * cell and topic on the copy's own sources (this repo's class lookup and the ralqr pack's
    module taxonomy, the October build without the FINMA rows) are compared and any
    difference is listed

The original is only read and run in place, with bytecode writing off; the SHA-256 of every
file in it, in the original ra-lqr-liquidity-tools (installed, else the lqr-ai-hub copy) and in
the doctrine-liquidity pack it reads
is checked before and after. Nothing is posted: the children run without any tracker,
Bitbucket or Cursor credential variable and REGNOLOGY_MCP_HOME points at an empty folder.
Skipped with a message when the original is not installed.

    python parity_test.py [--original <ra-lqr-ticket-desk folder>]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
COPY = HERE.parent / "scripts"
REPO = HERE.parents[3]
SETTINGS = REPO / "packs" / "doctrine-product-reg-liquidity-ralqr" / "product-desk" / "product-desk.yaml"
INSTALLED = Path.home() / ".claude" / "skills"
HUB = Path.home() / "GIT" / "lqr-ai-hub"
CANDIDATES = [INSTALLED / "ra-lqr-ticket-desk", HUB / "LQR-Agents" / "skills" / "ra-lqr-ticket-desk"]
TOOLS = next((p for p in (INSTALLED / "ra-lqr-liquidity-tools", HUB / "LQR-Agents" / "skills" / "ra-lqr-liquidity-tools")
              if (p / "scripts" / "class_lookup.py").is_file()), INSTALLED / "ra-lqr-liquidity-tools")
ORIG_ENV: dict[str, str] = {}   # set by stage_original_home() when the original's siblings are not installed
SECRET_VARS = ("JIRA_API_", "BITBUCKET_PAT", "CURSOR_API_KEY", "PRODUCT_DESK_", "CONFLUENCE_", "GITLAB_PAT")
REPO_VARS = ("RA_LQR_CALCULATOR_REPO", "RA_AE_REPO", "FS_ALM_REPO")


# Commands only the copy has (the original has no counterpart); argparse names them in its usage
# and invalid-choice messages, and that is the only place an argument error may differ.
COPY_ONLY_COMMANDS = ("search",)


def without_copy_commands(r):
    code, out, err = r
    for c in COPY_ONLY_COMMANDS:
        err = err.replace(f",{c},", ",").replace(f", {c},", ",")
    return code, out, err


def digest(folder: Path | None) -> dict[str, str]:
    if folder is None or not folder.is_dir():
        return {}
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def child_env(tmp: Path, settings: Path | None, repos: dict[str, Path]) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(SECRET_VARS) and k not in REPO_VARS}
    # equal-size clusters print in set order, which follows the string hash; pin it so both sides agree
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0",
               REGNOLOGY_MCP_HOME=str(tmp / "no-mcp"), **{k: str(v) for k, v in repos.items()})
    if settings is not None:
        env["PRODUCT_DESK_SETTINGS"] = str(settings)
    return env


def run(folder: Path, args: list[str], tmp: Path, settings: Path | None, repos: dict[str, Path],
        script: str = "ticket_desk.py") -> tuple[int, str, str]:
    env = child_env(tmp, settings, repos)
    if folder != COPY:
        env.update(ORIG_ENV)
    r = subprocess.run([sys.executable, "-B", str(folder / script), *args], cwd=tmp,
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    err = re.sub(r'(File "[^"]+", line )\d+', r"\1N", r.stderr.replace(str(folder), "<scripts>"))
    return r.returncode, r.stdout.replace(str(folder), "<scripts>"), err


def stage_original_home(tmp: Path) -> None:
    """The original reads ra-lqr-liquidity-tools and ra-lqr-qat from ~/.claude/skills. When the
    lookup is no longer installed there (the hub skills were retired), run the original under a
    staged home holding copies of the hub originals, with LQR_AI_HUB still on the real hub."""
    if (INSTALLED / "ra-lqr-liquidity-tools" / "scripts" / "class_lookup.py").is_file():
        return
    home = tmp / "orig-home"
    for name, src in (("ra-lqr-liquidity-tools", TOOLS), ("ra-lqr-qat", HUB / "LQR-Agents" / "skills" / "ra-lqr-qat")):
        if (src / "scripts").is_dir():
            shutil.copytree(src, home / ".claude" / "skills" / name, ignore=shutil.ignore_patterns("__pycache__"))
    ORIG_ENV.update(HOME=str(home), USERPROFILE=str(home), LQR_AI_HUB=os.environ.get("LQR_AI_HUB") or str(HUB))


def original_pack() -> Path | None:
    """The doctrine-liquidity pack the original's taxonomy() reads on this machine."""
    for c in (os.environ.get("DOCTRINE_LIQUIDITY_PACK"),
              os.environ.get("SPEC_KITTY_PACK_HOME") and Path(os.environ["SPEC_KITTY_PACK_HOME"]) / "doctrine-liquidity" / "pack",
              Path.home() / "GIT" / "doctrine-liquidity" / "pack"):
        if c and (Path(c) / "assets").exists():
            return Path(c)
    return None


def board() -> dict:
    """An invented board in the export's shape: two customer sections, internal, roadmap."""
    today = dt.date.today()
    d = lambda n: (today - dt.timedelta(days=n)).isoformat()  # noqa: E731
    t = lambda **k: {"frr": "", "sup": "", "title": "", "client": "", "priority": "Major", "jiraStatus": "Open",  # noqa: E731
                     "supStatus": "", "frrStatus": "", "fixVersions": [], "planning": "", "assignee": "dev a",
                     "pipeline": "Jira opened", "ageDays": 10, "created": d(10), "supDescription": "",
                     "frrDescription": "", "frrUrl": "", "supUrl": "", **k}
    lqr = [t(frr="FRRALM-101", sup="SUP-11", title="RA LQR: [SF-1] C 73.00 outflow for retail deposits wrong",
             client="Alpha Bank", priority="Critical", fixVersions=["Regulatory Analytics LQR 6.1.0"], ageDays=120,
             created=d(120), frrDescription="C_73 row 0035 retail deposits"),
           t(frr="FRRALM-102", title="LCR: C 73.00 outflow for retail deposit wrong", client="Beta Bank",
             fixVersions=["Regulatory Analytics LQR 6.1.0"], assignee="", ageDays=95, created=d(95)),
           t(frr="FRRALM-103", sup="SUP-12", title="NSFR C 80.00 RSF factor for HQLA", client="Alpha Bank",
             priority="Blocker", fixVersions=[], ageDays=3, created=d(3)),
           t(frr="—", sup="SUP-13", title="PRA110 maturity ladder question", client="Gamma UK",
             pipeline="Still on support (no Jira)", ageDays=45, created=d(45), jiraStatus="", supStatus="Waiting"),
           t(frr="FRRALM-104", sup="SUP-14", title="ALMM C 66 counterbalancing capacity", client="Beta Bank",
             jiraStatus="Closed", frrStatus="Closed", supStatus="In Progress", fixVersions=["Regulatory Analytics LQR 6.0.3"]),
           t(frr="FRRALM-105", title="UK LCR template row fix", client="Gamma UK",
             fixVersions=["Regulatory Analytics LQR UK 6.1.0"], ageDays=20, created=d(1)),
           t(frr="FRRAE-9", title="excluded project", client="Alpha Bank")]
    ae = [t(frr="FRRALM-201", sup="SUP-21", title="RA AE: F 32.01 encumbered assets", client="Delta Bank",
            fixVersions=["Regulatory Analytics LQR 6.1.0"], ageDays=200, created=d(200),
            frrDescription="Asset Encumbrance template F_32"),
          t(frr="FRRALM-202", sup="SUP-21", title="RA AE: F 32.01 encumbered assets follow-up", client="Delta Bank",
            fixVersions=["Regulatory Analytics LQR 6.1.0"], ageDays=12)]
    internal = [{"key": "FRRALM-301", "summary": "C 73.00 outflow refactoring", "customer": "", "priority": "Critical",
                 "status": "In Progress", "fixVersions": ["Regulatory Analytics LQR 6.1.0"], "assignee": "dev b",
                 "origin": "internal", "module": "", "ageDays": 30, "created": d(30), "url": ""},
                {"key": "FRRALM-302", "summary": "C 73.00 outflow test pack", "customer": "", "priority": "Minor",
                 "status": "Done", "fixVersions": ["Regulatory Analytics LQR 6.1.0"], "assignee": "dev b",
                 "origin": "internal", "module": "LCR", "ageDays": 60, "created": d(60), "url": ""}]
    roadmap = [{"versionName": "Regulatory Analytics LQR 6.1.0", "date": "2026-11-30", "dateSource": "FRRREL due date",
                "released": False, "releaseTicket": "FRRREL-77"},
               {"versionName": "Regulatory Analytics LQR UK 6.1.0", "date": None, "dateSource": None,
                "released": False, "releaseTicket": None}]
    return {"lqr": {"asOf": "2026-10-09 06:00", "tickets": lqr}, "ae": {"asOf": "2026-10-09 06:00", "tickets": ae},
            "internal": {"tickets": internal}, "roadmap": {"releases": roadmap}}


def synthetic_repos(root: Path) -> dict[str, Path] | None:
    """One invented origin with every release line, cloned three times; None when git is missing."""
    if shutil.which("git") is None:
        return None
    env = {**os.environ, "GIT_AUTHOR_NAME": "Synthetic", "GIT_AUTHOR_EMAIL": "synthetic@example.org",
           "GIT_COMMITTER_NAME": "Synthetic", "GIT_COMMITTER_EMAIL": "synthetic@example.org",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}

    def git(repo, *a):
        subprocess.run(["git", "-C", str(repo), *a], env=env, capture_output=True, text=True, check=True)

    origin = root / "origin"
    origin.mkdir(parents=True)
    git(origin, "init", "-q", "-b", "base")
    git(origin, "config", "commit.gpgsign", "false")
    git(origin, "commit", "--allow-empty", "-q", "-m", "init")
    for branch, msgs in (("RALQR-4.0.0", ["FRRALM-101: v13 fix", "FRRALM-10: prefix key"]),
                         ("RALQR-5.0.0", ["LCR update\n\n(cherry picked) FRRALM-101: v14 fix"]),
                         ("RALQR-6.0.0", ["FRRALM-1010: longer key", "Merge LCR outflow fix FRRALM-301 into 6.0",
                                          "FRRALM-3020: longer key"]),
                         ("feature/v13", ["FRRALM-201: AE v13"]), ("feature/v14", []), ("feature/v15", ["FRRALM-201"]),
                         ("feature/FRRALM-102", ["FRRALM-102: not merged"]),
                         ("develop/7.19.0", ["FRRALM-103", "Merge LCR outflow fix FRRALM-301 into develop",
                                             "Refactor outflows\n\nReviewed with the team; relates to FRRALM-302 too"]),
                         ("develop/7.20.0", []),
                         ("release/7.9.0", []), ("release/7.10.0", ["Issue: FRRALM-103 released"])):
        git(origin, "checkout", "-q", "-b", branch, "base")
        for m in msgs:
            git(origin, "commit", "--allow-empty", "-q", "-m", m)
    git(origin, "checkout", "-q", "develop/7.19.0")
    out = {}
    for var, name in zip(REPO_VARS, ("ra", "ae", "fs")):
        subprocess.run(["git", "clone", "-q", str(origin), str(root / name)], env=env, capture_output=True, check=True)
        out[var] = root / name
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--original", help="the installed ra-lqr-ticket-desk folder")
    a = ap.parse_args(argv)
    root = Path(a.original) if a.original else next((p for p in CANDIDATES if (p / "scripts").is_dir()), None)
    if root is None or not (root / "scripts").is_dir():
        print("parity_test: SKIP -- the original ra-lqr-ticket-desk is not installed "
              f"(looked in {', '.join(str(p) for p in CANDIDATES)})")
        return 0
    orig = root / "scripts"
    lookup = TOOLS / "scripts" / "class_lookup.py"
    opack = original_pack()
    before = (digest(root), digest(TOOLS), digest(opack / "assets") if opack else {})
    fails: list[str] = []
    notes: list[str] = []
    n = 0

    def same(tag: str, o, c, intentional: bool = False):
        nonlocal n
        n += 1
        if o != c:
            (notes if intentional else fails).append(
                f"{tag} differs\n  original: {str(o)[:600]}\n  copy:     {str(c)[:600]}")

    with tempfile.TemporaryDirectory(prefix="product-desk-tickets-parity-") as t:
        tmp = Path(t)
        (tmp / "no-mcp").mkdir()
        stage_original_home(tmp)
        data = tmp / "board.json"
        data.write_text(json.dumps(board(), ensure_ascii=False), encoding="utf-8")
        watch = tmp / "watch.txt"
        watch.write_text("# watched\nFRRALM-101\nSUP-13\nFRRALM-999\n", encoding="utf-8")

        doc = yaml.safe_load(SETTINGS.read_text(encoding="utf-8"))
        tk = doc["desk"]["clara"]["tickets"]
        tk["cell_lookup"] = {"path": str(lookup)}
        if opack:
            tk["topic"]["taxonomy"] = str(opack / "assets" / "ra-lqr-module-taxonomy.md")
            tk["topic"]["functions"] = str(opack / "assets" / "ralqr-function-catalog.json")
        pinned = tmp / "pinned" / "product-desk.yaml"
        pinned.parent.mkdir()
        pinned.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

        repos = synthetic_repos(tmp / "git") or {}

        def both(args, tag, settings=SETTINGS, intentional=False, files=(), normalise=None):
            outs = []
            for folder, s in ((orig, None), (COPY, settings)):
                for f in files:
                    if f.exists():
                        f.unlink()
                r = run(folder, args, tmp, s, repos)
                if normalise and folder == COPY:
                    r = normalise(r)
                outs.append((r, *[f.read_text("utf-8").replace(str(tmp), "<tmp>") if f.exists() else None
                                  for f in files]))
            same(tag, outs[0], outs[1], intentional)
            return outs

        D = ["--data", str(data)]
        for args in (["customer", "Alpha"], ["customer", "Alpha", "--release", "6.1.0"], ["customer", "Nobody"],
                     ["release", "6.1.0"], ["release", "UK 6.1.0"], ["release", "9.9.9"],
                     ["dupes"], ["dupes", "--threshold", "0.5"], ["stale"], ["stale", "--days", "30"], ["hygiene"],
                     ["changed", "--customer", "Beta", "--release", "6.1.0"], ["digest", "--watch", str(watch)],
                     ["digest", "--since", "2", "--watch", str(watch)],
                     ["group"], ["group", "--board", "ae"], ["group", "--board", "internal", "--limit", "3"]):
            both(D + args, " ".join(args).replace(str(tmp), "<tmp>"))
        for args in (["release", "6.1.0", "--jira"], ["topic", "retail deposits", "--jira"], ["group", "--jira"]):
            both(D + args, f"{' '.join(args)} (no credentials)", settings=pinned)
        for args in (["cell", "C_73_00|0035|0010"], ["cell", "1234"], ["cell", "SYN_NO_SUCH_CLASS"],
                     ["cell", "BORROWING"], ["cell", "RESERVE"],
                     ["topic", "NSFR"], ["topic", "LCR"], ["topic", "retail deposits"], ["topic", "C_76"]):
            both(D + args, f"{' '.join(args)} (copy pinned to the original's lookup and taxonomy)", settings=pinned)
            both(D + args, f"{' '.join(args)} (copy on its own sources)", intentional=True)
        for args in (["changed", "--customer", "x"], ["group", "--board", "nope"], ["nope"], []):
            both(D + args, f"argument error {args}", normalise=without_copy_commands)
        for folder, label in ((orig, "original"), (COPY, "copy")):
            r = run(folder, ["selftest"], tmp, SETTINGS if folder == COPY else None, repos)
            n += 1
            if r[0] != 0:
                fails.append(f"{label} selftest failed: {r[1][-400:]} {r[2][-400:]}")
        notes.append("selftest output differs by design: the copy's selftest uses invented names; both pass")

        if not repos:
            notes.append("git not found: branches not compared")
        else:
            md, js = tmp / "b.md", tmp / "b.json"
            for args in (["branches", "FRRALM-101"], ["branches", "FRRALM-101", "frralm-10", "FRRALM-102", "FRRALM-103",
                                                       "FRRALM-201"],
                         ["branches", "FRRALM-101", "FRRALM-102", "--detail", "--md", str(md), "--json", str(js)],
                         ["branches", "FRRALM-103", "--products", "fs"], ["branches", "FRRALM-201", "--products", "ae,ra"],
                         ["--data", str(data), "branches", "--release", "6.1.0"],
                         ["--data", str(data), "branches", "--release", "UK 6.1.0", "--products", "ra,fs"],
                         ["branches", "--products", "ra"],
                         ["branches", "FRRALM-1", "--products", "zz"], ["branches", "not-a-key"],
                         ["branches", "FRRALM-1", "--jql", "project = X"], ["branches", "FRRALM-101", "--jira"]):
                both(args, " ".join(args).replace(str(tmp), "<tmp>"), files=(md, js) if "--md" in args else ())
            # A key in the middle of a subject, a key only in the body, and a key named nowhere.
            outs = both(["branches", "FRRALM-301", "FRRALM-302", "FRRALM-303", "--json", str(js)],
                        "branches: key mid-subject, key in the body, key nowhere", files=(js,))
            hits: dict[str, list[str]] = {}
            for c in json.loads(outs[1][1] or "{}").get("columns", []):
                for k, v in (c.get("hits") or {}).items():
                    hits.setdefault(k, []).extend(f"{c['product']} {c['label']}: {x['subject']}" for x in v)
            n += 1
            if not any(h.startswith("fs develop/7.19.0") for h in hits.get("FRRALM-301", [])) \
                    or not any(h.startswith("ra v15") for h in hits.get("FRRALM-301", [])):
                fails.append(f"a key in the middle of the subject must be found on develop and v15: {hits}")
            if not any(h.startswith("fs develop/7.19.0: Refactor outflows") for h in hits.get("FRRALM-302", [])) \
                    or any("FRRALM-3020" in h for h in hits.get("FRRALM-302", [])):
                fails.append(f"a key only in the body must be found, and a longer key must not match: {hits}")
            if hits.get("FRRALM-303"):
                fails.append(f"a key named in no commit must have no hits: {hits['FRRALM-303']}")
            # FS ALM's develop is the repo's default branch however the settings spell it.
            for label, edit in (("branches: default", lambda d: d["desk"]["clara"]["branch_check"]["products"]["fs"]
                                 .__setitem__("branches", "default")),
                                ("no branches key, code.repos develop_branch: origin/HEAD",
                                 lambda d: d["desk"]["clara"]["branch_check"]["products"]["fs"].pop("branches"))):
                vdoc = yaml.safe_load(SETTINGS.read_text(encoding="utf-8"))
                edit(vdoc)
                variant = tmp / "variant" / "product-desk.yaml"
                variant.parent.mkdir(exist_ok=True)
                variant.write_text(yaml.safe_dump(vdoc, sort_keys=False, allow_unicode=True), encoding="utf-8")
                both(["branches", "FRRALM-103", "--products", "fs"], f"branches on FS ALM with {label}",
                     settings=variant)
            saved = dict(repos)
            repos.update({k: tmp / "absent" / k for k in REPO_VARS})
            both(["branches", "FRRALM-101"], "branches with no clone (clone hint per product)")
            repos.clear()
            repos.update(saved)
            for folder, label in ((orig, "original"), (COPY, "copy")):
                r = run(folder, ["selftest"], tmp, SETTINGS if folder == COPY else None, repos, script="branch_check.py")
                n += 1
                if r[0] != 0:
                    fails.append(f"{label} branch_check selftest failed: {r[1][-400:]}")

    after = (digest(root), digest(TOOLS), digest(opack / "assets") if opack else {})
    for label, b, x in zip(("ra-lqr-ticket-desk", "ra-lqr-liquidity-tools", "doctrine-liquidity assets"), before, after):
        if b != x:
            fails.append(f"the original {label} changed during the test: {sorted(set(b.items()) ^ set(x.items()))[:5]}")
    print(f"parity_test: original {root} ({len(before[0])} files), ra-lqr-liquidity-tools ({len(before[1])} files), "
          f"doctrine-liquidity assets {opack} ({len(before[2])} files); all unchanged: {before == after}")
    print(f"parity_test: {n} comparisons, copy with settings {SETTINGS.name}:",
          "PASS" if not fails else f"FAILED ({len(fails)})")
    for f in fails:
        print("  -", f)
    for x in notes:
        print("  intentional:", x)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
