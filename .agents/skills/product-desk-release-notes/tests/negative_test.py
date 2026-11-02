#!/usr/bin/env python3
"""A team without Rela's release notes is told "not set up -- ask Olga"; nothing runs against a host it did not configure.

    python tests/negative_test.py

1. No settings, the template (status TBD), readiness off, release_notes off: every command
   refuses with exit 3, the onboarding message on stderr and nothing on stdout.
2. release_notes on but a value the command needs is missing: the command names the key and
   stops with exit 3; it never falls back to another team's value.
3. The field tool refuses a read-only archive and any host other than tracker.instance, before
   it reads a login file; readiness refuses a tracker URL on another host.
4. The page check and the customer variant stop on missing settings or missing logins, before
   any request; readiness reports the board unknown when Clara's tickets are not on.
5. This skill's SKILL.md, scripts and tools name no team fact (same pattern as the capability
   skill's negative test).
Exit 0 when all hold. Offline; invented values only; no credential is read or sent.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPTS = SKILL / "scripts"
ROOT = HERE.parents[3]
TEMPLATE = ROOT / "pack" / "templates" / "product-desk" / "product-desk.template.yaml"


def team_facts():
    f = ROOT / "skills" / "desk" / "product-desk-capability" / "tests" / "negative_test.py"
    spec = importlib.util.spec_from_file_location("capability_negative", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.TEAM_FACTS


def run(script: str, args: list[str], settings: str, tmp: Path, extra_env: dict | None = None) -> tuple[int, str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("JIRA_API_", "PRODUCT_DESK_", "CONFLUENCE_", "JIRA_CLOUD_"))}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", REGNOLOGY_MCP_HOME=str(tmp / "no-logins"),
               **(extra_env or {}))
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / script), "--settings", settings, *args],
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=180, cwd=str(tmp))
    return r.returncode, r.stdout, r.stderr


def main() -> int:
    fails: list[str] = []

    def expect(cond: bool, what: str) -> None:
        if not cond:
            fails.append(what)

    tracker = {"instance": "https://tracker.example", "read_tools": "tracker_*",
               "write_env_file": "no-such-folder/.env.tracker",
               "projects": [{"key": "GAMMA", "role": "development"}, {"key": "HELP", "role": "support"}],
               "fix_version_pattern": "Gamma {v}", "read_only_archives": ["https://archive.example/tracker"],
               "fields": {"release_notes": "cf_1", "exclude_from_release_notes": "cf_2"}}
    rn_on = {"status": "on", "source_jql": "project = GAMMA AND fixVersion = '{fix_version}'",
             "sections": ["What", "Fix"], "format": "markdown", "done_statuses": ["Done"],
             "exclude_value": "skip", "output_file": "Gamma-{v}-notes.md"}
    with tempfile.TemporaryDirectory(prefix="product-desk-rn-neg-") as t:
        tmp = Path(t)
        md = tmp / "Gamma-1.0-notes.md"
        md.write_text("# Gamma 1.0\n\n## Area\n\n### GAMMA-1\n\n**T**\n", encoding="utf-8")
        tpl = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))

        def write(name: str, doc: dict) -> str:
            p = tmp / name / "product-desk.yaml"
            p.parent.mkdir()
            p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            return str(p)

        def rela(tr=None, creds=None, wiki=None, **c):
            doc = {**tpl, "tracker": tr or tracker, "desk": {**tpl["desk"], "rela": {**tpl["desk"]["rela"], **c}}}
            if creds is not None:
                doc["credentials"] = creds
            if wiki is not None:
                doc["wiki"] = wiki
            return doc

        commands = [("readiness.py", ["--version", "1.0"]),
                    ("rn_export.py", ["export", "--md", str(md), "--format", "md", "--out", str(tmp / "o")]),
                    ("rn_export.py", ["variant", "--md", str(md), "--customer", "Z"]),
                    ("rn_export.py", ["page-check", "--page", "1", "--version", "1.0"]),
                    ("rn_tools.py", ["fields", "pull", "--version", "1.0"]),
                    ("rn_tools.py", ["--show", "fields", "push", "--version", "1.0", "--apply"]),
                    ("rn_tools.py", ["wiki", "--page", "1", "--body", "x.xml", "--version", "1.0"]),
                    ("rn_tools.py", ["confluence", "--md", str(md)]),
                    ("rn_tools.py", ["skeleton", "--version", "1.0"])]
        cases = {
            "no settings": "none",
            "the template": str(TEMPLATE),
            "both off": write("off", rela(readiness={"status": "off"}, release_notes={"status": "off"})),
        }
        for label, s in cases.items():
            for script, args in commands:
                rc, out, err = run(script, args, s, tmp)
                section = "product-desk-onboarding" if s == "none" else \
                    ("rela-release" if script == "readiness.py" else "rela-release-notes")
                expect(rc == 3 and "Ask Olga" in err and section in err and not out.strip(),
                       f"{label} {script} {args[:2]}: rc {rc}, out {out[:120]!r}, err {err[:200]!r}")
        rc, _, err = run("rn_tools.py", ["fields", "pull", "--version", "1.0"], cases["both off"], tmp)
        expect("does not use" in err, f"an off capability says the team does not use it: {err[:200]!r}")
        expect(not (tmp / "o").exists() and not list(tmp.glob("*.xml")), "a refused command wrote a file")

        # 2. release_notes on, a needed value missing -> named, exit 3
        bare = write("bare", rela(tr={k: v for k, v in tracker.items() if k != "fields"},
                                  release_notes={k: v for k, v in rn_on.items() if k != "exclude_value"}))
        rc, out, err = run("rn_tools.py", ["--show", "fields", "pull", "--version", "1.0"], bare, tmp)
        expect(rc == 3 and "credentials.jira_release_notes" in err and "ask Olga" in err and not out.strip(),
               f"missing login key: rc {rc}, err {err[:200]!r}")
        bare2 = write("bare2", rela(tr={k: v for k, v in tracker.items() if k != "fields"},
                                    release_notes={k: v for k, v in rn_on.items() if k != "exclude_value"},
                                    creds={"jira_release_notes": "x/.env.notes"}))
        rc, out, err = run("rn_tools.py", ["--show", "fields", "pull", "--version", "1.0"], bare2, tmp)
        expect(rc == 3 and "tracker.fields.release_notes" in err, f"missing field id: rc {rc}, err {err[:200]!r}")
        full = write("full", rela(release_notes=rn_on, readiness={"status": "on", "blockers": ["x"]},
                                  creds={"jira_release_notes": "x/.env.notes"}))
        no_excl = write("no-excl", rela(release_notes={k: v for k, v in rn_on.items() if k != "exclude_value"},
                                        creds={"jira_release_notes": "x/.env.notes"}))
        rc, out, err = run("rn_tools.py", ["--show", "fields", "pull", "--version", "1.0"], no_excl, tmp)
        expect(rc == 3 and "exclude_value" in err, f"missing exclude option: rc {rc}, err {err[:200]!r}")
        rc, out, err = run("rn_tools.py", ["--show", "wiki", "--page", "1", "--body", "x", "--version", "1"], full, tmp)
        expect(rc == 3 and "wiki.instance" in err, f"missing wiki host: rc {rc}, err {err[:200]!r}")

        # titles: the page title, section heading and intro come from settings; missing ones are named
        rc, out, err = run("rn_tools.py", ["skeleton", "--version", "1.0"], full, tmp)
        expect(rc == 3 and "release_notes.title" in err and "release_notes.section_heading" in err
               and not out.strip(), f"skeleton without titles: rc {rc}, out {out[:120]!r}, err {err[:200]!r}")
        titled = write("titled", rela(release_notes={**rn_on, "title": "Gamma {v} - Notes", "section_heading": "Fixes",
                                                     "intro": "Solved.", "wiki": {"page_title": "Gamma {v} page"}},
                                      creds={"wiki": "x/.env.wiki"}, wiki={"instance": "https://wiki.example"}))
        rc, out, err = run("rn_tools.py", ["skeleton", "--version", "1.0"], titled, tmp)
        expect(rc == 0 and out == "# Gamma 1.0 page\n\n**Fixes**\n\nSolved.\n\n",
               f"skeleton from settings: rc {rc}, out {out!r}, err {err[:200]!r}")
        rc, out, err = run("rn_tools.py", ["--show", "wiki", "--page", "1", "--body", "x", "--version", "1.0",
                                           "--title", "auto"], titled, tmp)
        expect(rc == 0 and '-Title "Gamma 1.0 page"' in out, f"wiki --title auto: rc {rc}, out {out[:300]!r}")
        rc, out, err = run("rn_tools.py", ["--show", "wiki", "--page", "1", "--body", "x", "--version", "1.0"],
                           titled, tmp)
        expect(rc == 0 and "-Title" not in out, f"wiki keeps the page title unless asked: {out[:300]!r}")
        untitled = write("untitled", rela(release_notes=rn_on, creds={"wiki": "x/.env.wiki"},
                                          wiki={"instance": "https://wiki.example"}))
        rc, out, err = run("rn_tools.py", ["--show", "wiki", "--page", "1", "--body", "x", "--version", "1.0",
                                           "--title", "auto"], untitled, tmp)
        expect(rc == 3 and "release_notes.wiki.page_title" in err, f"--title auto unset: rc {rc}, err {err[:200]!r}")
        rc, out, err = run("rn_tools.py", ["--show", "fields", "pull", "--version", "1.0"], full, tmp)
        expect(rc == 0 and "-SiteUrl https://tracker.example" in out and "-ProductTag Gamma" in out
               and "-RefuseHosts archive.example" in out and "-DoneStatuses Done" in out
               and "-ExcludeValue skip" in out, f"the field tool gets this team's values: {out[:400]!r}")

        # 3. host refusals, before any login file is read
        for site, words in (("https://archive.example/tracker", "is a read-only archive"),
                            ("https://other.example", "only https://tracker.example is configured")):
            rc, out, err = run("rn_tools.py", ["fields", "pull", "--version", "1.0", "--site", site], full, tmp)
            expect(rc != 0 and words in err + out and "env file not found" not in err + out,
                   f"site {site}: rc {rc}, err {err[-300:]!r}")
        rc, out, err = run("rn_tools.py", ["fields", "push", "--version", "1.0", "--apply"], full, tmp)
        expect(rc != 0 and "env file not found" in err + out, f"no login file: rc {rc}, err {err[-300:]!r}")
        fake = {"JIRA_API_URL": "https://other-host.example/rest/api/3", "JIRA_API_EMAIL": "nobody@example.org",
                "JIRA_API_TOKEN": "not-a-token"}
        rc, out, err = run("readiness.py", ["--version", "1.0"], full, tmp, fake)
        expect(rc != 0 and "refusing non-Cloud Jira host; only tracker.example is allowed" in err,
               f"readiness other host: rc {rc}, err {err[-300:]!r}")

        # 4. page check and variant stop before any request
        rc, out, err = run("rn_export.py", ["page-check", "--page", "1", "--version", "1.0"], full, tmp)
        expect(rc == 3 and "wiki.instance and credentials.wiki" in err, f"page check unset: rc {rc}, err {err[:200]!r}")
        wk = write("wiki", rela(release_notes=rn_on, creds={"wiki": "x/.env.wiki"},
                                wiki={"instance": "https://wiki.example"}))
        rc, out, err = run("rn_export.py", ["page-check", "--page", "1", "--version", "1.0"], wk, tmp)
        expect(rc == 1 and "wiki credentials not found" in err and ".env.wiki" in err and not out.strip(),
               f"page check no login: rc {rc}, err {err[:200]!r}")
        rc, out, err = run("rn_tools.py", ["wiki", "--page", "1", "--body", "x.xml", "--version", "1.0"], wk, tmp)
        expect(rc == 1 and "wiki push not run" in err, f"wiki push needs the page check: rc {rc}, err {err[:300]!r}")
        rc, out, err = run("rn_export.py", ["variant", "--md", str(md), "--customer", "Z"], full, tmp)
        expect(rc == 1 and "tracker.fields.organizations" in err, f"variant unset: rc {rc}, err {err[:200]!r}")
        sys.path.insert(0, str(SCRIPTS))
        import readiness
        doc = yaml.safe_load(Path(full).read_text(encoding="utf-8"))
        doc["desk"]["clara"] = {"tickets": {"status": "off"}}
        try:
            readiness.read_board(doc, full, "1.0", "Gamma")
            fails.append("readiness read a board with Clara's tickets off")
        except SystemExit as e:
            expect("off" in str(e) and "Ticket" in str(e), f"board refusal names the capability: {e}")

    # 5. no team facts in this skill
    facts = team_facts()
    files = [SKILL / "SKILL.md", *sorted(SCRIPTS.glob("*.py")), *sorted((SKILL / "tools").glob("*.*"))]
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8-sig").splitlines(), 1):
            m = facts.search(line)
            if m:
                fails.append(f"{f.relative_to(ROOT)}:{n} names a team fact {m.group(0)!r}")

    print("negative test:", "PASS" if not fails else f"FAILED ({len(fails)})")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
