"""Review an existing team's desk settings: each current value, where it comes from, and what is still open.

Olga's review mode (procedure product-desk-onboarding, step "Review an
existing team's settings") walks this table instead of asking every question
from scratch: for each setting she says "currently it is X (from <where>) --
is that correct?" and the user confirms, corrects or skips. Settings still
TBD, partial or missing from the file are flagged `open` and asked as open
questions.

Where the values are read from:

    the team's settings file   product-desk.yaml, found as skill product-desk-capability finds it
    the template               keys the template has and the team's file lacks are `missing`
    environment variables      the `*_env` keys and every $NAME / ~ path the settings name (on Windows
                               also the user variables saved for new sessions)
    the database hosts file    database_server.hosts_file beside the settings, else the user-level
                               copy ~/.regnology/<server>/<file>, else --db-hosts
    Credential Manager         target NAMES only (cmdkey /list), per database target when
                               database_server.credential_target names the pattern
    credential files           the .env files `credentials` names: which keys are stored, never a value
    the project                .kittify/config.yaml: the registered packs, every settings file found

A secret is never shown: a key that names a password, token or secret, or a
value shaped like one, is reported as `stored` or `not stored` only.

    python settings_review.py show [--settings F] [--product ID] [--project DIR] [--section S]
                                   [--db-hosts F] [--json]
    python settings_review.py set --settings F --key a.b.c --value V [--customer-names F] [--apply]
    python settings_review.py set --env-file F --key NAME --value V [--apply]
    python settings_review.py set --user-env NAME --value V [--apply]
    python settings_review.py selftest

`set` writes one confirmed correction back to where the value came from. It
is a dry run that prints the diff unless --apply. It refuses a secret, a
customer name in a settings file (--customer-names <file>, one per line, or
PRODUCT_DESK_CUSTOMER_NAMES, names separated by |), a value that is a block
or sits inside a list (edit those by hand, after showing the diff), and an
env file that git tracks. Exit 0 done or dry run, 3 refused, 2 usage error.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - reported at use
    yaml = None

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[3]
TEMPLATE = CORE / "pack" / "templates" / "product-desk" / "product-desk.template.yaml"
REFUSED, USAGE = 3, 2
UNSET = (None, "", "TBD", "tbd", [], {})

# Olga's order (procedure product-desk-onboarding); each section lists the settings prefixes it reviews.
SECTIONS: list[tuple[str, str, list[str]]] = [
    ("product", "Product", ["schema_version", "product", "desk.agents", "desk.specialist"]),
    ("tracker", "Tracker", ["tracker"]),
    ("wiki", "Wiki", ["wiki"]),
    ("code", "Code", ["code"]),
    ("data-pipeline", "Data pipeline", ["pipeline"]),
    ("databases", "Databases", ["databases", "database_server"]),
    ("clara-tickets", "Clara: how the team handles tickets", ["desk.clara"]),
    ("qata-qat", "Qata: how the team does QAT", ["desk.qata"]),
    ("rela-release", "Rela: how the team releases",
     ["desk.rela.readiness", "desk.rela.release", "desk.rela.announcement", "desk.rela.documentation",
      "desk.rela.status_pages"]),
    ("rela-release-notes", "Rela: how the team writes release notes", ["desk.rela.release_notes"]),
    ("knowledge", "Knowledge", ["knowledge", "extensions"]),
    ("people", "People and boundaries", ["people", "boundaries"]),
    ("credentials", "Credentials (names only)", ["credentials"]),
    ("onboarding", "Section status", ["desk.onboarding"]),
]
CAP_SECTION = {"clara": "clara-tickets", "qata": "qata-qat"}
# Template keys whose absence is no open question: the per-agent doctrine lists are optional.
NOT_ASKED = ("extensions",)

SECRET_KEY = re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key)")
SECRET_VALUE = [
    re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?token|access[_-]?token|private[_-]?token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"\bATATT[A-Za-z0-9_\-=]{20,}"),
    re.compile(r"\bgl(pat|oas|ptt|rt)-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"),
]
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
ENV_REF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?|%([A-Za-z_][A-Za-z0-9_]*)%")
LABEL_KEYS = ("id", "key", "name", "target", "topic", "term", "what")
HIDDEN = "(hidden)"


def _load_capability():
    spec = importlib.util.spec_from_file_location("product_desk_capability_for_review", HERE / "capability.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


cap = _load_capability()


@dataclass
class Row:
    section: str
    key: str
    value: str
    state: str          # set | open | partial | missing | stored | not-stored | info
    origin: str         # settings | template | environment | hosts file | Credential Manager | credential file | derived | project
    write_to: str       # where a confirmed correction goes, in plain words
    note: str = ""

    @property
    def is_open(self) -> bool:
        return self.state in ("open", "partial", "missing", "not-stored")


# ---------------------------------------------------------------- helpers
def is_secret_key(name: str) -> bool:
    return bool(SECRET_KEY.search(name.split(".")[-1].split("[")[0]))


def is_secret_value(value) -> bool:
    return isinstance(value, str) and any(p.search(value) for p in SECRET_VALUE)


def render(value) -> str:
    if value is None:
        return "(empty)"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list):
        if not value:
            return "(empty list)"
        if all(not isinstance(v, (dict, list)) for v in value):
            return ", ".join(render(v) for v in value)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return "(empty)" if not value else json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _label(item, index: int) -> str:
    if isinstance(item, dict):
        for k in LABEL_KEYS:
            v = item.get(k)
            if isinstance(v, (str, int)) and str(v).strip() and len(str(v)) <= 40 and "[" not in str(v):
                return str(v).strip()
    return str(index)


def flatten(node, path: str = "") -> list[tuple[str, object]]:
    """(dotted key, leaf value). Lists of mappings are walked per item, labelled by its id, key or name."""
    out: list[tuple[str, object]] = []
    if isinstance(node, dict) and node:
        for k, v in node.items():
            out += flatten(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list) and node and any(isinstance(i, dict) for i in node):
        labels = [_label(item, i) for i, item in enumerate(node)]
        for i, item in enumerate(node):
            label = labels[i] if labels.count(labels[i]) == 1 else str(i)
            if isinstance(item, dict):
                out += flatten(item, f"{path}[{label}]")
            else:
                out.append((f"{path}[{label}]", item))
    else:
        out.append((path, node))
    return out


def section_of(key: str) -> str:
    best, size = "other", -1
    for sid, _, prefixes in SECTIONS:
        for p in prefixes:
            if (key == p or key.startswith(p + ".") or key.startswith(p + "[")) and len(p) > size:
                best, size = sid, len(p)
    return best


def git_root(path: Path) -> Path | None:
    p = path.resolve()
    for d in (p if p.is_dir() else p.parent, *p.parents):
        if (d / ".git").exists():
            return d
    return None


def describe_file(path: Path) -> str:
    """Plain words for where a settings file sits, and what a change to it means."""
    home = os.environ.get("SPEC_KITTY_PACK_HOME")
    repo = git_root(path)
    if home and repo is not None:
        try:
            path.resolve().relative_to(Path(home).resolve())
            return (f"the team settings file {path}, in the installed pack home (git clone {repo}); a change there "
                    "stays local until it is committed in the pack's repository")
        except ValueError:
            pass
    if repo is not None:
        return f"the team settings file {path}, in git repository {repo}; a change there is not committed by Olga"
    return f"the team settings file {path} (not in a git repository)"


def expand(text: str) -> tuple[str | None, list[str]]:
    """A $NAME / %NAME% / ~ path on this machine, or None with the variables that are not set."""
    unset: list[str] = []

    def sub(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        val = os.environ.get(name)
        if val is None:
            unset.append(name)
            return m.group(0)
        return val

    out = ENV_REF.sub(sub, text)
    if unset:
        return None, unset
    return os.path.expanduser(out), []


def user_env(name: str) -> str | None:
    """A user environment variable saved for new sessions (Windows), when this session does not have it."""
    if os.name != "nt" or os.environ.get("PRODUCT_DESK_REVIEW_NO_REGISTRY"):
        return None
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return None


def looks_like_path(text: str) -> bool:
    return bool(re.match(r"^(\$|%|~)", text)) and ("/" in text or "\\" in text or text.startswith("~"))


def env_rows(section: str, key: str, value) -> list[Row]:
    """Where a `*_env` variable or a $NAME / ~ path resolves on this machine."""
    rows: list[Row] = []
    last = key.split(".")[-1].split("[")[0]
    if last.endswith("_env") and isinstance(value, str) and ENV_NAME.match(value.strip()) \
            and value.strip().upper() != "TBD":
        name = value.strip()
        current = os.environ.get(name)
        saved = user_env(name) if current is None else None
        if current is None and saved is not None:
            rows.append(Row(section, f"{key} -> ${name}", HIDDEN if SECRET_KEY.search(name) else saved, "info",
                            "environment", f"your user environment variable {name}",
                            "saved in your user environment but not in this session: restart Cursor"))
        elif current is None:
            rows.append(Row(section, f"{key} -> ${name}", "not set", "open", "environment",
                            f"your user environment variable {name}"))
        elif SECRET_KEY.search(name):
            rows.append(Row(section, f"{key} -> ${name}", "set " + HIDDEN, "stored", "environment",
                            "not written by Olga"))
        else:
            exists = Path(os.path.expanduser(current)).exists()
            rows.append(Row(section, f"{key} -> ${name}", current, "info", "environment",
                            f"your user environment variable {name}",
                            "the folder exists" if exists else "that path does not exist on this machine"))
    candidates = [v for v in (value if isinstance(value, list) else [value])
                  if isinstance(v, str) and looks_like_path(v.strip())]
    if candidates:
        resolved, unset_all = None, []
        for c in candidates:
            path, unset = expand(c.strip())
            if path is not None:
                resolved = path
                break
            unset_all += unset
        if resolved is None:
            rows.append(Row(section, f"{key} (on this machine)", "no candidate resolves", "info", "environment",
                            "your user environment variables",
                            "not set: " + ", ".join(sorted(set(unset_all)))))
        else:
            exists = Path(resolved).exists()
            rows.append(Row(section, f"{key} (on this machine)", resolved, "info", "environment",
                            "user-local; never copied into a pack",
                            "exists" if exists else "does not exist yet"))
    return rows


def leaf_state(key: str, value) -> str:
    if key.startswith("desk.onboarding.") and str(value).strip().lower() == "partial":
        return "partial"
    if key.startswith("extensions.") and value in ([], {}, None):
        return "set"                    # an empty doctrine list is a normal answer, not a gap
    if value in UNSET or (isinstance(value, str) and value.strip().upper() == "TBD"):
        return "open"
    return "set"


# ---------------------------------------------------------------- user-local sources
def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def hosts_candidates(doc: dict, source: Path | None, explicit: str | None) -> list[Path]:
    server = (doc or {}).get("database_server") or {}
    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit).expanduser())
    hosts = server.get("hosts_file")
    if hosts not in UNSET and source is not None:
        rel = Path(str(hosts))
        cands.append(rel if rel.is_absolute() else source.parent.parent / rel)
        if server.get("source") not in UNSET:
            cands.append(Path.home() / ".regnology" / Path(str(server["source"])).name / rel.name)
    return cands


def credential_targets() -> set[str] | None:
    """Credential Manager target names (cmdkey /list prints names only), or None when it cannot be asked."""
    if os.name != "nt" or shutil.which("cmdkey") is None:
        return None
    try:
        r = subprocess.run(["cmdkey", "/list"], capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    names = set()
    for line in r.stdout.splitlines():
        m = re.search(r"Target:\s*(?:[A-Za-z]+:target=)?(.+?)\s*$", line)
        if m:
            names.add(m.group(1).strip())
    return names


def database_rows(doc: dict, source: Path | None, db_hosts: str | None, cm: set[str] | None) -> list[Row]:
    rows: list[Row] = []
    sec = "databases"
    cands = hosts_candidates(doc, source, db_hosts)
    found = next((c for c in cands if c.is_file()), None)
    if cands and found is None:
        rows.append(Row(sec, "hosts file", "not found", "open", "hosts file",
                        "a user-local hosts file (copy the template and fill in each host)",
                        "looked in: " + "; ".join(str(c) for c in cands)))
    elif found is not None:
        repo = git_root(found)
        where = f"the hosts file {found}" + (f", inside git repository {repo} (it must stay git-ignored)"
                                              if repo else " (user-local)")
        rows.append(Row(sec, "hosts file", str(found), "info", "hosts file", where))
        for k, v in read_env_file(found).items():
            if is_secret_key(k) or is_secret_value(v):
                rows.append(Row(sec, f"hosts: {k}", "stored " + HIDDEN if v else "not stored",
                                "stored" if v else "not-stored", "hosts file",
                                "not written by Olga; a login belongs in Credential Manager",
                                "a secret in the hosts file: move it to Credential Manager"))
            else:
                state = "open" if (not v or re.fullmatch(r"<[^<>]*>", v)) else "set"
                rows.append(Row(sec, f"hosts: {k}", v or "(empty)", state, "hosts file", where))
    pattern = ((doc or {}).get("database_server") or {}).get("credential_target")
    targets = [str(d.get("target")) for d in (doc or {}).get("databases") or [] if isinstance(d, dict)
               and d.get("target") not in UNSET]
    if pattern not in UNSET and targets:
        for t in targets:
            name = str(pattern).replace("{target}", t)
            if cm is None:
                rows.append(Row(sec, f"login for {t}", name, "info", "Credential Manager",
                                "not written by Olga", "Credential Manager cannot be asked on this machine"))
            elif name in cm:
                rows.append(Row(sec, f"login for {t}", f"{name}: stored {HIDDEN}", "stored", "Credential Manager",
                                "not written by Olga"))
            else:
                rows.append(Row(sec, f"login for {t}", f"{name}: not stored", "not-stored", "Credential Manager",
                                "not written by Olga; store it with the database server's own credential script"))
    return rows


def credential_file_rows(doc: dict, root: Path) -> list[Row]:
    """For each `credentials` entry naming a file: is it there, which keys hold a value. Never a value."""
    rows: list[Row] = []
    bases = [Path.home() / "GIT", Path.home(), root.parent]
    for k, v in ((doc or {}).get("credentials") or {}).items():
        if not isinstance(v, str) or v.strip() in UNSET:
            continue
        token = next((t.strip("(),;") for t in v.split() if ("/" in t or "\\" in t or t.startswith("."))
                      and "://" not in t), None)
        if token is None:
            continue
        p = Path(os.path.expanduser(token))
        found = p if p.is_absolute() and p.is_file() else next((b / p for b in bases if (b / p).is_file()), None)
        key = f"credentials.{k} (file)"
        if found is None:
            rows.append(Row("credentials", key, f"{token}: not found", "not-stored", "credential file",
                            "not written by Olga; create the file yourself",
                            "looked under: " + "; ".join(str(b) for b in bases)))
            continue
        patterns = [m.rstrip("*") for m in re.findall(r"\b([A-Z][A-Z0-9_]*\*?)", v[v.find("("):]
                                                                                 if "(" in v else "")]
        values = read_env_file(found)
        if not values:
            size = found.stat().st_size
            rows.append(Row("credentials", key, f"{found}: " + (f"stored {HIDDEN}" if size else "empty"),
                            "stored" if size else "not-stored", "credential file", "not written by Olga"))
            continue
        names = [n for n in values if not patterns or any(n.startswith(p) for p in patterns)]
        if not names:
            rows.append(Row("credentials", key, f"{found}: none of {', '.join(patterns)} is in it", "not-stored",
                            "credential file", "not written by Olga"))
        for n in names:
            rows.append(Row("credentials", f"{key}: {n}", "stored " + HIDDEN if values[n] else "empty",
                            "stored" if values[n] else "not-stored", "credential file", "not written by Olga"))
    return rows


# ---------------------------------------------------------------- the review
def review(doc: dict | None, source: Path | None, *, db_hosts: str | None = None,
           cm: set[str] | None | str = "ask", template: Path | None = TEMPLATE,
           project: Path | None = None) -> list[Row]:
    doc = doc or {}
    root = project or (cap._consult().project_root() if cap._consult() else Path.cwd())
    rows: list[Row] = []
    where = describe_file(source) if source else "no settings file"
    rows.append(Row("setup", "settings file in use", str(source) if source else "none found", "info", "project",
                    "-", where))
    try:
        others = [f for f in cap.settings_files() if source is None or f.resolve() != source.resolve()]
    except SystemExit:
        others = []
    if others:
        rows.append(Row("setup", "other settings files found", ", ".join(str(f) for f in others), "info",
                        "project", "-"))
    consult = cap._consult()
    packs = consult.registered_packs(root) if consult else []
    rows.append(Row("setup", "project", str(root), "info", "project", "-",
                    ".kittify/config.yaml " + ("found" if (root / ".kittify" / "config.yaml").is_file()
                                              else "not found")))
    if packs:
        rows.append(Row("setup", "registered packs", ", ".join(p.parent.name for p in packs), "info", "project",
                        "the project's .kittify/config.yaml (changed by configure_pc.py, not by Olga)"))
    if source is not None:
        progress = source.parent / "onboarding-progress.yaml"
        rows.append(Row("setup", "progress file", str(progress) if progress.is_file() else "none yet", "info",
                        "project", "beside the settings, when the team agrees",
                        "" if progress.is_file() else "Olga creates it from the template after the go-ahead"))

    settings_write = f"the same settings file ({source})" if source else "the settings file"
    leaves = flatten(doc)
    present = {k for k, _ in leaves}
    for key, value in leaves:
        if not key:
            continue
        sec = section_of(key)
        if is_secret_key(key) or is_secret_value(value):
            rows.append(Row(sec, key, ("written " + HIDDEN) if value not in UNSET else "not stored",
                            "stored" if value not in UNSET else "not-stored", "settings",
                            "remove it from the file; name the Credential Manager entry or .env key instead",
                            "a secret does not belong in the settings"))
            continue
        rows.append(Row(sec, key, render(value), leaf_state(key, value), "settings", settings_write))
        rows += env_rows(sec, key, value)

    if template is not None and template.is_file() and yaml is not None:
        tdoc = yaml.safe_load(template.read_text(encoding="utf-8")) or {}
        for key, _ in flatten(tdoc):
            if not key or key.startswith(NOT_ASKED) or key in present:
                continue
            if any(p.startswith(key + ".") or p.startswith(key + "[") for p in present):
                continue
            if "[" in key:
                continue
            rows.append(Row(section_of(key), key, "not in the file", "missing", "template", settings_write,
                            "the template asks for it"))

    rows += database_rows(doc, source, db_hosts, credential_targets() if cm == "ask" else cm)  # type: ignore[arg-type]
    rows += credential_file_rows(doc, root)

    if source is not None or doc:
        for a in cap.every(doc, str(source) if source else ""):
            sec = CAP_SECTION.get(a.agent) or ("rela-release-notes" if a.capability == "release_notes"
                                               else "rela-release")
            rows.append(Row(sec, f"capability {a.agent}.{a.capability}", a.state,
                            "info" if a.state in ("on", "off", "agent-off") else "open", "derived",
                            f"comes from desk.{a.agent}.{a.capability} in the settings",
                            "" if a.state == "on" else a.message))
    order = {sid: i for i, (sid, _, _) in enumerate([("setup", "", [])] + SECTIONS + [("other", "", [])])}
    return sorted(rows, key=lambda r: order.get(r.section, len(order)))


def _cell(text: str, width: int = 110) -> str:
    text = str(text).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= width else text[: width - 3] + "..."


def to_markdown(rows: list[Row]) -> str:
    titles = {"setup": "Where the settings are read from", "other": "Other settings",
              **{sid: title for sid, title, _ in SECTIONS}}
    out: list[str] = []
    n = 0
    for i, sid in enumerate(["setup"] + [s for s, _, _ in SECTIONS] + ["other"]):
        sec = [r for r in rows if r.section == sid]
        if not sec:
            continue
        out += ["", f"## {i}. {titles[sid]}" + ("" if sid in ("setup", "other") else f"  (section {sid})"), "",
                "| # | Setting | Currently | From | State |", "|---|---|---|---|---|"]
        for r in sec:
            n += 1
            state = {"open": "OPEN -- ask", "partial": "OPEN (partial)", "missing": "OPEN (not in the file)",
                     "not-stored": "OPEN (not stored)"}.get(r.state, r.state)
            current = r.value + (f" -- {r.note}" if r.note and r.section != "setup" else "")
            if r.section == "setup" and r.note:
                current = f"{r.value} -- {r.note}"
            out.append(f"| {n} | `{_cell(r.key, 70)}` | {_cell(current)} | {r.origin} | {state} |")
    open_rows = [r for r in rows if r.is_open]
    out += ["", f"## Summary: {len(rows)} rows, {sum(1 for r in rows if r.state == 'set')} set, "
                f"{len(open_rows)} open", ""]
    for sid in [s for s, _, _ in SECTIONS] + ["other"]:
        keys = [r.key for r in open_rows if r.section == sid]
        if keys:
            out.append(f"- {sid}: " + ", ".join(f"`{k}`" for k in keys))
    out += ["", "Corrections go back where the value came from: settings rows to the same settings file, "
                "environment rows to your user environment variable, hosts rows to the hosts file. "
                "Secrets are never shown and never written by Olga."]
    return "\n".join(out).lstrip("\n") + "\n"


# ---------------------------------------------------------------- set: one confirmed correction
class Refused(Exception):
    pass


def customer_names(path: str | None) -> list[str]:
    if path:
        return [n.strip() for n in Path(path).read_text(encoding="utf-8-sig").splitlines()
                if n.strip() and not n.lstrip().startswith("#")]
    env = os.environ.get("PRODUCT_DESK_CUSTOMER_NAMES", "")
    return [n.strip() for n in env.split("|") if n.strip()]


def names_customer(value: str, names: list[str]) -> str | None:
    for n in names:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", value, re.I):
            return n
    return None


def inline(value) -> str:
    text = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10 ** 6).strip()
    if text.endswith("\n..."):
        text = text[: -len("\n...")]
    if text.endswith("..."):
        text = text[:-3].rstrip()
    return text


def _split_comment(rest: str) -> tuple[str, str]:
    """(value text, '  # comment' with its leading spaces) of the part after `key:`."""
    quote, depth = None, 0
    for i, ch in enumerate(rest):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "#" and depth <= 0 and (i == 0 or rest[i - 1] in " \t"):
            j = i
            while j > 0 and rest[j - 1] in " \t":
                j -= 1
            return rest[:j], rest[j:]
    return rest.rstrip(), ""


def _set_in(doc: dict, key: str, value) -> None:
    parts = key.split(".")
    node = doc
    for p in parts[:-1]:
        node = node[p]
    node[parts[-1]] = value


def set_yaml(path: Path, key: str, raw: str, names: list[str]) -> tuple[str, str]:
    """(old text, new text) with one scalar or inline value replaced; comments and layout kept."""
    if yaml is None:
        raise Refused("PyYAML is needed: python -m pip install --user pyyaml")
    if "[" in key or "]" in key:
        raise Refused(f"{key} sits inside a list; edit it by hand and show the diff first")
    if is_secret_key(key) or is_secret_value(raw):
        raise Refused("a secret is never written into the settings; name the Credential Manager entry or "
                      ".env key instead")
    hit = names_customer(raw, names)
    if hit:
        raise Refused("a customer name never goes into the settings file; record where it lives instead")
    try:
        value = yaml.safe_load(raw) if raw.strip() else ""
    except yaml.YAMLError:
        value = raw
    if isinstance(value, dict):
        raise Refused("a mapping is a block; edit it by hand and show the diff first")
    data = path.read_bytes()
    bom = data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    start, end, parent = 0, len(lines), -1
    target = None
    for depth, seg in enumerate(key.split(".")):
        child_indent = None
        found = None
        for i in range(start, end):
            body = lines[i].rstrip("\r\n")
            if not body.strip() or body.lstrip().startswith("#"):
                continue
            indent = len(body) - len(body.lstrip(" "))
            if indent <= parent:
                break
            if child_indent is None:
                child_indent = indent
            if indent != child_indent:
                continue
            if re.match(rf"^\s*['\"]?{re.escape(seg)}['\"]?\s*:(\s|$)", body):
                found = (i, indent)
                break
        if found is None:
            raise Refused(f"{key} is not a key of {path.name} (only an existing key is corrected here; a new one "
                          "is added by hand after showing the diff)")
        i, indent = found
        block_end = end
        for j in range(i + 1, end):
            b = lines[j].rstrip("\r\n")
            if b.strip() and not b.lstrip().startswith("#") and len(b) - len(b.lstrip(" ")) <= indent:
                block_end = j
                break
        start, end, parent, target = i + 1, block_end, indent, i
    assert target is not None
    line = lines[target]
    newline = line[len(line.rstrip("\r\n")):]
    body = line.rstrip("\r\n")
    m = re.match(r"^(\s*['\"]?[^:'\"]+['\"]?\s*:)(\s*)(.*)$", body)
    if not m:
        raise Refused(f"cannot read the line of {key}")
    head, gap, rest = m.group(1), m.group(2), m.group(3)
    old_value, comment = _split_comment(rest)
    if not old_value.strip() or old_value.strip()[:1] in "|>":
        raise Refused(f"{key} holds a block; edit it by hand and show the diff first")
    # on / off / yes / no stay as typed: the settings write switches that way, and they read back the same
    new_value = raw.strip() if isinstance(value, bool) and re.fullmatch(r"[A-Za-z]+", raw.strip()) else inline(value)
    pad = comment
    if comment:
        col = len(head) + len(gap or " ") + len(old_value)
        new_col = len(head) + len(gap or " ") + len(new_value)
        spaces = len(comment) - len(comment.lstrip(" \t"))
        pad = " " * max(1, spaces + col - new_col) + comment.lstrip(" \t")
    lines[target] = f"{head}{gap or ' '}{new_value}{pad}{newline}"
    new_text = "".join(lines)
    old_doc = yaml.safe_load(text) or {}
    want = copy.deepcopy(old_doc)
    _set_in(want, key, value)
    if (yaml.safe_load(new_text) or {}) != want:
        raise Refused(f"the edit of {key} did not read back as exactly that one change; nothing was written")
    return ("\ufeff" if bom else "") + text, ("\ufeff" if bom else "") + new_text


def tracked_by_git(path: Path) -> bool:
    """True unless git confirms the file is ignored; a repository git cannot answer for counts as tracked."""
    repo = git_root(path)
    if repo is None:
        return False
    if shutil.which("git") is None:
        return True
    r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(path.resolve())],
                       capture_output=True, text=True)
    return r.returncode != 0


def set_env_file(path: Path, key: str, value: str) -> tuple[str, str]:
    if not ENV_NAME.match(key) and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        raise Refused(f"{key} is not an env key")
    if is_secret_key(key) or is_secret_value(value):
        raise Refused("a secret is never written by Olga; store the login in Credential Manager or let the user "
                      "edit the .env file")
    if tracked_by_git(path):
        raise Refused(f"{path} is in a git repository and not git-ignored; user-local values never go into a "
                      "repository")
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    lines = text.splitlines(keepends=True)
    done = False
    for i, line in enumerate(lines):
        if re.match(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=", line):
            nl = line[len(line.rstrip("\r\n")):] or "\n"
            lines[i] = f"{key}={value}{nl}"
            done = True
            break
    if not done:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
    return text, "".join(lines)


def diff(old: str, new: str, name: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        f"{name} (now)", f"{name} (after)"))


def set_user_env(name: str, value: str, apply: bool) -> str:
    if not ENV_NAME.match(name):
        raise Refused(f"{name} is not an environment variable name")
    if is_secret_key(name) or is_secret_value(value):
        raise Refused("a secret is never written by Olga")
    current = os.environ.get(name)
    if not apply:
        return f"would set user variable {name} to {value} (now: {current if current is not None else 'not set'})"
    if os.name == "nt":
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        return f"set user variable {name}={value} (open a new shell or restart Cursor to see it)"
    return f"add to your shell profile: export {name}={value}"


def cmd_set(a) -> int:
    try:
        if a.user_env:
            print(set_user_env(a.user_env, a.value, a.apply))
            return 0
        if a.env_file:
            path = Path(a.env_file).expanduser()
            old, new = set_env_file(path, a.key, a.value)
        else:
            if not a.settings or not a.key:
                print("set needs --settings and --key (or --env-file / --user-env)", file=sys.stderr)
                return USAGE
            path = Path(a.settings).expanduser()
            if not path.is_file():
                print(f"settings file not found: {path}", file=sys.stderr)
                return USAGE
            old, new = set_yaml(path, a.key, a.value, customer_names(a.customer_names))
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return REFUSED
    if old == new:
        print("no change: the value is already that")
        return 0
    print(diff(old.lstrip("\ufeff"), new.lstrip("\ufeff"), path.name), end="")
    if not a.apply:
        print("dry run: nothing written (add --apply after the user's go-ahead)")
        return 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    repo = git_root(path)
    print(f"written: {path}" + (f" (in git repository {repo}; not committed)" if repo and not a.env_file else ""))
    return 0


def cmd_show(a) -> int:
    for attr in ("settings", "db_hosts"):
        if getattr(a, attr):
            setattr(a, attr, str(Path(getattr(a, attr)).expanduser().resolve()))
    if a.project:
        os.chdir(Path(a.project).expanduser())
    try:
        doc, where = cap.load(a.settings, a.product)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return USAGE
    source = Path(where) if doc is not None else None
    rows = review(doc, source, db_hosts=a.db_hosts, project=Path.cwd() if a.project else None)
    if a.section:
        rows = [r for r in rows if r.section in ("setup", a.section)]
    if a.json:
        print(json.dumps([asdict(r) | {"open": r.is_open} for r in rows], indent=2, ensure_ascii=False))
    else:
        print(to_markdown(rows), end="")
    return 0


# ---------------------------------------------------------------- self-test (synthetic, offline)
def selftest() -> int:
    fails: list[str] = []

    def check(cond: bool, what: str) -> None:
        if not cond:
            fails.append(what)

    secret_a = "Wq7" + "zLm2" + "Pv9x" + "Rt4k"
    secret_b = "Hn3" + "bXy8" + "Kc6d" + "Jf1s"
    customer = "Synthetic" + "corp Bank"
    keep = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "PRODUCT_DESK_HOME", "PRODUCT_DESK_SETTINGS",
                                           "SPEC_KITTY_PACK_HOME", "DEMO_REVIEW_REPO", "DEMO_REVIEW_UNSET",
                                           "PRODUCT_DESK_CUSTOMER_NAMES", "PRODUCT_DESK_REVIEW_NO_REGISTRY")}
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="settings-review-") as t:
        tmp = Path(t)
        user = tmp / "user"
        repo = tmp / "team"
        (repo / ".git").mkdir(parents=True)
        (repo / "product-desk").mkdir()
        clone = tmp / "clone"
        clone.mkdir()
        hosts = user / ".regnology" / "demo-db" / "team-targets.local.env"
        hosts.parent.mkdir(parents=True)
        hosts.write_text("DB_TARGETS=demo-db\nDB_DEMO_DB_HOST=db.example.test\nDB_DEMO_DB_DATABASE=<database>\n"
                         f"DB_DEMO_DB_PASSWORD={secret_a}\n", encoding="utf-8")
        cred = user / "GIT" / "secrets" / ".env.demo"
        cred.parent.mkdir(parents=True)
        cred.write_text(f"DEMO_API_EMAIL=someone@example.com\nDEMO_API_TOKEN={secret_b}\nOTHER=1\n", encoding="utf-8")
        settings = repo / "product-desk" / "product-desk.yaml"
        settings.write_text(
            "schema_version: \"2.0\"\n"
            "product:\n"
            "  id: demo\n"
            "  short_name: Demo\n"
            "  owners:\n"
            "    product_owner: TBD          # confirm at review\n"
            "    release_manager: Pat Example\n"
            "desk:\n"
            "  agents: {clerk-clara: on, qa-qata: off, release-rela: on}\n"
            "  onboarding: {product: done, data_pipeline: TBD, rela_release: partial}\n"
            "  clara:\n"
            "    tickets:\n"
            "      stale_after_days: 30\n"
            "      workflow: TBD\n"
            "      data:\n"
            "        folder: [$DEMO_REVIEW_UNSET, ~/demo-board]\n"
            "  qata:\n"
            "    qat: {status: TBD}\n"
            "  rela:\n"
            "    release_notes: {status: on, source_jql: \"project = DEMO\", sections: [What changed], "
            "format: markdown}\n"
            "tracker:\n"
            "  instance: https://tracker.example.com\n"
            "  read_tools: demo_*\n"
            "  projects:\n"
            "    - {key: DEMO, role: development}\n"
            "code:\n"
            "  repos:\n"
            "    - {id: app, host: example, project: TBD, clone_env: DEMO_REVIEW_REPO}\n"
            "databases:\n"
            "  - {target: demo-db, engine: sqlserver, purpose: demo, access: read-only}\n"
            "database_server:\n"
            "  source: mcp/demo-db\n"
            "  hosts_file: mcp/demo-db/team-targets.local.env\n"
            "  credential_target: \"demo-cm/{target}\"\n"
            "credentials:\n"
            "  jira: secrets/.env.demo (DEMO_API_*)\n"
            "  databases: Windows Credential Manager entries of the demo-db server\n", encoding="utf-8")
        try:
            for k in keep:
                os.environ.pop(k, None)
            os.environ["HOME"] = os.environ["USERPROFILE"] = str(user)
            os.environ["DEMO_REVIEW_REPO"] = str(clone)
            os.environ["PRODUCT_DESK_REVIEW_NO_REGISTRY"] = "1"
            os.chdir(tmp)
            doc = yaml.safe_load(settings.read_text(encoding="utf-8"))
            rows = review(doc, settings, cm={"demo-cm/demo-db"}, project=tmp)
            md = to_markdown(rows)
            js = json.dumps([asdict(r) for r in rows])
            by = {r.key: r for r in rows}

            # negative: a secret never reaches the output, in any form
            for s in (secret_a, secret_b):
                check(s not in md and s not in js, "a secret value reached the review output")
            check(by.get("hosts: DB_DEMO_DB_PASSWORD") is not None
                  and by["hosts: DB_DEMO_DB_PASSWORD"].state == "stored", "hosts password not reported as stored")
            check(by.get("credentials.jira (file): DEMO_API_TOKEN") is not None
                  and by["credentials.jira (file): DEMO_API_TOKEN"].state == "stored", "credential key not stored")
            check("credentials.jira (file): OTHER" not in by, "a key outside the named pattern was listed")
            check(by.get("login for demo-db") is not None and by["login for demo-db"].state == "stored",
                  "Credential Manager target not found")
            rows_none = review(doc, settings, cm=set(), project=tmp)
            check(any(r.key == "login for demo-db" and r.state == "not-stored" for r in rows_none),
                  "a missing Credential Manager entry is not open")

            # TBD, partial and missing are open questions; set values are shown with their source
            check(by["product.owners.product_owner"].state == "open", "TBD owner not open")
            check(by["code.repos[app].project"].state == "open", "TBD inside a list not open")
            check(by["desk.onboarding.rela_release"].state == "partial", "partial section not open")
            check(by["product.owners.release_manager"].state == "set"
                  and by["product.owners.release_manager"].value == "Pat Example", "set value not shown")
            check(any(r.section == "data-pipeline" and r.state == "missing" for r in rows),
                  "a template key missing from the file is not open")
            check(by["hosts: DB_DEMO_DB_HOST"].value == "db.example.test", "host not shown")
            check(by["hosts: DB_DEMO_DB_DATABASE"].state == "open", "placeholder host value not open")
            env = by.get("code.repos[app].clone_env -> $DEMO_REVIEW_REPO")
            check(env is not None and env.value == str(clone), "clone_env not resolved")
            folder = by.get("desk.clara.tickets.data.folder (on this machine)")
            check(folder is not None and folder.value.endswith("demo-board"), "user-local path not resolved")
            check("OPEN -- ask" in md and "Summary:" in md, "markdown lacks open flags or summary")
            caps = {r.key: r.value for r in rows if r.key.startswith("capability ")}
            check(caps.get("capability rela.release_notes") == "on", "capability on not shown")
            check(caps.get("capability qata.qat") == "agent-off", "agent-off not shown")
            check(by["settings file in use"].note.startswith("the team settings file")
                  and "git repository" in by["settings file in use"].note, "settings source not described")

            # set: one scalar, comment and layout kept; dry run writes nothing
            before = settings.read_text(encoding="utf-8")
            old, new = set_yaml(settings, "product.owners.product_owner", "Jane Example", [])
            check(settings.read_text(encoding="utf-8") == before, "set wrote during a dry run")
            changed = [ln for ln in difflib.ndiff(old.splitlines(), new.splitlines()) if ln[:1] in "+-"]
            check(len(changed) == 2 and "Jane Example" in changed[1] and "# confirm at review" in changed[1],
                  f"set changed more than the one line, or lost its comment: {changed}")
            check(yaml.safe_load(new)["product"]["owners"]["product_owner"] == "Jane Example", "set did not read back")
            _, new2 = set_yaml(settings, "desk.clara.tickets.stale_after_days", "45", [])
            check(yaml.safe_load(new2)["desk"]["clara"]["tickets"]["stale_after_days"] == 45, "int not written")

            # negative: what set refuses
            for args, why in [
                (("desk.clara.tickets", "x", []), "a block"),
                (("tracker.projects[DEMO].role", "support", []), "a list item"),
                (("credentials.api_token", "abc", []), "a secret key"),
                (("product.short_name", "password=" + secret_a, []), "a secret value"),
                (("product.short_name", customer, [customer]), "a customer name"),
                (("product.nickname", "Demo", []), "a key that is not there"),
            ]:
                try:
                    set_yaml(settings, *args)
                    fails.append(f"set accepted {why}")
                except Refused:
                    pass
            check(settings.read_text(encoding="utf-8") == before, "a refused set changed the file")

            # env files: user-local is written, a secret or a repository file is refused
            old_h, new_h = set_env_file(hosts, "DB_DEMO_DB_DATABASE", "demo")
            check("DB_DEMO_DB_DATABASE=demo" in new_h and secret_a in new_h, "env set lost a line")
            for path, key in [(hosts, "DB_DEMO_DB_PASSWORD"), (repo / "product-desk" / "local.env", "DB_X_HOST")]:
                try:
                    set_env_file(path, key, "value")
                    fails.append(f"env set accepted {key} in {path.name}")
                except Refused:
                    pass
            try:
                set_user_env("DEMO_API_TOKEN", "x", apply=False)
                fails.append("user env accepted a secret name")
            except Refused:
                pass
            check("would set user variable DEMO_REVIEW_REPO" in set_user_env("DEMO_REVIEW_REPO", "x", apply=False),
                  "user env dry run")

            # the command line: show --json and set --apply end to end
            out = subprocess.run([sys.executable, "-B", str(Path(__file__)), "show", "--settings", str(settings),
                                  "--json"], capture_output=True, text=True, encoding="utf-8", env=dict(os.environ))
            check(out.returncode == 0 and secret_a not in out.stdout and secret_b not in out.stdout
                  and '"open": true' in out.stdout, f"show --json failed: {out.stderr[-300:]}")
            r = subprocess.run([sys.executable, "-B", str(Path(__file__)), "set", "--settings", str(settings), "--key",
                                "product.owners.product_owner", "--value", "Jane Example", "--apply"],
                               capture_output=True, text=True, encoding="utf-8", env=dict(os.environ))
            check(r.returncode == 0 and "Jane Example" in settings.read_text(encoding="utf-8")
                  and "# confirm at review" in settings.read_text(encoding="utf-8"), "set --apply failed")
            r = subprocess.run([sys.executable, "-B", str(Path(__file__)), "set", "--settings", str(settings), "--key",
                                "product.short_name", "--value", customer, "--apply"],
                               capture_output=True, text=True, encoding="utf-8",
                               env=dict(os.environ, PRODUCT_DESK_CUSTOMER_NAMES=f"Other|{customer}"))
            check(r.returncode == REFUSED and customer not in settings.read_text(encoding="utf-8"),
                  "a customer name was written through the command line")

            # the template: no capability status on, every capability but the tickets default not on,
            # and its TBD values are open questions
            if TEMPLATE.is_file():
                tdoc = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
                trows = review(tdoc, TEMPLATE, cm=set(), template=None, project=tmp)
                check(not [r for r in trows if r.key.startswith("desk.") and r.key.endswith(".status")
                           and r.value == "on"], "the template switches a capability on")
                check(not any(r.key.startswith("capability ") and r.value == "on" for r in trows),
                      "a template capability is on")
                check(sum(r.is_open for r in trows) > 20, "the template's TBD values are not open")
        finally:
            os.chdir(cwd)
            for k, v in keep.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    for f in fails:
        print("FAIL:", f)
    print("settings_review selftest:", "PASS" if not fails else f"FAILED ({len(fails)})")
    return 0 if not fails else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show", help="every current setting, its source and whether it is open")
    s.add_argument("--settings")
    s.add_argument("--product")
    s.add_argument("--project", help="the folder holding .kittify/ (default: the current folder)")
    s.add_argument("--section", help="one section id, e.g. tracker or qata-qat")
    s.add_argument("--db-hosts", help="the database hosts file, when it is not beside the settings")
    s.add_argument("--json", action="store_true")
    w = sub.add_parser("set", help="write one confirmed correction where the value came from")
    w.add_argument("--settings")
    w.add_argument("--env-file")
    w.add_argument("--user-env")
    w.add_argument("--key")
    w.add_argument("--value", required=True)
    w.add_argument("--customer-names", help="file with one customer name per line (never committed)")
    w.add_argument("--apply", action="store_true")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    if yaml is None:
        print("PyYAML is needed: python -m pip install --user pyyaml", file=sys.stderr)
        return USAGE
    if a.cmd == "show":
        return cmd_show(a)
    if a.env_file and not a.key:
        print("set --env-file needs --key", file=sys.stderr)
        return USAGE
    return cmd_set(a)


if __name__ == "__main__":
    sys.exit(main())
