#!/usr/bin/env python3
"""Parity: the generic release-notes desk with the RA LQR settings answers like the installed original.

    python tests/parity_test.py

Runs the original skill (`~/.claude/skills/ra-lqr-release-notes`, else the lqr-ai-hub copy; a
junction to a pack clone never counts as the original) and this copy, with RA LQR's product-desk.yaml, on the same invented inputs, and compares:

* the selftests, argument errors, and the no-credential / wrong-host stops of readiness.py;
* readiness end to end against a fake tracker (in a child process per side: the fake answers
  the search and the versions call) and the same invented board, core and UK lines;
* rn_export.py: export dry runs, md / docx / html files written, the customer variant against
  a fake tracker and an invented client map, the page check without a login file;
* the Node converters, byte for byte;
* the PowerShell field and wiki tools: the archive refusal, a missing login file, a login file
  without credentials, and the wiki tool's body checks (bad entity, malformed XML, missing body).
  Those checks all stop before any request; the wiki cases use a placeholder login file and an
  .invalid base URL, so nothing can reach a real host.

No credential is read (secret variables are dropped, REGNOLOGY_MCP_HOME is an empty folder, and
the page check runs with a temporary home); nothing is posted. The originals (and the skills they
import) are hashed before and after and must be unchanged. Exit 0 when every comparison passes
or differs only where listed as intentional.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
COPY = HERE.parent
ROOT = HERE.parents[3]
TICKETS = ROOT / "skills" / "desk" / "product-desk-tickets"
SETTINGS = ROOT / "packs" / "doctrine-product-reg-liquidity-ralqr" / "product-desk" / "product-desk.yaml"
SKILLS = Path.home() / ".claude" / "skills"
HUB = Path(os.environ.get("LQR_AI_HUB") or Path.home() / "GIT" / "lqr-ai-hub") / "LQR-Agents" / "skills"
SECRET_VARS = ("JIRA_", "CONFLUENCE_", "BITBUCKET_", "GITLAB_", "TEAMCITY_", "PRODUCT_DESK_")


def is_pack_copy(folder: Path) -> bool:
    """True when `folder` resolves to <pack>/skills/<name> of a pack clone (e.g. the junction the
    skills takeover put in ~/.claude/skills); comparing a copy with itself proves nothing."""
    try:
        real = folder.resolve()
    except OSError:
        return False
    return real.parent.name == "skills" and (real.parent.parent / "pack").is_dir()


def original(name: str) -> Path | None:
    for c in (SKILLS / name, HUB / name):
        if (c / "SKILL.md").is_file() and not is_pack_copy(c):
            return c
    return None


def tree_hash(folder: Path) -> tuple[int, str]:
    h, n = hashlib.sha256(), 0
    for f in sorted(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(str(f.relative_to(folder)).encode())
        h.update(f.read_bytes())
        n += 1
    return n, h.hexdigest()


def child_env(tmp: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(SECRET_VARS)}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0",
               REGNOLOGY_MCP_HOME=str(tmp / "no-mcp"), PRODUCT_DESK_SETTINGS=str(SETTINGS))
    env.update({k: str(v) for k, v in extra.items()})
    return env


def run(cmd: list[str], tmp: Path, cwd: Path | None = None, timeout: int = 240, **extra) -> tuple[int, str, str]:
    r = subprocess.run(cmd, env=child_env(tmp, **extra), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=str(cwd or tmp))
    return r.returncode, r.stdout, r.stderr


def py(script: Path, args: list[str], tmp: Path, **kw) -> tuple[int, str, str]:
    return run([sys.executable, "-B", str(script), *args], tmp, **kw)


def ps_error(text: str) -> str:
    """The thrown message of a PowerShell run, without the position block, whitespace collapsed."""
    msg = text.split("\nAt ", 1)[0]
    return " ".join(msg.split())


def last_line(text: str) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def tickets_board() -> dict:
    spec = importlib.util.spec_from_file_location("tickets_parity", TICKETS / "tests" / "parity_test.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    b = mod.board()
    b["roadmap"]["releases"][1]["releaseTicket"] = "FRRREL-78"
    return b


DRIVER = r'''
import json, sys
sys.dont_write_bytecode = True
side, mode, orig_rn, orig_qat, orig_td, copy_rn, copy_td, data = sys.argv[1:9]
sc = json.load(open(data, encoding="utf-8"))
CALLS = []

class Resp:
    def __init__(self, d): self.d = d
    def raise_for_status(self): pass
    def json(self): return self.d

class Sess:
    def post(self, url, json=None, timeout=None):
        CALLS.append(("POST", url.rsplit("/", 2)[-2] + "/" + url.rsplit("/", 1)[-1], json["jql"], sorted(json["fields"])))
        i = int(json.get("nextPageToken") or 0)
        pages = sc["pages"]
        d = {"issues": pages[i], "isLast": i + 1 >= len(pages)}
        if i + 1 < len(pages):
            d["nextPageToken"] = str(i + 1)
        return Resp(d)

class Fake:
    def __init__(self, *a, **k):
        self.s, self.base = Sess(), "https://tracker.invalid/rest/api/3/"
    def get(self, path, **params):
        CALLS.append(("GET", path, sorted(params.items())))
        if path.startswith("project/"):
            return sc["versions"]
        return sc["issues"].get(path.split("/", 1)[1], {})

board = sc.get("board")

def load_board(data):
    if board is None:
        raise SystemExit("no board data under <folder>: run the refresh")
    return board

if side == "orig":
    sys.path.insert(0, orig_qat)
    import _common
    _common.JiraCloud = Fake
    sys.path.insert(0, orig_td)
    import ticket_desk
    ticket_desk.load_board = load_board
    sys.path.insert(0, orig_rn)
else:
    sys.path.insert(0, copy_td)
    import _desk
    _desk.Tracker = Fake
    import ticket_desk
    ticket_desk.load_board = load_board
    sys.path.insert(0, copy_rn)
if mode == "readiness":
    import readiness
    rc = readiness.main(sc["args"])
else:
    import rn_export
    if side == "orig":
        rn_export.BOARD_CFG = __import__("pathlib").Path(sc["client_map"])
    else:
        rn_export.DOC, rn_export.SOURCE = _desk.load()
        rn_export.DOC["desk"]["rela"]["release_notes"]["customer_variant"]["client_map"] = sc["client_map"]
    rc = rn_export.main(sc["args"]) if mode == "main" else None
    if mode == "customers":
        print(json.dumps({k: sorted(v) for k, v in rn_export.customers_for(sc["keys"]).items()}, sort_keys=True))
    elif mode == "variant":
        ns = __import__("argparse").Namespace(md=sc["md"], customer=sc["customer"], apply=True)
        rc = rn_export.cmd_variant(ns)
print("rc", rc)
print("calls", json.dumps(CALLS))
'''


def main() -> int:
    orig = original("ra-lqr-release-notes")
    if orig is None:
        print("parity_test: SKIP (no installed ra-lqr-release-notes)")
        return 0
    deps = [p for p in (original("ra-lqr-qat"), original("ra-lqr-ticket-desk")) if p]
    if len(deps) < 2:
        print("parity_test: SKIP (the original needs ra-lqr-qat and ra-lqr-ticket-desk installed)")
        return 0
    qat, td = deps
    watched = [orig, qat, td]
    before = {p: tree_hash(p) for p in watched}
    O, C = orig / "scripts", COPY / "scripts"
    # The original imports its siblings from ~/.claude/skills; once those are retired the hub copies
    # found above stand in, on PYTHONPATH (an installed sibling still wins: it is inserted first).
    orig_path = os.pathsep.join(str(p / "scripts") for p in (td, qat))

    def opy(script: Path, args: list[str], tmp: Path, **kw) -> tuple[int, str, str]:
        return py(script, args, tmp, PYTHONPATH=orig_path, **kw)

    fails: list[str] = []
    notes: list[str] = []
    count = 0

    def same(tag: str, o, c, intentional: str = "") -> None:
        nonlocal count
        count += 1
        if o != c:
            if intentional:
                notes.append(f"{tag}: {intentional}")
            else:
                fails.append(f"{tag} differs\n  original: {str(o)[:700]}\n  copy:     {str(c)[:700]}")

    with tempfile.TemporaryDirectory(prefix="product-desk-rn-parity-") as t:
        tmp = Path(t)
        (tmp / "no-mcp").mkdir()

        # ---------------------------------------------------------------- readiness.py
        same("readiness selftest", opy(O / "readiness.py", ["selftest"], tmp)[:2], py(C / "readiness.py", ["selftest"], tmp)[:2])
        for args in ([], ["bogus"], ["--version", "5.13.0"]):
            o, c = opy(O / "readiness.py", args, tmp), py(C / "readiness.py", args, tmp)
            same(f"readiness {' '.join(args) or '(no args)'}", (o[0], last_line(o[2])), (c[0], last_line(c[2])))
        fake = {"JIRA_API_URL": "https://other-host.example/rest/api/3", "JIRA_API_EMAIL": "nobody@example.org",
                "JIRA_API_TOKEN": "not-a-token"}
        o = opy(O / "readiness.py", ["--version", "5.13.0"], tmp, **fake)
        c = py(C / "readiness.py", ["--version", "5.13.0"], tmp, **fake)
        same("readiness other tracker host", (o[0], last_line(o[2])), (c[0], last_line(c[2])))

        board = tickets_board()
        iss = lambda key, cat, status, rn=None, excl=None, prio="Major", who="Dev A": {  # noqa: E731
            "key": key, "fields": {"summary": f"summary of {key}", "status": {"name": status, "statusCategory": {"key": cat}},
                                   "assignee": {"displayName": who} if who else None, "priority": {"name": prio},
                                   "customfield_18655": rn, "customfield_18673": excl}}
        adf = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "From now on x."}]}]}
        pages = [[iss("FRRALM-101", "indeterminate", "In Progress", prio="Major"),
                  iss("FRRALM-102", "done", "Closed", rn="Fixed y."),
                  iss("FRRALM-104", "done", "Tested")],
                 [iss("FRRALM-201", "done", "Resolved", excl=[{"value": "exclude"}]),
                  iss("FRRALM-202", "done", "Implemented", rn=adf, who=None),
                  iss("FRRALM-301", "new", "Open", prio="Minor", who=None)]]
        versions = [{"name": "Regulatory Analytics LQR 6.1.0", "releaseDate": "2026-11-30", "released": False},
                    {"name": "Regulatory Analytics LQR UK 6.1.0", "released": False}]
        (tmp / "q1.yaml").write_text("verdict: PASS\nrun: r1\ncommit: abc\nevidence: all green\n"
                                     "tickets:\n  FRRALM-102: PASS\n  FRRALM-104: FAIL\n", encoding="utf-8")
        (tmp / "q2.yaml").write_bytes("verdict: CANNOT TELL\nrun: r2\nevidence: watchdog missing a day\n"
                                      .encode("utf-16"))
        (tmp / "drv.py").write_text(DRIVER, encoding="utf-8")
        dirs = [str(O), str(qat / "scripts"), str(td / "scripts"), str(C), str(TICKETS / "scripts")]
        scenarios = {
            "core, two pages, verdicts": {"args": ["--version", "6.1.0", "--qat", str(tmp / "q1.yaml"), str(tmp / "q2.yaml"),
                                                   "--out", "OUT"], "pages": pages, "versions": versions},
            "UK line, no verdict": {"args": ["--version", "6.1.0", "--prefix", "Regulatory Analytics LQR UK"],
                                    "pages": [pages[0][:1]], "versions": versions},
            "clean release": {"args": ["--version", "6.1.0", "--qat", str(tmp / "q1.yaml").replace("q1", "q3")],
                              "pages": [[iss("FRRALM-102", "done", "Closed", rn="ok")]], "versions": versions},
            "unknown version, no board": {"args": ["--version", "9.9.9", "--project", "FRRALM"], "pages": [[]],
                                          "versions": versions, "board": None},
        }
        (tmp / "q3.yaml").write_text("verdict: PASS\nrun: r3\n", encoding="utf-8")
        for label, sc in scenarios.items():
            sc.setdefault("board", board)
            outs = []
            for side in ("orig", "copy"):
                s = dict(sc, args=[a.replace("OUT", str(tmp / f"ready-{side}.md")) for a in sc["args"]])
                data = tmp / f"sc-{side}.json"
                data.write_text(json.dumps(s), encoding="utf-8")
                rc, out, err = run([sys.executable, "-B", str(tmp / "drv.py"), side, "readiness", *dirs, str(data)], tmp)
                outs.append((rc, out.replace(str(tmp), "<tmp>").replace(f"ready-{side}", "ready-X"), last_line(err)))
            same(f"readiness end to end: {label}", outs[0], outs[1])
            want = {"core, two pages, verdicts": ["NOT READY", "Release ticket: FRRREL-77", "FRRALM-104: Qata verdict FAIL",
                                                  "Qata verdict CANNOT TELL", "support case Critical, blocking", "Alpha Bank"],
                    "UK line, no verdict": ["Release ticket: FRRREL-78", "no Qata verdict"],
                    "clean release": ["**READY**"],
                    "unknown version, no board": ["fix version not found", "FRRREL ticket and customers unknown"]}[label]
            if not all(w in outs[1][1] for w in want):
                fails.append(f"readiness end to end: {label} did not exercise {want}: {outs[1][1][:600]}")
        same("readiness --out file", (tmp / "ready-orig.md").read_text(encoding="utf-8"),
             (tmp / "ready-copy.md").read_text(encoding="utf-8"))

        # ---------------------------------------------------------------- rn_export.py
        same("rn_export selftest", opy(O / "rn_export.py", ["selftest"], tmp)[:2], py(C / "rn_export.py", ["selftest"], tmp)[:2])
        md_text = ("# RRiskH Regulatory Analytics LQR 6.1.0 — Fixed issues\n\nIssues solved in this release.\n\n---\n\n"
                   "## LCR\n\n### FRRALM-101\n\n**Outflow for retail deposits**\n\n**Problem**\nThe `C 73.00` row 0035 was wrong.\n\n"
                   "**Solution**\nFrom now on the row uses **the stable share**.\n\n- one\n- two\n\n"
                   "### FRRALM-102\n\n**Second**\n\n**Problem**\nx & y < z\n\n---\n\n## NSFR\n\n### FRRALM-201\n\n**Third**\n\n---\n\n"
                   "## Internal / excluded from customer notes\n\n- FRRALM-301 test only\n")
        for side in ("orig", "copy"):
            d = tmp / f"md-{side}"
            d.mkdir()
            (d / "RA-LQR-6.1.0-Fixed-issues.md").write_text(md_text, encoding="utf-8")
        mdo, mdc = tmp / "md-orig" / "RA-LQR-6.1.0-Fixed-issues.md", tmp / "md-copy" / "RA-LQR-6.1.0-Fixed-issues.md"
        # a printed PDF carries its own id and timestamp, so only its size line varies
        norm = lambda s, side: re.sub(r"\(\d+(?:\.\d+)? KB\)", "(n KB)", s.replace(  # noqa: E731
            str(tmp / f"md-{side}"), "<dir>").replace(str(tmp / f"out-{side}"), "<out>"))
        for fmt in ("md", "docx", "html", "pdf"):
            for extra in ([], ["--out", "OUT"]):
                res = []
                for side, md in (("orig", mdo), ("copy", mdc)):
                    a = ["export", "--md", str(md), "--format", fmt] + [x.replace("OUT", str(tmp / f"out-{side}")) for x in extra]
                    rc, out, err = py((O if side == "orig" else C) / "rn_export.py", a, tmp)
                    res.append((rc, norm(out, side), last_line(err)))
                same(f"export --format {fmt} {' '.join(extra)} (dry run)", res[0], res[1])
        for fmt in ("md", "docx", "html"):
            res = []
            for side, md in (("orig", mdo), ("copy", mdc)):
                a = ["export", "--md", str(md), "--format", fmt, "--out", str(tmp / f"out-{side}"), "--apply"]
                rc, out, err = py((O if side == "orig" else C) / "rn_export.py", a, tmp, timeout=300)
                res.append((rc, norm(out, side)))
            same(f"export --format {fmt} --apply", res[0], res[1])
        same("export md file", (tmp / "out-orig" / mdo.name).read_bytes(), (tmp / "out-copy" / mdc.name).read_bytes())
        try:
            from docx import Document

            def paras(p: Path):
                return [(x.style.name, x.text, [r.bold for r in x.runs]) for x in Document(str(p)).paragraphs]
            same("export docx paragraphs", paras(tmp / "out-orig" / (mdo.stem + ".docx")),
                 paras(tmp / "out-copy" / (mdc.stem + ".docx")))
        except ImportError:
            notes.append("docx paragraphs: python-docx missing, not compared")
        ho, hc = tmp / "out-orig" / (mdo.stem + ".html"), tmp / "out-copy" / (mdc.stem + ".html")
        if ho.is_file() and hc.is_file():
            same("export html file", ho.read_text(encoding="utf-8"), hc.read_text(encoding="utf-8"))
        else:
            notes.append("export html file: not produced on this machine (no branding or no browser), not compared")

        for args in (["variant", "--md", str(mdo), "--customer", "Alpha Bank"], ["page-check", "--page", "1"], ["nope"]):
            o, c = opy(O / "rn_export.py", args, tmp), py(C / "rn_export.py", [a.replace("md-orig", "md-copy") for a in args], tmp)
            same(f"rn_export {args[0]} (no credentials / bad args)", (o[0], last_line(o[2])), (c[0], last_line(c[2])))

        home = tmp / "home"
        home.mkdir()
        o = opy(O / "rn_export.py", ["page-check", "--page", "1", "--version", "6.1.0"], tmp,
               USERPROFILE=home, HOME=home)
        c = py(C / "rn_export.py", ["page-check", "--page", "1", "--version", "6.1.0"], tmp,
               USERPROFILE=home, HOME=home)
        same("page-check without a login file", (o[0], last_line(o[2])), (c[0], last_line(c[2])),
             intentional="the original stops with a FileNotFoundError traceback; the copy names the missing "
                          "credentials in one line (same exit code 1, no request either way)")
        same("page-check without a login file: exit code", o[0], c[0])

        cfg = tmp / "config.yaml"
        cfg.write_text("clients:\n  - {name: Alpha Bank, organizations: [ALPHA Org, ' Shared Org ']}\n"
                       "  - {name: Beta Bank, organizations: [Beta Org]}\n"
                       "ae:\n  clients:\n    - {name: Delta Bank, organizations: [shared org, Delta Org]}\n", encoding="utf-8")
        link = lambda k, d="outwardIssue": {d: {"key": k}}  # noqa: E731
        fake_issues = {
            "FRRALM-101": {"fields": {"issuelinks": [link("SUP-11"), link("FRRRP-5"), link("SUP-12", "inwardIssue")]}},
            "FRRALM-102": {"fields": {"issuelinks": [link("SUP-13")]}},
            "FRRALM-201": {"fields": {"issuelinks": []}},
            "SUP-11": {"fields": {"customfield_10002": [{"name": "Alpha Org"}]}},
            "SUP-12": {"fields": {"customfield_10002": ["Shared Org", {"name": "Unknown Org"}]}},
            "SUP-13": {"fields": {"customfield_10002": [{"name": "Delta Org"}]}},
        }
        for mode, extra in (("customers", {"keys": ["FRRALM-101", "FRRALM-102", "FRRALM-201"]}),
                            ("variant", {"customer": "alpha"}), ("variant", {"customer": "Nobody"})):
            outs = []
            for side, md in (("orig", mdo), ("copy", mdc)):
                data = tmp / f"cv-{side}.json"
                data.write_text(json.dumps({"issues": fake_issues, "client_map": str(cfg), "md": str(md), **extra}),
                                encoding="utf-8")
                rc, out, err = run([sys.executable, "-B", str(tmp / "drv.py"), side, mode, *dirs, str(data)], tmp)
                outs.append((rc, norm(out, side), last_line(err)))
            same(f"customer variant ({mode} {extra.get('customer', '')})", outs[0], outs[1])
            want = {"customers": '"FRRALM-101": ["Alpha Bank", "Unknown Org"]',
                    "alpha": "keep FRRALM-101", "Nobody": "no note for this customer"}[extra.get("customer", mode)]
            if want not in outs[1][1]:
                fails.append(f"customer variant {mode}: expected {want!r} in {outs[1][1][:400]}")
        vo, vc = mdo.with_name(mdo.stem + "-alpha.md"), mdc.with_name(mdc.stem + "-alpha.md")
        same("customer variant file", vo.read_text(encoding="utf-8") if vo.exists() else None,
             vc.read_text(encoding="utf-8") if vc.exists() else None)

        # ---------------------------------------------------------------- Node converters
        node = shutil.which("node")
        if node:
            brand = Path(os.environ.get("SPEC_KITTY_PACK_HOME", "")) / "doctrine-org" / "pack" / "templates" / "branding"
            for script, suffix, extra in (("md-to-confluence.mjs", ".xml", []), ("md-to-plain-html.mjs", ".html", []),
                                          ("md-to-branded-html.mjs", ".b.html", ["T", "S", str(brand)])):
                if extra and not brand.is_dir():
                    notes.append(f"{script}: no branding folder, not compared")
                    continue
                outs = []
                for side, folder in (("orig", orig), ("copy", COPY)):
                    target = tmp / f"node-{side}{suffix}"
                    more = ["Regnology — Regulatory Analytics"] if side == "copy" and extra else []
                    rc, out, err = run([node, str(folder / "tools" / script), str(mdo), str(target), *extra, *more], tmp)
                    outs.append((rc, target.read_bytes() if target.exists() else err))
                same(f"node {script}", outs[0], outs[1])
            if brand.is_dir():
                target = tmp / "node-copy-default.html"
                run([node, str(COPY / "tools" / "md-to-branded-html.mjs"), str(mdo), str(target), "T", "S", str(brand)], tmp)
                same("node md-to-branded-html.mjs without a footer", (tmp / "node-orig.b.html").read_bytes(),
                     target.read_bytes() if target.exists() else b"",
                     intentional="the copy's default footer is plain 'Regnology'; RA LQR's settings pass its product-line footer")
        else:
            notes.append("node converters: node not on PATH, not compared")

        # ---------------------------------------------------------------- PowerShell tools
        psh = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
        frr = [*psh, str(orig / "tools" / "frr-rn.ps1")]
        tools = [sys.executable, "-B", str(C / "rn_tools.py")]
        missing = tmp / "no-mcp" / ".env.regnology-cloud-confluence"
        empty_dir = tmp / "empty-login"
        empty_dir.mkdir()
        (empty_dir / ".env.regnology-cloud-confluence").write_text("SOMETHING_ELSE=1\n", encoding="utf-8")
        cases = [
            ("field tool: read-only archive", frr + ["-Command", "pull", "-Version", "6.1.0", "-SiteUrl", "https://jira.frrdev.com/jira"],
             tools + ["fields", "pull", "--version", "6.1.0", "--site", "https://jira.frrdev.com/jira"], {}),
            ("field tool: missing login file", frr + ["-Command", "pull", "-Version", "6.1.0", "-EnvFile", str(missing)],
             tools + ["fields", "pull", "--version", "6.1.0"], {}),
            ("field tool push: missing login file", frr + ["-Command", "push", "-Version", "6.1.0", "-EnvFile", str(missing), "-Apply"],
             tools + ["fields", "push", "--version", "6.1.0", "--apply"], {}),
            ("field tool: login file without credentials",
             frr + ["-Command", "pull", "-Version", "6.1.0", "-EnvFile", str(empty_dir / ".env.regnology-cloud-confluence")],
             tools + ["fields", "pull", "--version", "6.1.0"], {"REGNOLOGY_MCP_HOME": empty_dir}),
        ]
        placeholder = tmp / "placeholder.env"
        placeholder.write_text("CONFLUENCE_CLOUD_EMAIL=nobody@example.org\nCONFLUENCE_CLOUD_API_TOKEN=not-a-token\n",
                               encoding="utf-8")
        (tmp / "bad-entity.xml").write_text("<p>a &mdash; b</p>", encoding="utf-8")
        (tmp / "malformed.xml").write_text("<p>unclosed", encoding="utf-8")
        common = ["-PageId", "1", "-BaseUrl", "https://wiki.invalid/wiki"]
        labels = ["-Labels", "prd-ra-liq-risk,doc-rn,doc"]
        for label, body, env_file in (("missing login file", tmp / "bad-entity.xml", missing),
                                      ("login file without credentials", tmp / "bad-entity.xml", empty_dir / ".env.regnology-cloud-confluence"),
                                      ("bad entity", tmp / "bad-entity.xml", placeholder),
                                      ("malformed XML", tmp / "malformed.xml", placeholder),
                                      ("missing body", tmp / "no-body.xml", placeholder)):
            args = [*common, "-BodyFile", str(body), "-EnvFile", str(env_file)]
            cases.append((f"wiki tool: {label}", [*psh, str(orig / "tools" / "push-confluence.ps1"), *args],
                          [*psh, str(COPY / "tools" / "wiki-push.ps1"), *args, *labels], {}))
        for label, ocmd, ccmd, extra in cases:
            o, c = run(ocmd, tmp, **extra), run(ccmd, tmp, **extra)
            same(label, (o[0] != 0, ps_error(o[2] or o[1])), (c[0] != 0, ps_error(c[2] or c[1])))

    after = {p: tree_hash(p) for p in watched}
    unchanged = after == before
    if not unchanged:
        fails.append("an original changed: " + ", ".join(str(p) for p in watched if after[p] != before[p]))
    print(f"parity_test: originals {', '.join(f'{p.name} ({before[p][0]} files)' for p in watched)}; all unchanged: {unchanged}")
    print(f"parity_test: {count} comparisons, copy with settings {SETTINGS.name}: "
          f"{'PASS' if not fails else f'FAILED ({len(fails)})'}")
    for f in fails:
        print("  -", f)
    for n in notes:
        print("  intentional:", n)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
