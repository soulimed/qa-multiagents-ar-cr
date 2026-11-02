#!/usr/bin/env python3
"""A team without Clara's ticket handling is told "not set up -- ask Olga"; nobody borrows another team's way.

    python tests/negative_test.py

1. No settings, the template (tracker TBD), tickets off, branch_check off: every command
   refuses with exit 3, the onboarding message on stderr and nothing on stdout.
2. Tickets on but no board set up: the board command stops with the onboarding pointer,
   it never falls back to another team's board.
3. A second team with tickets on but its own (or no) families, prefixes and topic sources
   gets none of the first team's.
4. The tracker client refuses a host that is not the team's tracker.instance, and a team
   with no tracker.instance, before any request.
5. This skill's SKILL.md and scripts name no team fact (same pattern as the capability
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
SCRIPTS = HERE.parent / "scripts"
ROOT = HERE.parents[3]
TEMPLATE = ROOT / "pack" / "templates" / "product-desk" / "product-desk.template.yaml"


def team_facts():
    f = ROOT / "skills" / "desk" / "product-desk-capability" / "tests" / "negative_test.py"
    spec = importlib.util.spec_from_file_location("capability_negative", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.TEAM_FACTS


def run(args: list[str], settings: str, extra_env: dict | None = None) -> tuple[int, str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("JIRA_API_", "PRODUCT_DESK_"))}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", **(extra_env or {}))
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "ticket_desk.py"), "--settings", settings, *args],
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    return r.returncode, r.stdout, r.stderr


def main() -> int:
    fails: list[str] = []

    def expect(cond: bool, what: str) -> None:
        if not cond:
            fails.append(what)

    tracker = {"instance": "https://tracker.example", "read_tools": "tracker_*",
               "write_env_file": "no-such-folder/.env.tracker",
               "projects": [{"key": "GAMMA", "role": "development"}], "fix_version_pattern": "Gamma {v}"}
    with tempfile.TemporaryDirectory(prefix="product-desk-tickets-neg-") as t:
        tmp = Path(t)
        board = tmp / "board.json"
        board.write_text('{"main": {"tickets": [{"frr": "GAMMA-1", "title": "T 73 broken", "client": "Z"}]}}',
                         encoding="utf-8")
        tpl = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))

        def write(name: str, doc: dict) -> str:
            p = tmp / name / "product-desk.yaml"
            p.parent.mkdir()
            p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            return str(p)

        clara = lambda **c: {**tpl, "tracker": tracker, "desk": {**tpl["desk"], "clara": {**tpl["desk"]["clara"], **c}}}  # noqa: E731
        cases = {
            "no settings": "none",
            "the template": str(TEMPLATE),
            "tickets off": write("off", clara(tickets={"status": "off"})),
        }
        for label, s in cases.items():
            for args in (["--data", str(board), "hygiene"], ["--data", str(board), "customer", "Z"],
                         ["--data", str(board), "release", "1.0", "--jira"]):
                rc, out, err = run(args, s)
                section = "product-desk-onboarding" if s == "none" else "clara-tickets"
                expect(rc == 3 and "Ask Olga" in err and section in err and not out.strip(),
                       f"{label} {args[2:]}: rc {rc}, out {out[:120]!r}, err {err[:200]!r}")
            rc, out, err = run(["branches", "GAMMA-1"], s)
            expect(rc == 3 and "Ask Olga" in err and not out.strip(), f"{label} branches: rc {rc}, err {err[:200]!r}")
        rc, _, err = run(["--data", str(board), "hygiene"], cases["tickets off"])
        expect("does not use" in err, f"an off capability says the team does not use it: {err[:200]!r}")

        bc_off = write("bc-off", clara(tickets={"status": "on", "data": {"sections": [{"id": "main", "kind": "customer"}]}},
                                       branch_check={"status": "off"}))
        no_board = write("no-board", clara(tickets={"status": "on"}))
        rc, out, err = run(["branches", "GAMMA-1"], bc_off)
        expect(rc == 3 and "Ask Olga" in err and not out.strip(), f"branch_check off: rc {rc}, err {err[:200]!r}")
        rc, out, _ = run(["--data", str(board), "hygiene"], bc_off)
        expect(rc == 0, f"tickets on, branch_check off: hygiene still answers (rc {rc})")
        bc_on = write("bc-on", clara(tickets={"status": "off"},
                                     branch_check={"status": "on", "repos": ["x"], "products": {}}))
        rc, out, err = run(["--data", str(board), "branches", "--release", "1.0"], bc_on)
        expect(rc == 3 and "Ask Olga" in err, f"branches --release needs tickets too: rc {rc}, err {err[:200]!r}")

        # 2. tickets on, no board set up
        rc, out, err = run(["hygiene"], no_board)
        expect(rc != 0 and "Ask Olga" in err and "clara-tickets" in err, f"no board: rc {rc}, err {err[:200]!r}")
        rc, out, err = run(["hygiene"], bc_off)
        expect(rc != 0 and "pass --data" in err and not out.strip(), f"no board folder: rc {rc}, err {err[:200]!r}")

        # 3. a second team borrows nothing
        rc, out, _ = run(["--data", str(board), "stale", "--days", "0"], bc_off)
        expect("probable group: no template family named" in out, f"no families of another team: {out[:300]!r}")
        rc, out, err = run(["--data", str(board), "topic", "NSFR"], bc_off)
        expect("search terms: NSFR" in out and "family" not in out, f"no topic sources of another team: {out[:300]!r}")
        rc, out, err = run(["--data", str(board), "cell", "SOME_CLASS"], bc_off)
        expect(rc != 0 and "Ask Olga" in err, f"no cell lookup of another team: rc {rc}, err {err[:200]!r}")

        # 4. the tracker client refuses other hosts, before any request
        fake = {"JIRA_API_URL": "https://other-host.example/rest/api/3", "JIRA_API_EMAIL": "nobody@example.org",
                "JIRA_API_TOKEN": "not-a-token"}
        roadmap = tmp / "roadmap.json"
        roadmap.write_text('{"plan": {"releases": [{"versionName": "Gamma 1.0", "releaseTicket": "GAMMA-9"}]}}',
                           encoding="utf-8")
        with_road = write("road", clara(tickets={"status": "on", "data": {"sections": [
            {"id": "main", "kind": "customer"}, {"id": "plan", "kind": "roadmap"}]}}))
        rc, out, err = run(["--data", str(roadmap), "release", "1.0", "--jira"], with_road, fake)
        expect(rc != 0 and "refusing non-Cloud Jira host; only tracker.example is allowed" in err,
               f"other host: rc {rc}, err {err[-300:]!r}")
        no_tracker = {**clara(tickets={"status": "on", "data": {"sections": [
            {"id": "main", "kind": "customer"}, {"id": "plan", "kind": "roadmap"}]}})}
        no_tracker["tracker"] = {**tracker, "instance": "TBD"}
        rc, out, err = run(["--data", str(roadmap), "release", "1.0", "--jira"], write("no-tracker", no_tracker), fake)
        expect(rc != 0 and "refusing" in err, f"no tracker.instance: rc {rc}, err {err[-300:]!r}")
        rc, out, err = run(["--data", str(roadmap), "release", "1.0", "--jira"], with_road)
        expect(rc != 0 and "credentials not found" in err and ".env.tracker" in err,
               f"no credentials: rc {rc}, err {err[-300:]!r}")

    # 5. no team facts in this skill
    facts = team_facts()
    for f in [HERE.parent / "SKILL.md", *sorted(SCRIPTS.glob("*.py"))]:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = facts.search(line)
            if m:
                fails.append(f"{f.relative_to(ROOT)}:{n} names a team fact {m.group(0)!r}")

    print("negative test:", "PASS" if not fails else f"FAILED ({len(fails)})")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
