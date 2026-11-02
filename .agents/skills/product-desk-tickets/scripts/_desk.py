"""Shared helpers for the desk skills: the team's settings, the capability gate,
a read-only tracker client, and where a named asset or skill script lives.

Nothing here knows a team. Every value comes from the team's product-desk.yaml:
the tracker host and its login file, the packs that hold its assets, the skill
that does a lookup. A capability that is not on is refused before any work,
with the gate's own message ("not set up ... ask Olga").

The settings file: --settings <file> anywhere on the command line (taken off
before the script parses its own arguments), else PRODUCT_DESK_SETTINGS, else
the lookup of skill product-desk-capability. --product <id> picks one product
when several have settings.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]                       # <repo>/skills/desk/<skill>/scripts
UNSET = (None, "", "TBD", "tbd", [], {})
NOT_SET_UP = 3
_ENV_VAR = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def take_flag(argv: list[str], flag: str) -> str | None:
    """The value of `flag` (`--x v` or `--x=v`), removed from argv; None when absent."""
    for i, arg in enumerate(argv[1:], 1):
        if arg == flag and i + 1 < len(argv):
            value = argv[i + 1]
            del argv[i:i + 2]
            return value
        if arg.startswith(flag + "="):
            del argv[i]
            return arg.split("=", 1)[1]
    return None


_EXPLICIT = take_flag(sys.argv, "--settings")
_PRODUCT = take_flag(sys.argv, "--product")
_CACHE: dict = {}


def _module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def capability():
    """Skill product-desk-capability, installed beside this one."""
    for c in (HERE.parents[1] / "product-desk-capability", ROOT / "skills" / "desk" / "product-desk-capability"):
        if (c / "scripts" / "capability.py").is_file():
            return _module("product_desk_capability", c / "scripts" / "capability.py")
    raise SystemExit("skill product-desk-capability is not installed beside this skill")


def load(explicit: str | None = None, product: str | None = None) -> tuple[dict | None, str]:
    """(settings, where from). None when no settings were found."""
    explicit = explicit if explicit is not None else (_EXPLICIT or os.environ.get("PRODUCT_DESK_SETTINGS"))
    product = product if product is not None else _PRODUCT
    key = (explicit or "", product or "")
    if key not in _CACHE:
        if explicit and explicit.lower() in ("none", "off"):
            _CACHE[key] = (None, "settings off")
        else:
            _CACHE[key] = capability().load(explicit, product)
    return _CACHE[key]


def gate(agent: str, cap: str, doc: dict | None = None, source: str = ""):
    """The capability's answer when it is on; otherwise its message on stderr and exit 3."""
    if doc is None:
        doc, source = load()
    ans = capability().resolve(doc, agent, cap, source)
    if not ans.on:
        print(ans.message, file=sys.stderr)
        raise SystemExit(NOT_SET_UP)
    return ans


def get(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return default if d in UNSET else d


def expand(value) -> Path | None:
    """A path from the settings. A list is a set of candidates: the first whose $VARs are all set
    wins, whether or not it exists. `~` is the user's home; a relative path is under ~/GIT."""
    cands = value if isinstance(value, list) else [value]
    for c in cands:
        if c in UNSET:
            continue
        s = str(c)
        names = _ENV_VAR.findall(s)
        if any(not os.environ.get(n) for n in names):
            continue
        s = _ENV_VAR.sub(lambda m: os.environ[m.group(1)], s)
        p = Path(os.path.expanduser(s))
        return p if p.is_absolute() else Path.home() / "GIT" / p
    return None


def settings_file(source: str) -> Path | None:
    p = Path(source) if source else None
    return p if p is not None and p.is_file() else None


# ---------------------------------------------------------------- assets and skills
def _pack_dirs(doc: dict | None, source: str) -> list[Path]:
    out: list[Path] = []
    own = settings_file(source)
    if own is not None:
        out.append(own.parent.parent / "pack")          # <product pack>/product-desk/product-desk.yaml
    names = list(get(doc, "extensions", "packs", default=[]) or [])
    names += [get(doc, "desk", "specialist", "product_pack"), get(doc, "desk", "specialist", "pack")]
    out += [ROOT / "packs" / str(n) / "pack" for n in names if n not in UNSET]
    out.append(ROOT / "pack")
    return [p for i, p in enumerate(out) if p.is_dir() and p not in out[:i]]


def asset_file(doc: dict | None, source: str, ref) -> Path | None:
    """A file named in the settings: a path, or an asset id resolved through its sidecar in the
    team's packs (its own product pack first, then extensions.packs, then this repo's pack)."""
    if ref in UNSET:
        return None
    p = expand(ref)
    if p is not None and p.is_file():
        return p
    for pack in _pack_dirs(doc, source):
        side = pack / "assets" / f"{ref}.asset.yaml"
        if side.is_file():
            m = re.search(r"^path:\s*(\S+)", side.read_text(encoding="utf-8"), re.M)
            if m and (pack / "assets" / m.group(1)).is_file():
                return pack / "assets" / m.group(1)
    return None


def skill_script(skill: str, script: str) -> Path | None:
    """A script of a skill in this repo (desk skills, then every pack's skills)."""
    if skill in UNSET or script in UNSET:
        return None
    for base in (ROOT / "skills", *sorted((ROOT / "packs").glob("*/skills"))):
        for c in (base / skill, *base.glob(f"*/{skill}")):
            f = c / "scripts" / script
            if f.is_file():
                return f
    return None


# ---------------------------------------------------------------- tracker (read-only)
def read_env_file(path: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if path is None or not path.exists():
        return out
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def tracker_env(doc: dict | None) -> Path | None:
    value = get(doc, "tracker", "write_env_file")
    if value is None:
        return None
    if os.environ.get("REGNOLOGY_MCP_HOME"):
        return Path(os.environ["REGNOLOGY_MCP_HOME"]) / Path(str(value).split(" (")[0].strip()).name
    return expand(str(value).split(" (")[0].strip())


def tracker_host(doc: dict | None) -> str | None:
    inst = get(doc, "tracker", "instance")
    return urlparse(str(inst)).hostname if inst else None


class Tracker:
    """Read-only client for the team's tracker. GET plus the search POST; nothing that writes.
    Refuses any host other than the one in tracker.instance."""

    def __init__(self, doc: dict | None) -> None:
        import requests
        env_file = tracker_env(doc)
        env = read_env_file(env_file)
        url = os.environ.get("JIRA_API_URL") or env.get("JIRA_API_URL", "")
        email = os.environ.get("JIRA_API_EMAIL") or env.get("JIRA_API_EMAIL", "")
        token = os.environ.get("JIRA_API_TOKEN") or env.get("JIRA_API_TOKEN", "")
        name = env_file.name if env_file else "the env file named in tracker.write_env_file"
        if not (url and email and token):
            raise SystemExit(f"Jira Cloud credentials not found (JIRA_API_* in env or {name})")
        host = tracker_host(doc)
        if not host or host not in url:
            raise SystemExit(f"refusing non-Cloud Jira host; only {host or 'the host in tracker.instance'} is allowed")
        self.base = url.rstrip("/") + "/"
        self.s = requests.Session()
        self.s.auth = (email, token)
        self.s.headers["Accept"] = "application/json"

    def get(self, path: str, **params):
        r = self.s.get(self.base + path.lstrip("/"), params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def search(self, jql: str, fields: list[str], max_results: int = 50) -> list[dict]:
        """Up to `max_results` issues, read across as many result pages as that takes, each key once."""
        return search_all(self, jql, fields, cap=max_results)[0]


PAGE_SIZE = 100


def search_all(client, jql: str, fields: list[str], cap: int = 500) -> tuple[list[dict], bool]:
    """Every issue a JQL returns, each key once, up to `cap`; the flag says whether the cap cut it short.

    Reads every result page: Jira Cloud's `nextPageToken` (until `isLast`), or `startAt` + `total`
    when the response pages that way. An issue a later page repeats (the order moved while paging)
    is kept once, so a count or a split never sees it twice."""
    out, seen, token, start = [], set(), None, 0
    for _ in range(cap // PAGE_SIZE + 50):
        body = {"jql": jql, "maxResults": max(1, min(PAGE_SIZE, cap - len(out))), "fields": list(fields)}
        if token:
            body["nextPageToken"] = token
        elif start:
            body["startAt"] = start
        r = client.s.post(client.base + "search/jql", timeout=60, json=body)
        r.raise_for_status()
        js = r.json()
        issues = js.get("issues") or []
        for iss in issues:
            key = iss.get("key")
            if key not in seen:
                seen.add(key)
                out.append(iss)
        token = js.get("nextPageToken")
        if token:
            more = not js.get("isLast", False)
        else:
            start = int(js.get("startAt") or start) + len(issues)
            more = bool(issues) and js.get("total") is not None and start < int(js["total"])
        if not more:
            return out, False
        if len(out) >= cap:
            return out[:cap], True
    return out[:cap], True


def project_keys(doc: dict | None, roles: tuple[str, ...]) -> list[str]:
    """Tracker project keys with one of these roles, in the settings' order."""
    return [str(p["key"]) for p in get(doc, "tracker", "projects", default=[]) or []
            if isinstance(p, dict) and p.get("key") not in UNSET and p.get("role") in roles]


def fix_version_prefix(doc: dict | None) -> str:
    """The text before {v} in tracker.fix_version_pattern, e.g. 'My Product ' -> 'My Product'."""
    pat = str(get(doc, "tracker", "fix_version_pattern", default="") or "")
    return pat.split("{v}", 1)[0].rstrip() if "{v}" in pat else ""
