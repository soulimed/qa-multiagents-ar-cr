"""Is a desk capability set up for this team? The gate every desk agent and team skill asks first.

Clara, Qata and Rela carry no team's way of working. How a team handles
tickets, does QAT, cuts a release and writes release notes is in its desk
settings, product-desk.yaml, under desk.clara, desk.qata and desk.rela, one
block per capability with a `status`. Only `on` switches a capability on,
with one default: Clara's ticket handling (desk.clara.tickets) with no status
is on once the tracker section is set up; an explicit `off` still wins.
Anything else -- off, TBD, a missing block, an agent switched off, no settings
at all -- is answered with "not set up for <product>, ask Olga" and the
onboarding section that sets it up. Nothing falls back to another team.
A capability that binds a `skill` or `tactic` is on only when that name
resolves to a skill folder or tactic file in the settings file's pack chain;
otherwise it answers `unresolved`.

    python capability.py check --agent qata --capability qat [--settings F] [--product ID] [--json]
    python capability.py list [--settings F] [--product ID] [--json]
    python capability.py selftest

`check` exits 0 when the capability is on and complete, 3 when it is not set
up (the message says why and what to ask Olga), 2 on a usage error.
The settings file: --settings, else PRODUCT_DESK_SETTINGS, else the desk
settings lookup of toolguide product-desk-settings (PRODUCT_DESK_HOME, the
project's product-desk/, the registered packs' product-desk/). Several
products: --product <product.id>.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - reported at use
    yaml = None

HERE = Path(__file__).resolve().parent
UNSET = (None, "", "TBD", "tbd", [], {})
SCHEMA_MAJOR = 2
NOT_SET_UP, ON = 3, 0

# agent key -> profile id, name, and each capability: what it is called, the
# onboarding section that sets it up, the keys it cannot run without, and the
# capabilities it builds on.
AGENTS: dict[str, dict] = {
    "clara": {"profile": "clerk-clara", "name": "Clara", "caps": {
        "tickets": {"what": "Ticket handling", "section": "clara-tickets", "needs": [], "default_on": True},
        "lookup": {"what": "Granular ticket search", "section": "clara-tickets", "needs": ["skill", "command"]},
        "branch_check": {"what": "The release-branch check", "section": "clara-tickets", "needs": ["repos"]},
    }},
    "qata": {"profile": "qa-qata", "name": "Qata", "caps": {
        "qat": {"what": "QAT", "section": "qata-qat", "needs": ["process", "results.location"]},
        "fix_verification": {"what": "Fix verification", "section": "qata-qat", "needs": ["method"],
                             "builds_on": ["qat"]},
    }},
    "rela": {"profile": "release-rela", "name": "Rela", "caps": {
        "readiness": {"what": "The release-readiness check", "section": "rela-release", "needs": ["blockers"]},
        "release": {"what": "Release publishing", "section": "rela-release",
                    "needs": ["skill", "profiles_file", "steps", "approver"]},
        "release_notes": {"what": "Release-note generation", "section": "rela-release-notes",
                          "needs": ["source_jql", "sections", "format"]},
        "announcement": {"what": "The release announcement", "section": "rela-release", "needs": ["channel"]},
        "documentation": {"what": "Release documentation", "section": "rela-release", "needs": ["skill"]},
    }},
}
# A `default_on` capability with no status of its own is on once these tracker
# keys are set: the team's tracker section is enough to run it. An explicit
# status, `off` included, always wins.
TRACKER_NEEDS = ["instance", "read_tools", "projects"]
ALIASES = {k: k for k in AGENTS} | {v["profile"]: k for k, v in AGENTS.items()} \
    | {v["name"].lower(): k for k, v in AGENTS.items()}


@dataclass
class Answer:
    agent: str
    capability: str
    state: str                       # on | off | not-set-up | incomplete | unresolved | agent-off | no-settings | old-schema
    message: str
    settings: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def on(self) -> bool:
        return self.state == "on"

    def as_dict(self) -> dict:
        return {"agent": self.agent, "capability": self.capability, "state": self.state, "on": self.on,
                "message": self.message, "missing": self.missing, "source": self.source,
                "settings": self.settings}


def _get(d, dotted: str):
    for part in dotted.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def _status(block) -> str:
    if not isinstance(block, dict):
        return "TBD"
    s = block.get("status")
    if s is True:
        return "on"
    if s is False:
        return "off"
    return str(s).strip().lower() if s not in UNSET else "TBD"


def _ask_olga(section: str) -> str:
    return f"Ask Olga (Hey Olga) to run section {section} of procedure product-desk-onboarding."


def resolve(doc: dict | None, agent: str, capability: str, source: str = "",
            roots: list[Path] | None = None) -> Answer:
    """The one answer: the team's settings for this capability, or why it is not set up.

    `roots` are the pack repositories a bound `skill` or `tactic` must resolve
    in. Without it, they are the pack chain of the settings file `source`
    (pack_chain); a parsed dict with no file and no roots skips that check.
    """
    key = ALIASES.get(agent.lower())
    if key is None:
        raise ValueError(f"unknown desk agent {agent!r}; one of {', '.join(sorted(AGENTS))}")
    spec = AGENTS[key]
    if capability not in spec["caps"]:
        raise ValueError(f"{spec['name']} has no capability {capability!r}; one of {', '.join(spec['caps'])}")
    cap = spec["caps"][capability]
    what, section = cap["what"], cap["section"]

    def answer(state, msg, **kw):
        return Answer(key, capability, state, msg, source=source, **kw)

    if not isinstance(doc, dict) or not doc:
        return answer("no-settings", f"{what} is not set up: no desk settings were found for this project. "
                      + "Ask Olga (Hey Olga) to run procedure product-desk-onboarding.")
    names = [_get(doc, f"product.{k}") for k in ("short_name", "name", "id")]
    product = next((str(n) for n in names if n not in UNSET), "this product")
    major = str(doc.get("schema_version") or "1").split(".")[0]
    desk = doc.get("desk") if isinstance(doc.get("desk"), dict) else {}
    if not major.isdigit() or int(major) < SCHEMA_MAJOR or not isinstance(desk.get(key), dict):
        return answer("old-schema", f"{what} is not set up for {product}: its desk settings have no desk.{key} "
                      f"block (schema {doc.get('schema_version') or 'unknown'}; the per-agent shape is "
                      f"{SCHEMA_MAJOR}.0). " + _ask_olga(section))
    if _status({"status": (desk.get("agents") or {}).get(spec["profile"])}) == "off":
        return answer("agent-off", f"{spec['name']} is switched off for {product} (desk.agents). "
                      + _ask_olga(section))
    block = desk[key].get(capability)
    status = _status(block)
    undecided = not isinstance(block, dict) or block.get("status") in UNSET
    if cap.get("default_on") and undecided:
        missing = [f"tracker.{n}" for n in TRACKER_NEEDS if _get(doc, f"tracker.{n}") in UNSET]
        if missing:
            return answer("not-set-up", f"{what} switches on by itself once the tracker section is set up; for "
                          f"{product}, {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} still TBD. "
                          f"Ask Olga (Hey Olga) to run section tracker of procedure product-desk-onboarding "
                          f"(section {section} can switch it off or add the team's rules).", missing=missing)
        return answer("on", f"{what} is on for {product} by default: the tracker section is set up.",
                      settings=block if isinstance(block, dict) else {})
    if status == "off":
        return answer("off", f"{what} is off for {product}: the team does not use it. "
                      "If that has changed: " + _ask_olga(section))
    if status != "on":
        return answer("not-set-up", f"{what} is not set up for {product} yet. " + _ask_olga(section))
    for dep in cap.get("builds_on", []):
        dep_ans = resolve(doc, key, dep, source, roots)
        if not dep_ans.on:
            return answer("not-set-up", f"{what} for {product} builds on {AGENTS[key]['caps'][dep]['what']}, "
                          f"which is not on: {dep_ans.message}")
    missing = [n for n in cap["needs"] if _get(block, n) in UNSET]
    if missing:
        return answer("incomplete", f"{what} is on for {product} but {', '.join(missing)} "
                      f"{'is' if len(missing) == 1 else 'are'} still TBD. " + _ask_olga(section),
                      settings=block, missing=missing)
    chain = roots if roots is not None else (pack_chain(doc, Path(source)) if source and Path(source).is_file()
                                             else None)
    if chain is not None:
        lost = [(kind, name) for kind, name in bindings(block) if find(kind, name, chain) is None]
        if lost:
            names = ", ".join(f"{kind} `{name}`" for kind, name in lost)
            where = ", ".join(r.name for r in chain) or "no pack"
            return answer("unresolved", f"{what} is on for {product} but {names} "
                          f"{'does' if len(lost) == 1 else 'do'} not resolve to a "
                          f"{' or '.join(dict.fromkeys(KINDS[k] for k, _ in lost))} in its pack chain ({where}), "
                          "so it cannot run. Install or register the pack that ships it, or fix the name: "
                          + _ask_olga(section), missing=[f"{k}:{n}" for k, n in lost])
    return answer("on", f"{what} is set up for {product}.", settings=block)


# ---------------------------------------------------------------- do the bound names exist
KINDS = {"skill": "skill folder", "tactic": "tactic file"}
NO_BINDING = {"none", "n/a", "-"}


def bindings(block) -> list[tuple[str, str]]:
    """(kind, name) for the block's own `skill` and `tactic`; `none` binds nothing."""
    out = []
    for kind in KINDS:
        v = block.get(kind) if isinstance(block, dict) else None
        if v not in UNSET and str(v).strip().lower() not in NO_BINDING:
            out.append((kind, str(v).strip()))
    return out


def _is_repo(p: Path) -> bool:
    return (p / "pack" / "org-charter.yaml").is_file()


def _repo_of(path: Path) -> Path | None:
    for d in path.resolve().parents:
        if _is_repo(d):
            return d
    return None


def _named(name: str, near: list[Path]) -> Path | None:
    """The pack repository called `name`: beside a known one, under doctrine-product's packs/, or the pack home."""
    core = HERE.parents[3]
    cands = [core] if name == "doctrine-product" else []
    for base in near:
        cands += [base.parent / name, base / "packs" / name]
    cands.append(core / "packs" / name)
    home = os.environ.get("SPEC_KITTY_PACK_HOME")
    if home:
        cands += [Path(home) / name, Path(home) / "doctrine-product" / "packs" / name]
        if name == "doctrine-product":
            cands.append(Path(home) / "doctrine-product")
    return next((c.resolve() for c in cands if _is_repo(c)), None)


def pack_chain(doc: dict | None, source: Path | None = None) -> list[Path]:
    """Pack repositories a capability's skill and tactic resolve in, most specific first.

    The settings file's own pack, the packs it extends (org-charter `extends`,
    followed up), the packs under extensions.packs, the packs registered in the
    project's .kittify/config.yaml, then doctrine-product itself.
    """
    chain: list[Path] = []

    def add(repo: Path | None) -> None:
        if repo is not None and repo.resolve() not in chain:
            chain.append(repo.resolve())

    def extends(repo: Path) -> None:
        seen = 0
        while repo is not None and seen < 10:
            try:
                parent = (yaml.safe_load((repo / "pack" / "org-charter.yaml").read_text(encoding="utf-8")) or {}) \
                    .get("extends") if yaml else None
            except Exception:              # unreadable charter: the chain stops here
                parent = None
            repo = _named(str(parent), chain) if parent else None
            add(repo)
            seen += 1

    if source is not None:
        own = _repo_of(source)
        add(own)
        if own is not None:
            extends(own)
    for name in _get(doc or {}, "extensions.packs") or []:
        repo = _named(str(name), chain)
        add(repo)
        if repo is not None:
            extends(repo)
    consult = _consult()
    if consult is not None:
        for pack in consult.registered_packs(consult.project_root()):
            if (pack / "org-charter.yaml").is_file():
                add(pack.parent)
    core = HERE.parents[3]
    if _is_repo(core):
        add(core)
    return chain


def find(kind: str, name: str, chain: list[Path]) -> Path | None:
    """The skill folder or tactic file `name` in the chain (or installed beside this skill), else None."""
    if kind == "tactic":
        return next((f for r in chain for f in [r / "pack" / "tactics" / f"{name}.tactic.yaml"] if f.is_file()), None)
    places = [d for r in chain for d in [r / "skills" / name, *sorted((r / "skills").glob(f"*/{name}"))]]
    places += [HERE.parents[1] / name]          # installed flat beside this skill
    return next((d for d in places if (d / "SKILL.md").is_file()), None)


# ---------------------------------------------------------------- finding the settings
def _consult():
    """The consult skill's lookup (project root, registered packs), when it is installed beside this one."""
    for c in (HERE.parents[1] / "product-desk-consult", HERE.parents[2] / "product-desk-consult"):
        path = c / "scripts" / "handoff.py"
        if path.is_file():
            spec = importlib.util.spec_from_file_location("product_desk_handoff", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            return module
    return None


def _files_in(home: Path) -> list[Path]:
    return [p for p in [home / "product-desk.yaml", *sorted(home.glob("*/product-desk.yaml"))] if p.is_file()]


def settings_files() -> list[Path]:
    """Toolguide product-desk-settings' order, without any team's legacy fallback."""
    if os.environ.get("PRODUCT_DESK_HOME"):
        return _files_in(Path(os.environ["PRODUCT_DESK_HOME"]))
    consult = _consult()
    root = consult.project_root() if consult else Path.cwd()
    own = _files_in(root / "product-desk")
    if own or consult is None:
        return own
    return [f for d in consult.pack_desk_folders(root) for f in _files_in(d)]


def _read(path: Path) -> dict:
    if yaml is None:
        raise SystemExit("PyYAML is needed to read the desk settings: python -m pip install --user pyyaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load(explicit: str | None = None, product: str | None = None) -> tuple[dict | None, str]:
    explicit = explicit or os.environ.get("PRODUCT_DESK_SETTINGS")
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise SystemExit(f"desk settings not found: {p}")
        return _read(p), str(p)
    found = [(f, _read(f)) for f in settings_files()]
    if product:
        found = [(f, d) for f, d in found if str(_get(d, "product.id")) == product]
    if not found:
        return None, "no desk settings found" + (f" for product {product}" if product else "")
    if len(found) > 1:
        ids = ", ".join(str(_get(d, "product.id")) for _, d in found)
        raise SystemExit(f"several products have desk settings ({ids}); pass --product <id>")
    return found[0][1], str(found[0][0])


def every(doc: dict | None, source: str = "") -> list[Answer]:
    return [resolve(doc, a, c, source) for a, spec in AGENTS.items() for c in spec["caps"]]


# ---------------------------------------------------------------- self-test (synthetic, offline)
def _synthetic() -> dict:
    return {
        "schema_version": "2.0",
        "product": {"id": "demo", "short_name": "Demo"},
        "desk": {
            "agents": {"clerk-clara": "on", "qa-qata": "on", "release-rela": "on"},
            "clara": {"tickets": {"status": "on"}, "lookup": {"status": "TBD"},
                      "branch_check": {"status": "on", "repos": []}},
            "qata": {"qat": {"status": "off"}, "fix_verification": {"status": "on", "method": "rerun"}},
            "rela": {"release_notes": {"status": "on", "source_jql": "project = DEMO AND fixVersion = '{fix_version}'",
                                       "sections": ["What changed"], "format": "markdown"},
                     "release": {"status": "TBD"}},
        },
    }


def selftest() -> int:
    fails: list[str] = []

    def expect(cond: bool, what: str) -> None:
        if not cond:
            fails.append(what)

    doc = _synthetic()
    rn = resolve(doc, "release-rela", "release_notes")
    expect(rn.on and rn.settings["sections"] == ["What changed"], "an `on` capability returns the team's own settings")
    qat = resolve(doc, "Qata", "qat")
    expect(qat.state == "off" and "Ask Olga" in qat.message and "qata-qat" in qat.message,
           "an `off` capability points to Olga and its section")
    fv = resolve(doc, "qata", "fix_verification")
    expect(fv.state == "not-set-up" and "QAT" in fv.message, "fix verification without QAT is not set up")
    lk = resolve(doc, "clara", "lookup")
    expect(lk.state == "not-set-up" and "clara-tickets" in lk.message, "a TBD capability is not set up")
    bc = resolve(doc, "clara", "branch_check")
    expect(bc.state == "incomplete" and bc.missing == ["repos"] and not bc.on, "an `on` capability with a TBD need")
    ann = resolve(doc, "rela", "announcement")
    expect(ann.state == "not-set-up", "a missing block is not set up")
    old = resolve({"schema_version": "1.0", "product": {"id": "x"}, "desk": {}, "tests": {"ci": "teamcity"}},
                  "qata", "qat")
    expect(old.state == "old-schema" and not old.on, "a 1.0 file is not read as set up")
    none = resolve(None, "rela", "release_notes")
    expect(none.state == "no-settings" and "Olga" in none.message, "no settings: ask Olga")
    off = resolve({**doc, "desk": {**doc["desk"], "agents": {"release-rela": "off"}}}, "rela", "release_notes")
    expect(off.state == "agent-off", "an agent switched off answers for every capability")
    off_yaml = resolve({**doc, "desk": {**doc["desk"], "agents": yaml.safe_load("release-rela: off") if yaml
                                        else {"release-rela": False}}}, "rela", "release_notes")
    expect(off_yaml.state == "agent-off", "an unquoted YAML off (read as false) switches the agent off")
    # Clara's ticket handling: on by default once the tracker is set up; explicit off wins.
    tracker = {"instance": "https://tracker.example", "read_tools": "tracker_*", "projects": [{"key": "DEMO"}]}
    for label, tickets in (("no status", {"blocking": ["Urgent"]}), ("TBD status", {"status": "TBD"}),
                           ("no block", None)):
        d = {**doc, "tracker": tracker,
             "desk": {**doc["desk"], "clara": {**({"tickets": tickets} if tickets is not None else {})}}}
        t = resolve(d, "clara", "tickets")
        expect(t.on and "by default" in t.message, f"tickets, tracker set, {label}: on by default")
    t = resolve({**doc, "tracker": tracker, "desk": {**doc["desk"], "clara": {"tickets": {"blocking": ["Urgent"]}}}},
                "clara", "tickets")
    expect(t.settings == {"blocking": ["Urgent"]}, "default-on tickets hands back the team's own rules")
    t = resolve({**doc, "tracker": {**tracker, "projects": []}, "desk": {**doc["desk"], "clara": {"tickets": {}}}},
                "clara", "tickets")
    expect(t.state == "not-set-up" and t.missing == ["tracker.projects"] and "section tracker" in t.message
           and not t.settings, "tickets without a complete tracker is not set up and names the tracker gap")
    t = resolve({**doc, "desk": {**doc["desk"], "clara": {}}}, "clara", "tickets")
    expect(t.state == "not-set-up" and len(t.missing) == len(TRACKER_NEEDS), "tickets with no tracker at all")
    t = resolve({**doc, "tracker": tracker, "desk": {**doc["desk"], "clara": {"tickets": {"status": "off"}}}},
                "clara", "tickets")
    expect(t.state == "off" and not t.on, "an explicit off beats the tracker default")
    t = resolve({**doc, "tracker": tracker, "desk": {**doc["desk"], "agents": {"clerk-clara": "off"}}},
                "clara", "tickets")
    expect(t.state == "agent-off", "Clara switched off beats the tracker default")
    t = resolve({**doc, "tracker": tracker, "desk": {**doc["desk"], "clara": {"lookup": {}}}}, "clara", "lookup")
    expect(t.state == "not-set-up", "the tracker default is Clara's ticket handling only")
    for bad in (("dora", "qat"), ("qata", "release_notes")):
        try:
            resolve(doc, *bad)
            fails.append(f"{bad} accepted")
        except ValueError:
            pass
    # A bound skill or tactic that does not resolve in the pack chain is not on.
    docs_on = {**doc, "desk": {**doc["desk"], "rela": {**doc["desk"]["rela"], "documentation": {
        "status": "on", "skill": "no-such-desk-skill", "tactic": "none"}}}}
    u = resolve(docs_on, "rela", "documentation", roots=[])
    expect(u.state == "unresolved" and not u.on and not u.settings and "no-such-desk-skill" in u.message
           and "Ask Olga" in u.message and u.missing == ["skill:no-such-desk-skill"],
           "a bound skill that resolves nowhere is unresolved, with no settings")
    expect(resolve(docs_on, "rela", "documentation").on, "a parsed dict with no file and no roots skips the name check")
    core = pack_chain(None)
    docs_on["desk"]["rela"]["documentation"]["skill"] = "product-desk-consult"
    expect(resolve(docs_on, "rela", "documentation", roots=core).on, "a skill in doctrine-product resolves")
    docs_on["desk"]["rela"]["documentation"]["tactic"] = "no-such-desk-tactic"
    u = resolve(docs_on, "rela", "documentation", roots=core)
    expect(u.state == "unresolved" and "tactic `no-such-desk-tactic`" in u.message, "an unknown tactic is unresolved")
    docs_on["desk"]["rela"]["documentation"]["tactic"] = "product-desk-shared-conduct"
    expect(resolve(docs_on, "rela", "documentation", roots=core).on, "a tactic in doctrine-product resolves")
    # A team with nothing configured gets no other team's values: every answer is
    # not set up and carries no settings.
    blank = {"schema_version": "2.0", "product": {"id": "blank"}, "desk": {"clara": {}, "qata": {}, "rela": {}}}
    answers = every(blank)
    expect(all(not a.on and not a.settings and "Ask Olga" in a.message for a in answers),
           "a blank team is not set up anywhere and borrows nothing")
    template = HERE.parents[3] / "pack" / "templates" / "product-desk" / "product-desk.template.yaml"
    if template.is_file() and yaml is not None:
        t = _read(template)
        expect(str(t.get("schema_version")).startswith(str(SCHEMA_MAJOR)), "the template carries the 2.0 shape")
        expect(all(isinstance(_get(t, f"desk.{a}.{c}"), dict) for a, s in AGENTS.items() for c in s["caps"]),
               "the template has a block for every capability")
        expect(not any(resolve(t, a, c).on for a, s in AGENTS.items() for c in s["caps"]),
               "the template switches nothing on")
        for a, s in AGENTS.items():
            for c, cap in s["caps"].items():
                for n in cap["needs"]:
                    expect(n.split(".")[0] in _get(t, f"desk.{a}.{c}"), f"template desk.{a}.{c} lacks {n}")
    print("capability selftest:", "PASS" if not fails else "FAILED")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="is one capability set up")
    c.add_argument("--agent", required=True)
    c.add_argument("--capability", required=True)
    lst = sub.add_parser("list", help="every capability of the desk")
    for p in (c, lst):
        p.add_argument("--settings")
        p.add_argument("--product")
        p.add_argument("--json", action="store_true")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    if a.cmd not in ("check", "list"):
        ap.print_help()
        return 2
    doc, where = load(a.settings, a.product)
    if a.cmd == "check":
        try:
            ans = resolve(doc, a.agent, a.capability, where)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        if a.json:
            print(json.dumps(ans.as_dict(), indent=2, ensure_ascii=False, default=str))
        else:
            print(ans.message)
            print(f"settings: {where}")
            if ans.on:
                print(yaml.safe_dump(ans.settings, sort_keys=False, allow_unicode=True).rstrip()
                      if yaml else json.dumps(ans.settings, indent=2, default=str))
        return ON if ans.on else NOT_SET_UP
    answers = every(doc, where)
    if a.json:
        print(json.dumps({"settings": where, "capabilities": [x.as_dict() for x in answers]},
                         indent=2, ensure_ascii=False, default=str))
    else:
        print(f"settings: {where}")
        for x in answers:
            print(f"  {AGENTS[x.agent]['name']:<5} {x.capability:<17} {x.state:<11} "
                  + ("" if x.on else x.message))
    return 0


if __name__ == "__main__":
    sys.exit(main())
