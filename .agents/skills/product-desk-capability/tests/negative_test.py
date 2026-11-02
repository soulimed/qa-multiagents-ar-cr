"""A team without a capability is told "not set up -- ask Olga", and the generic desk carries no team's way.

    python tests/negative_test.py

1. Every capability of the template and of every product pack's desk file that
   has not been through Olga's agent sections answers not set up, names its
   onboarding section, points to Olga, and hands back no settings.
2. A team that switched a capability on gets its own values; a second team
   with the same capability off or missing gets none of them.
3. The generic desk surfaces -- the four desk profiles, the desk tactics and
   procedures, this skill -- name no RA LQR fact (projects, hosts, jobs,
   fields, chats, formats). Those live in the RA LQR pack's settings and skills.
4. A capability that is on but binds a skill or tactic that does not exist in
   the settings file's pack chain answers `unresolved` (exit 3 from `check`),
   names the missing one and hands back no settings; the same names placed in
   a pack the product extends resolve.
Exit 0 when all hold.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location("product_desk_capability", HERE.parent / "scripts" / "capability.py")
cap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cap
spec.loader.exec_module(cap)  # type: ignore[union-attr]

GENERIC = [
    *(ROOT / "pack" / "agent_profiles" / f"{p}.agent.yaml"
      for p in ("clerk-clara", "qa-qata", "release-rela", "onboarding-olga")),
    *(ROOT / "pack" / "tactics" / f"{t}.tactic.yaml"
      for t in ("release-notes-authoring", "evidence-verdict", "ticket-desk-queries",
                "product-desk-shared-conduct", "product-desk-consult-contract")),
    *(ROOT / "pack" / "procedures" / f"{p}.procedure.yaml"
      for p in ("release-notes-generation", "release-publish", "release-readiness", "release-announcement",
                "test-run-review", "fix-verification", "product-desk-onboarding")),
    ROOT / "pack" / "toolguides" / "product-desk-settings.md",
    ROOT / "pack" / "templates" / "product-desk" / "product-desk.template.yaml",
    ROOT / "pack" / "templates" / "product-desk" / "release-profile.template.yaml",
    ROOT / "pack" / "templates" / "product-desk" / "onboarding-progress.template.yaml",
    HERE.parent / "SKILL.md",
    HERE.parent / "scripts" / "capability.py",
    HERE.parent / "scripts" / "settings_review.py",
]
# Facts that belong to the RA LQR team's settings and skills, never to the generic desk.
TEAM_FACTS = re.compile(
    r"RA LQR|RALQR|FRRALM|FRRREL|FRRAE|d-rr-rp-02|teamcity\.wkfs|Zoomin|Artifactory|RRiskH|"
    r"customfield_\d+|FRR - Release Management|RRH_DoD|RaLqrQat|prd-ra-liq-risk|Fixed issues|"
    r"Problem copied|Solution by source precedence|frr-rn\.ps1|push-confluence|ra-lqr-",
    re.I)


def main() -> int:
    fails: list[str] = []

    def expect(cond: bool, what: str) -> None:
        if not cond:
            fails.append(what)

    # 1. template and scaffolds: nothing on, every answer points to Olga and its section
    files = [ROOT / "pack" / "templates" / "product-desk" / "product-desk.template.yaml",
             *sorted((ROOT / "packs").glob("*/product-desk/product-desk.yaml"))]
    checked = 0
    for f in files:
        doc = cap._read(f)
        answered = {(a, c): cap.resolve(doc, a, c, str(f)) for a, s in cap.AGENTS.items() for c in s["caps"]}
        if any(x.on for x in answered.values()):
            continue    # a team that set something up; part 2 covers on/off between teams
        checked += 1
        for (a, c), x in answered.items():
            section = cap.AGENTS[a]["caps"][c]["section"]
            expect(x.state in ("not-set-up", "off", "old-schema", "agent-off"), f"{f.parent.parent.name} {a}.{c}: {x.state}")
            expect("Ask Olga" in x.message and section in x.message, f"{f.parent.parent.name} {a}.{c}: {x.message}")
            expect(not x.settings, f"{f.parent.parent.name} {a}.{c} handed back settings while not set up")
    expect(checked >= 3, f"expected the template and at least two scaffold teams, checked {checked}")

    # 2. one team's values never reach another team
    on_team = {"schema_version": "2.0", "product": {"id": "alpha"},
               "desk": {"rela": {"release_notes": {"status": "on", "source_jql": "project = ALPHA",
                                                   "sections": ["Change"], "format": "markdown"}},
                        "qata": {"qat": {"status": "on", "process": "nightly diff", "results": {"location": "x"}}},
                        "clara": {}}}
    off_team = {"schema_version": "2.0", "product": {"id": "beta"},
                "desk": {"rela": {"release_notes": {"status": "off"}}, "qata": {}, "clara": {}}}
    expect(cap.resolve(on_team, "rela", "release_notes").settings["sections"] == ["Change"], "alpha gets its own notes")
    for agent, c in (("rela", "release_notes"), ("qata", "qat")):
        x = cap.resolve(off_team, agent, c)
        expect(not x.on and not x.settings and "Olga" in x.message, f"beta borrowed alpha's {agent}.{c}")
    x = cap.resolve(off_team, "rela", "release_notes")
    expect(x.state == "off" and "does not use it" in x.message, "an off capability says the team does not use it")

    # 2b. Clara's ticket handling on the real template: on by default once the
    # tracker is set up, not set up without it, off when the team says so.
    t = cap._read(files[0])
    tracker = {**t["tracker"], "instance": "https://tracker.example", "read_tools": "tracker_*",
               "projects": [{"key": "GAMMA", "role": "development"}]}
    expect("status" not in (t["desk"]["clara"]["tickets"] or {}), "the template's tickets block carries no status")
    x = cap.resolve({**t, "tracker": tracker}, "clara", "tickets")
    expect(x.on, f"template + tracker set + no status: tickets on, got {x.state}")
    x = cap.resolve(t, "clara", "tickets")
    expect(x.state == "not-set-up" and "section tracker" in x.message and not x.settings,
           f"template, tracker TBD: tickets not set up, got {x.state}")
    off = {**t, "tracker": tracker,
           "desk": {**t["desk"], "clara": {**t["desk"]["clara"], "tickets": {"status": "off"}}}}
    x = cap.resolve(off, "clara", "tickets")
    expect(x.state == "off" and not x.settings, f"explicit off beats the tracker default, got {x.state}")
    others = [cap.resolve({**t, "tracker": tracker}, a, c) for a, s in cap.AGENTS.items() for c in s["caps"]
              if (a, c) != ("clara", "tickets")]
    expect(not any(o.on for o in others), "the tracker default switches on nothing but Clara's tickets")

    # 3. the generic desk names no team's facts
    for f in GENERIC:
        if not f.is_file():
            fails.append(f"generic surface missing: {f.relative_to(ROOT)}")
            continue
        text = f.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            m = TEAM_FACTS.search(line)
            if m and f.name != "negative_test.py":
                fails.append(f"{f.relative_to(ROOT)}:{n} names a team fact {m.group(0)!r}")

    # 4. a bound skill or tactic must resolve in the pack chain
    fails += unresolved_names()

    print("negative test:", "PASS" if not fails else "FAILED", f"({checked} settings files without a capability)")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


def unresolved_names() -> list[str]:
    fails: list[str] = []
    settings = ("schema_version: '2.0'\n"
                "product: {id: gamma, short_name: Gamma}\n"
                "desk:\n"
                "  agents: {release-rela: on}\n"
                "  clara: {}\n  qata: {}\n"
                "  rela:\n"
                "    documentation: {status: on, skill: SKILL, tactic: TACTIC}\n")
    with tempfile.TemporaryDirectory() as tmp:
        packs = Path(tmp) / "packs"
        product, domain = packs / "doctrine-product-reg-tax-gamma", packs / "doctrine-product-reg-tax"
        for repo, charter in ((product, "extends: doctrine-product-reg-tax\n"), (domain, "extends: doctrine-product\n")):
            (repo / "pack" / "tactics").mkdir(parents=True)
            (repo / "pack" / "org-charter.yaml").write_text("schema_version: '1'\n" + charter, encoding="utf-8")
        (domain / "skills" / "tax-docs").mkdir(parents=True)
        (domain / "skills" / "tax-docs" / "SKILL.md").write_text("---\nname: tax-docs\n---\n", encoding="utf-8")
        (domain / "pack" / "tactics" / "tax-docs-authoring.tactic.yaml").write_text("id: tax-docs-authoring\n",
                                                                                     encoding="utf-8")
        (product / "product-desk").mkdir()
        desk = product / "product-desk" / "product-desk.yaml"
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "SPEC_KITTY_PACK_HOME": str(Path(tmp) / "no-home")}
        script = HERE.parent / "scripts" / "capability.py"
        cases = (("ghost-docs", "tax-docs-authoring", 3, "skill `ghost-docs`"),
                 ("tax-docs", "ghost-authoring", 3, "tactic `ghost-authoring`"),
                 ("tax-docs", "tax-docs-authoring", 0, "is set up"),
                 ("tax-docs", "none", 0, "is set up"))
        for skill, tactic, rc_want, text in cases:
            desk.write_text(settings.replace("SKILL", skill).replace("TACTIC", tactic), encoding="utf-8")
            doc = cap._read(desk)
            x = cap.resolve(doc, "rela", "documentation", str(desk))
            run = subprocess.run([sys.executable, "-B", str(script), "check", "--agent", "rela", "--capability",
                                  "documentation", "--settings", str(desk)], capture_output=True, text=True,
                                 cwd=tmp, env=env)
            label = f"skill {skill}, tactic {tactic}"
            if run.returncode != rc_want or text not in run.stdout:
                fails.append(f"{label}: check exit {run.returncode}, want {rc_want}; {run.stdout.strip()}")
            if rc_want == 3 and (x.state != "unresolved" or x.on or x.settings or "Ask Olga" not in x.message
                                 or "rela-release" not in x.message):
                fails.append(f"{label}: {x.state} {x.message!r} settings={x.settings}")
            if rc_want == 0 and not x.on:
                fails.append(f"{label}: a name in a pack the product extends did not resolve: {x.message}")
        chain = [r.name for r in cap.pack_chain(doc, desk)]
        if chain[:2] != [product.name, domain.name]:
            fails.append(f"pack chain starts {chain}, want the product then the pack it extends")
    ralqr = ROOT / "packs" / "doctrine-product-reg-liquidity-ralqr" / "product-desk" / "product-desk.yaml"
    if ralqr.is_file():
        chain = [r.name for r in cap.pack_chain(cap._read(ralqr), ralqr)]
        want = ["doctrine-product-reg-liquidity-ralqr", "doctrine-product-reg-liquidity", ROOT.name]
        if [c for c in chain if c in want] != want:
            fails.append(f"RA LQR pack chain {chain}, want {want} in that order")
    return fails


if __name__ == "__main__":
    sys.exit(main())
