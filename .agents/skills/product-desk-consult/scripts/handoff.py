#!/usr/bin/env python3
"""Write, answer, list and check product desk consult handoffs.

A handoff is one YAML file per consult in the handoff folder:
  <yyyy-mm-dd>-<id>.yaml   with a `request` block and, once answered, an `answer` block.

Desk agents: clerk-clara, qa-qata, release-rela, the desk router (`desk`), the
user, and every specialist named in a product-desk.yaml
(`desk.specialist.profile_id`, e.g. liquidity-lena or credit-carl; `none` and
TBD name nobody). PRODUCT_DESK_AGENTS adds more, comma-separated.

Settings are found as toolguide product-desk-settings says, first hit wins:
PRODUCT_DESK_HOME, else <project>/product-desk, else the product-desk/ folder
of each product pack registered in <project>/.kittify/config.yaml. The
project is the nearest folder above the current one that holds .kittify/.

Handoff folder: PRODUCT_DESK_HANDOFFS, else <PRODUCT_DESK_HOME>/handoffs, else
<project>/product-desk/handoffs. It is never inside a pack repository (a registered
local_path's folder, or any folder holding pack/org-charter.yaml): a folder
that resolves there, explicit or not, is replaced by <project>/product-desk/handoffs
with a one-line notice. It stays local and gitignored: a handoff may name customers. Nothing that looks like a credential
is ever written.

  python handoff.py agents
  python handoff.py new --from qa-qata --to liquidity-lena --question "..." \
      --inputs-file inputs.yaml --evidence "no commit touches the rule" --expected "owning layer + ticket"
  python handoff.py answer <id> --answer "..." --confidence likely \
      --owner liquidity-lena --evidence-cited "..." --open-question "..."
  python handoff.py show <id>
  python handoff.py list [--open]
  python handoff.py validate <file-or-id>
  python handoff.py selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import yaml

GENERIC_AGENTS = {"clerk-clara", "qa-qata", "release-rela", "desk", "user"}
NO_SPECIALIST = {"TBD", "none"}
CONFIDENCE = {"confirmed", "likely", "unknown"}
REQUEST_FIELDS = ["id", "from", "to", "question", "inputs", "evidence_so_far", "expected_output"]
ANSWER_FIELDS = ["answer", "evidence_cited", "confidence", "owner", "open_questions"]
KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?token|access[_-]?token|private[_-]?token|pat)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"\bATATT[A-Za-z0-9_\-=]{20,}"),          # Atlassian API token
    re.compile(r"\bgl(pat|oas)-[A-Za-z0-9_\-]{16,}"),     # GitLab token
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"(?i)\b(jdbc:|server=[^;]+;.*(user id|uid)=)"),                      # connection string
]


def project_root() -> Path:
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if (p / ".kittify").is_dir():
            return p
    return here


def _pack_path(local: str, root: Path) -> Path:
    home = os.environ.get("SPEC_KITTY_PACK_HOME", "")
    text = local.replace("${SPEC_KITTY_PACK_HOME}", home).replace("$SPEC_KITTY_PACK_HOME", home)
    p = Path(os.path.expanduser(text))
    return p if p.is_absolute() else root / p


def registered_packs(root: Path) -> list[Path]:
    """The pack/ folders (local_path) registered in <root>/.kittify/config.yaml."""
    cfg = root / ".kittify" / "config.yaml"
    if not cfg.is_file():
        return []
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    packs = config_packs(data)
    return [_pack_path(str(p["local_path"]), root) for p in packs if isinstance(p, dict) and p.get("local_path")]


def config_packs(data: dict) -> list:
    """charter_packs.org.packs, as Spec Kitty 3.2.7 reads it; else the legacy doctrine.org.packs."""
    for key in ("charter_packs", "doctrine"):
        packs = ((data.get(key) or {}).get("org") or {}).get("packs")
        if packs is not None:
            return list(packs)
    return []


def pack_desk_folders(root: Path, packs: list[Path] | None = None) -> list[Path]:
    """product-desk/ folders beside the registered packs (or the given pack/ folders)."""
    out = []
    for pack in registered_packs(root) if packs is None else packs:
        d = pack.parent / "product-desk"
        if (d / "product-desk.yaml").is_file() and d not in out:
            out.append(d)
    return out


def inside_pack(path: Path, root: Path, packs: list[Path] | None = None) -> Path | None:
    """The pack repository `path` lies in, or None.

    A pack repository is the folder holding a registered pack/ (its local_path),
    or any folder that holds pack/org-charter.yaml.
    """
    p = path.expanduser().resolve()
    chain = [p, *p.parents]
    for pack in registered_packs(root) if packs is None else packs:
        repo = pack.expanduser().resolve().parent
        if repo in chain:
            return repo
    for d in chain:
        if (d / "pack" / "org-charter.yaml").is_file():
            return d
    return None


def _files_in(home: Path) -> list[Path]:
    return [p for p in [home / "product-desk.yaml", *sorted(home.glob("*/product-desk.yaml"))] if p.exists()]


def _candidate_handoff_dir(root: Path) -> Path:
    if os.environ.get("PRODUCT_DESK_HANDOFFS"):
        return Path(os.environ["PRODUCT_DESK_HANDOFFS"])
    if os.environ.get("PRODUCT_DESK_HOME"):
        return Path(os.environ["PRODUCT_DESK_HOME"]) / "handoffs"
    return root / "product-desk" / "handoffs"


def handoff_dir(root: Path | None = None, packs: list[Path] | None = None, notify=sys.stderr) -> Path:
    """The handoff folder; never inside a pack repository other than the project itself."""
    root = project_root() if root is None else root
    own = root / "product-desk" / "handoffs"
    found = _candidate_handoff_dir(root)
    if found.expanduser().resolve() != own.resolve():
        repo = inside_pack(found, root, packs)
        if repo is None:
            return found
        if notify is not None:
            print(f"note: handoff folder {found} is inside pack repository {repo}; using {own} instead "
                  "(handoffs never go into a pack)", file=notify)
    repo = inside_pack(own, root, packs)
    if repo is not None:
        raise SystemExit(f"refused: this project is inside pack repository {repo}, and handoffs never go into a "
                         "pack; run the desk from a separate project folder "
                         "(configure_pc.py --project <folder> [--init-desk]). Nothing was written.")
    return own


def settings_files(root: Path | None = None, packs: list[Path] | None = None) -> list[Path]:
    """The desk settings the agents read, first hit wins (toolguide product-desk-settings).

    `packs` replaces the pack/ folders read from <root>/.kittify/config.yaml, so a
    caller that has not written the config yet (configure_pc --dry-run) gets the
    same answer.
    """
    if os.environ.get("PRODUCT_DESK_HOME"):
        return _files_in(Path(os.environ["PRODUCT_DESK_HOME"]))
    root = project_root() if root is None else root
    own = _files_in(root / "product-desk")
    if own:
        return own
    return [f for d in pack_desk_folders(root, packs) for f in _files_in(d)]


def desk_agents() -> tuple[set[str], list[str]]:
    """(agent ids, where each specialist came from)."""
    agents, notes = set(GENERIC_AGENTS), []
    files = settings_files()
    for f in files:
        try:
            s = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            notes.append(f"{f}: unreadable ({e.__class__.__name__}) -- skipped")
            continue
        sid = str(((s.get("desk") or {}).get("specialist") or {}).get("profile_id") or "")
        if sid in NO_SPECIALIST:
            notes.append(f"no specialist in {f}: analysis goes back to the user")
        elif sid and KEBAB.match(sid):
            agents.add(sid)
            notes.append(f"{sid} from {f}")
    for extra in filter(None, (x.strip() for x in os.environ.get("PRODUCT_DESK_AGENTS", "").split(","))):
        if KEBAB.match(extra):
            agents.add(extra)
            notes.append(f"{extra} from PRODUCT_DESK_AGENTS")
    if not files:
        notes.append("no product-desk.yaml found: no specialist (run product-desk-onboarding)")
    return agents, notes


def short(agent: str) -> str:
    return agent.rsplit("-", 1)[-1]


def find_secret(obj) -> str | None:
    text = json.dumps(obj, ensure_ascii=False)
    for pat in SECRET_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)[:12] + "…"
    return None


def validate(doc: dict, agents: set[str] | None = None) -> list[str]:
    agents = agents or desk_agents()[0]
    errs: list[str] = []
    req = doc.get("request")
    if not isinstance(req, dict):
        return ["missing request block"]
    for f in REQUEST_FIELDS:
        if f not in req:
            errs.append(f"request.{f} missing")
    for end in ("from", "to"):
        if req.get(end) not in agents:
            errs.append(f"request.{end} not a desk agent: {req.get(end)!r} (see `handoff.py agents`)")
    if req.get("from") == req.get("to"):
        errs.append("request.from and request.to are the same agent")
    if "product" in req and not KEBAB.match(str(req["product"])):
        errs.append(f"request.product must be a kebab-case product id: {req['product']!r}")
    if not str(req.get("question", "")).strip():
        errs.append("request.question is empty")
    if not isinstance(req.get("inputs", {}), dict):
        errs.append("request.inputs must be a mapping")
    ans = doc.get("answer")
    if ans is not None:
        for f in ANSWER_FIELDS:
            if f not in ans:
                errs.append(f"answer.{f} missing")
        if ans.get("confidence") not in CONFIDENCE:
            errs.append(f"answer.confidence must be one of {sorted(CONFIDENCE)}")
        if ans.get("confidence") == "unknown" and not ans.get("open_questions"):
            errs.append("an unknown answer must carry at least one open question for the user")
        if not isinstance(ans.get("open_questions", []), list):
            errs.append("answer.open_questions must be a list")
    hit = find_secret(doc)
    if hit:
        errs.append(f"looks like a credential ({hit}) — handoffs never carry secrets")
    return errs


def path_for(hid: str, folder: Path) -> Path:
    direct = Path(hid)
    if direct.suffix in (".yaml", ".yml") and direct.exists():
        return direct
    matches = sorted(folder.glob(f"*-{hid}.yaml"))
    if not matches:
        raise SystemExit(f"no handoff with id {hid} in {folder}")
    return matches[-1]


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def save(p: Path, doc: dict, agents: set[str]) -> None:
    errs = validate(doc, agents)
    if errs:
        raise SystemExit("refusing to write handoff:\n  " + "\n  ".join(errs))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")


def cmd_new(a, folder: Path, agents: set[str]) -> Path:
    now = dt.datetime.now().replace(microsecond=0)
    if getattr(a, "inputs_file", None):
        raw = Path(a.inputs_file).read_bytes()
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
        inputs = yaml.safe_load(text) or {}
    else:
        inputs = json.loads(a.inputs) if a.inputs else {}
    hid = a.id or f"{now:%H%M%S}-{short(a.frm)}-{short(a.to)}"
    req = {"id": hid, "from": a.frm, "to": a.to}
    if getattr(a, "product", None):
        req["product"] = a.product
    req.update({"question": a.question, "inputs": inputs,
                "evidence_so_far": a.evidence or [], "expected_output": a.expected or ""})
    doc = {"request": req, "status": "open", "created": now.isoformat()}
    p = folder / f"{now:%Y-%m-%d}-{hid}.yaml"
    save(p, doc, agents)
    print(p)
    return p


def cmd_answer(a, folder: Path, agents: set[str]) -> Path:
    p = path_for(a.hid, folder)
    doc = load(p)
    doc["answer"] = {
        "answer": a.answer,
        "evidence_cited": a.evidence_cited or [],
        "confidence": a.confidence,
        "owner": a.owner,
        "open_questions": a.open_question or [],
    }
    doc["status"] = "needs-user" if a.confidence == "unknown" else "answered"
    doc["answered"] = dt.datetime.now().replace(microsecond=0).isoformat()
    save(p, doc, agents)
    print(p)
    return p


def cmd_list(a, folder: Path) -> None:
    for p in sorted(folder.glob("*.yaml")):
        doc = load(p)
        st = doc.get("status", "?")
        if a.open and st == "answered":
            continue
        r = doc.get("request", {})
        prod = f"[{r['product']}] " if r.get("product") else ""
        print(f"{st:11} {p.name:44} {r.get('from')} -> {r.get('to')}: {prod}{str(r.get('question'))[:70]}")


def _refused(fn) -> bool:
    try:
        fn()
    except SystemExit:
        return True
    return False


def selftest() -> int:
    keep = {k: os.environ.get(k) for k in ("PRODUCT_DESK_HOME", "PRODUCT_DESK_HANDOFFS", "PRODUCT_DESK_AGENTS",
                                           "LQR_DESK_HANDOFFS", "LQR_AI_HUB", "SPEC_KITTY_PACK_HOME",
                                           "HOME", "USERPROFILE")}
    cwd = Path.cwd()
    fails = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "desk-home"
            home.mkdir()
            (home / "abacus").mkdir()
            (home / "abacus" / "product-desk.yaml").write_text(
                "desk:\n  specialist:\n    profile_id: liquidity-lena\n", encoding="utf-8")
            (home / "other").mkdir()
            (home / "other" / "product-desk.yaml").write_text(
                "desk:\n  specialist:\n    profile_id: TBD\n", encoding="utf-8")
            os.environ["PRODUCT_DESK_HOME"] = str(home)
            os.environ.pop("PRODUCT_DESK_HANDOFFS", None)
            os.environ.pop("PRODUCT_DESK_AGENTS", None)
            agents, _ = desk_agents()
            folder = handoff_dir()
            checks = [("handoff folder under PRODUCT_DESK_HOME", folder == home / "handoffs"),
                      ("specialist read from settings; TBD ignored", "liquidity-lena" in agents and "TBD" not in agents)]
            ns = argparse.Namespace(frm="qa-qata", to="liquidity-lena", id="t1", product="abacus",
                                    question="Why did C_73.00 row 0010 move?", inputs='{"cells": ["C_73_00|0010|0010"]}',
                                    inputs_file=None, evidence=["no commit touches the rule"], expected="owning layer")
            p = cmd_new(ns, folder, agents)
            checks.append(("new request is open and carries the product",
                           load(p)["status"] == "open" and load(p)["request"]["product"] == "abacus"))
            cmd_answer(argparse.Namespace(hid="t1", answer="Classification layer", evidence_cited=["rule id"],
                                          confidence="likely", owner="liquidity-lena", open_question=[]), folder, agents)
            checks.append(("answered", load(p)["status"] == "answered"))
            checks.append(("unknown without an open question is refused", _refused(lambda: cmd_answer(
                argparse.Namespace(hid="t1", answer="?", evidence_cited=[], confidence="unknown",
                                   owner="liquidity-lena", open_question=[]), folder, agents))))
            mk = lambda **kw: argparse.Namespace(**{"frm": "qa-qata", "to": "liquidity-lena", "id": "tx", "product": None,  # noqa: E731
                                                    "question": "q", "inputs": None, "inputs_file": None,
                                                    "evidence": [], "expected": "", **kw})
            checks.append(("a credential is refused", _refused(lambda: cmd_new(
                mk(id="t2", inputs='{"note": "password=hunter2"}'), folder, agents))
                and not list(folder.glob("*-t2.yaml"))))
            checks.append(("a connection string is refused", _refused(lambda: cmd_new(
                mk(id="t5", inputs='{"db": "jdbc:sqlserver://h;user=x"}'), folder, agents))))
            checks.append(("self-consult is refused", _refused(lambda: cmd_new(mk(id="t3", to="qa-qata"), folder, agents))))
            checks.append(("an agent no settings file names is refused", _refused(lambda: cmd_new(
                mk(id="t4", to="tax-tom"), folder, agents))))
            os.environ["PRODUCT_DESK_AGENTS"] = "tax-tom"
            checks.append(("PRODUCT_DESK_AGENTS adds an agent", "tax-tom" in desk_agents()[0]))
            older = {"request": {"id": "101500-qata-lena", "from": "qa-qata", "to": "liquidity-lena",
                                 "question": "q", "inputs": {}, "evidence_so_far": [], "expected_output": ""},
                     "status": "open"}
            checks.append(("a handoff in the established format validates", not validate(older, agents)))
            router_style = {**older, "request": {**older["request"], "from": "lqr-desk"}}
            checks.append(("the old router name lqr-desk is refused", bool(validate(router_style, agents))))
            checks.append(("short ids drop the agent prefix", (short("liquidity-lena"), short("qa-qata")) == ("lena", "qata")))

            # A team with no settings and no product pack: generic desk only.
            os.environ.pop("PRODUCT_DESK_HOME", None)
            os.environ.pop("PRODUCT_DESK_AGENTS", None)
            bare = Path(tmp) / "bare-project"
            (bare / ".kittify").mkdir(parents=True)
            os.chdir(bare / ".kittify")
            agents, _ = desk_agents()
            checks.append(("no settings: no specialist presumed", agents == GENERIC_AGENTS))
            checks.append(("no settings: handoffs in the project",
                           handoff_dir() == bare.resolve() / "product-desk" / "handoffs"))

            # A project whose chain registers a product pack carrying desk settings.
            packs = Path(tmp) / "packs"
            desk = packs / "doctrine-product-reg-credit-acme" / "product-desk"
            desk.mkdir(parents=True)
            (desk / "product-desk.yaml").write_text(
                "desk:\n  specialist:\n    profile_id: credit-carl\n", encoding="utf-8")
            other = packs / "doctrine-product-reg-credit-beta" / "product-desk"
            other.mkdir(parents=True)
            (other / "product-desk.yaml").write_text(
                "desk:\n  specialist:\n    profile_id: none\n", encoding="utf-8")
            os.environ["SPEC_KITTY_PACK_HOME"] = str(packs)
            proj = Path(tmp) / "team-project"
            (proj / ".kittify").mkdir(parents=True)
            entries = ("    - name: doctrine-product-reg-credit-acme\n"
                       "      local_path: ${SPEC_KITTY_PACK_HOME}/doctrine-product-reg-credit-acme/pack\n"
                       f"    - name: doctrine-product-reg-credit-beta\n      local_path: {(other.parent / 'pack').as_posix()}\n")
            for key in ("doctrine", "charter_packs"):     # the legacy key, then the 3.2.7 one configure_pc writes
                (proj / ".kittify" / "config.yaml").write_text(f"{key}:\n  org:\n    packs:\n{entries}", encoding="utf-8")
                checks.append((f"packs read from {key}.org.packs",
                               [p.name for p in registered_packs(proj)] == ["pack", "pack"]
                               and len(pack_desk_folders(proj)) == 2))
            (proj / ".kittify" / "config.yaml").write_text(
                f"charter_packs:\n  org:\n    packs:\n{entries}"
                "doctrine:\n  org:\n    packs:\n    - {name: stale, local_path: stale/pack}\n", encoding="utf-8")
            checks.append(("charter_packs wins over a stale doctrine block",
                           all("stale" not in str(p) for p in registered_packs(proj))))
            os.chdir(proj)
            agents, notes = desk_agents()
            checks.append(("specialist found through a product pack in the chain", "credit-carl" in agents))
            checks.append(("specialist none names nobody", "none" not in agents
                           and any("no specialist" in n for n in notes)))
            checks.append(("handoffs never land in a product pack repo",
                           handoff_dir() == proj.resolve() / "product-desk" / "handoffs"))
            (proj / "product-desk").mkdir()
            (proj / "product-desk" / "product-desk.yaml").write_text(
                "desk:\n  specialist:\n    profile_id: tax-tom\n", encoding="utf-8")
            agents, _ = desk_agents()
            checks.append(("project settings win over pack settings", "tax-tom" in agents and "credit-carl" not in agents))

            # Handoffs never go into a pack repository, whatever points there.
            import io
            own = proj.resolve() / "product-desk" / "handoffs"
            acme_repo = packs / "doctrine-product-reg-credit-acme"
            loose = Path(tmp) / "loose-pack"
            (loose / "pack").mkdir(parents=True)
            (loose / "pack" / "org-charter.yaml").write_text("org_name: loose\n", encoding="utf-8")
            outside = Path(tmp) / "my-handoffs"

            def redirected(var, value):
                os.environ[var] = str(value)
                msg = io.StringIO()
                got = handoff_dir(notify=msg)
                os.environ.pop(var)
                return got == own and "inside pack repository" in msg.getvalue()

            checks.append(("PRODUCT_DESK_HANDOFFS into a registered pack repo is redirected",
                           redirected("PRODUCT_DESK_HANDOFFS", acme_repo / "handoffs")))
            checks.append(("PRODUCT_DESK_HANDOFFS into a registered pack/ itself is redirected",
                           redirected("PRODUCT_DESK_HANDOFFS", acme_repo / "pack" / "handoffs")))
            checks.append(("PRODUCT_DESK_HANDOFFS into an unregistered pack repo is redirected",
                           redirected("PRODUCT_DESK_HANDOFFS", loose / "notes" / "handoffs")))
            checks.append(("PRODUCT_DESK_HOME on a pack repo's product-desk: handoffs redirected",
                           redirected("PRODUCT_DESK_HOME", desk)))
            os.environ["PRODUCT_DESK_HOME"] = str(desk)
            checks.append(("PRODUCT_DESK_HOME on a pack repo still supplies the settings",
                           settings_files() == [desk / "product-desk.yaml"]))
            os.environ.pop("PRODUCT_DESK_HOME")
            os.environ["PRODUCT_DESK_HANDOFFS"] = str(outside)
            msg = io.StringIO()
            checks.append(("PRODUCT_DESK_HANDOFFS outside any pack is honoured, silently",
                           handoff_dir(notify=msg) == outside and not msg.getvalue()))
            os.environ.pop("PRODUCT_DESK_HANDOFFS")

            # A project that is itself a pack repository: refused, nothing written.
            pack_project = Path(tmp) / "pack-project"
            (pack_project / ".kittify").mkdir(parents=True)
            (pack_project / "pack").mkdir()
            (pack_project / "pack" / "org-charter.yaml").write_text("org_name: pp\n", encoding="utf-8")
            os.chdir(pack_project)
            checks.append(("a project that is a pack repo is refused", _refused(handoff_dir)))
            os.environ["PRODUCT_DESK_HANDOFFS"] = str(loose / "handoffs")
            checks.append(("a pack-repo project is refused even after a redirect", _refused(
                lambda: handoff_dir(notify=None))))
            os.environ.pop("PRODUCT_DESK_HANDOFFS")
            checks.append(("the refusal writes nothing", not (pack_project / "product-desk").exists()))
            os.environ["PRODUCT_DESK_HANDOFFS"] = str(outside)
            checks.append(("a pack-repo project may still use an explicit folder outside packs",
                           handoff_dir(notify=None) == outside))
            os.environ.pop("PRODUCT_DESK_HANDOFFS")

            # A full legacy RA LQR hub on the machine, at LQR_AI_HUB and at ~/GIT/lqr-ai-hub, with
            # LQR_DESK_HANDOFFS set: none of it is read; the bare project stays a generic desk.
            user = Path(tmp) / "user"
            os.environ["HOME"] = os.environ["USERPROFILE"] = str(user)
            for hub in (Path(tmp) / "hub", user / "GIT" / "lqr-ai-hub"):
                (hub / "lqr-desk" / "handoffs").mkdir(parents=True)
                (hub / "LQR-Agents" / "product-desk").mkdir(parents=True)
                (hub / "LQR-Agents" / "product-desk" / "product-desk.yaml").write_text(
                    "desk:\n  specialist:\n    profile_id: liquidity-lena\n", encoding="utf-8")
            os.environ["LQR_AI_HUB"] = str(Path(tmp) / "hub")
            os.environ["LQR_DESK_HANDOFFS"] = str(Path(tmp) / "hub" / "lqr-desk" / "handoffs")
            os.environ.pop("SPEC_KITTY_PACK_HOME", None)
            os.chdir(bare)
            agents, _ = desk_agents()
            checks.append(("a legacy hub on the machine: no settings read from it", settings_files() == []))
            checks.append(("a legacy hub on the machine: no specialist or router name from it",
                           agents == GENERIC_AGENTS))
            checks.append(("a legacy hub and LQR_DESK_HANDOFFS: handoffs stay in the project",
                           handoff_dir() == bare.resolve() / "product-desk" / "handoffs"))
            os.chdir(cwd)  # leave the temp folder before it is removed
    finally:
        os.chdir(cwd)
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    for n, ok in checks:
        if not ok:
            fails.append(n)
        print(f"  {'ok  ' if ok else 'FAIL'} {n}")
    print("selftest OK" if not fails else f"{len(fails)} FAILURE(S)")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("agents", help="list the desk agents and where each specialist came from")
    n = sub.add_parser("new")
    n.add_argument("--from", dest="frm", required=True)
    n.add_argument("--to", required=True)
    n.add_argument("--product", help="product id, when the desk serves more than one")
    n.add_argument("--question", required=True)
    n.add_argument("--inputs", help="JSON object: keys, cells, classes, run id")
    n.add_argument("--inputs-file", help="YAML or JSON file with the inputs (use this from PowerShell)")
    n.add_argument("--evidence", action="append", help="evidence so far (repeatable)")
    n.add_argument("--expected", help="expected output")
    n.add_argument("--id")
    r = sub.add_parser("answer")
    r.add_argument("hid")
    r.add_argument("--answer", required=True)
    r.add_argument("--evidence-cited", action="append")
    r.add_argument("--confidence", required=True, choices=sorted(CONFIDENCE))
    r.add_argument("--owner", required=True)
    r.add_argument("--open-question", action="append")
    s = sub.add_parser("show")
    s.add_argument("hid")
    li = sub.add_parser("list")
    li.add_argument("--open", action="store_true", help="only open or needs-user")
    v = sub.add_parser("validate")
    v.add_argument("hid")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    folder = handoff_dir()
    agents, notes = desk_agents()
    if a.cmd == "agents":
        print("handoff folder:", folder)
        print("agents:", ", ".join(sorted(agents)))
        for x in notes:
            print("  " + x)
    elif a.cmd == "new":
        cmd_new(a, folder, agents)
    elif a.cmd == "answer":
        cmd_answer(a, folder, agents)
    elif a.cmd == "show":
        print(path_for(a.hid, folder).read_text(encoding="utf-8"))
    elif a.cmd == "list":
        cmd_list(a, folder)
    elif a.cmd == "validate":
        errs = validate(load(path_for(a.hid, folder)), agents)
        print("valid" if not errs else "\n".join(errs))
        return 1 if errs else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
