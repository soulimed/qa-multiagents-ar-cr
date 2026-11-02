#!/usr/bin/env python3
"""A desk agent's Jira comment: an executive summary on top, the full analysis folded below.

The analysis is written as Markdown with two sections:

    ## Executive summary
    - one line per finding, with the action it needs (1 to 5 lines)

    ## Full analysis
    ...anything: headings, paragraphs, lists, tables, code blocks...

The comment shows the agent's opener, the executive summary in an info panel,
one collapsed "Full analysis" section holding everything else, and the agent's
sign-off. A Jira comment's expand cannot hold another expand, so the full
analysis uses headings for its own structure.

Who is speaking comes from the product's desk settings (product-desk.yaml):
`extensions.<agent>.comment` gives the agent's name, opener and sign-off, on top
of the shared `extensions.all.comment`; `{on_behalf_of}` in a sign-off is replaced
by `comment.on_behalf_of` (refused when unset); the Jira host is `tracker.instance`, the
login file is `tracker.write_env_file`, and the ticket keys shown as smart links
are `comment.card_projects`, else every `tracker.projects` key.

    desk_comment.py render   --agent A --in analysis.md [--title T] [--out body.json]
    desk_comment.py post     --agent A --in analysis.md --key KEY [--title T] [--replace ID] [--post]
    desk_comment.py identity --agent A
    desk_comment.py selftest                      (also: --selftest)

Every command takes [--settings product-desk.yaml] [--product ID]; without
--settings the file is found as in toolguide product-desk-settings
(PRODUCT_DESK_SETTINGS, PRODUCT_DESK_HOME, <project>/product-desk, the product
packs registered in <project>/.kittify/config.yaml).

`post` prints the preview and writes nothing without --post (--apply is the
same flag). It writes only to the settings' Jira Cloud host, through REST v3,
and reads the comment back. Credentials: JIRA_API_URL / JIRA_API_EMAIL /
JIRA_API_TOKEN, else the env file named in the settings (or --env-file). They
are never printed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

MAX_SUMMARY = 5
MAX_CHARS = 30000
CLOUD_MARKUP = "cloud-markdown"
UNSET = (None, "", "TBD", "tbd", [], {})
ON_BEHALF_OF = "{on_behalf_of}"

SUMMARY_H = re.compile(r"^#{1,6}\s*executive summary\s*$", re.I)
FULL_H = re.compile(r"^#{1,6}\s*full analysis\b.*$", re.I)
GREETING = re.compile(r"^\s*(hi|hello|hey)\b\W*", re.I)
DASH_LEAD = re.compile(r"^\s*[—-]+\s*")


# ---------------------------------------------------------------- identity
@dataclass
class Identity:
    agent: str
    name: str
    opener: str
    sign_off: str
    host: str
    card_projects: tuple[str, ...]
    env_file: Path | None = None
    markup: str = CLOUD_MARKUP
    source: str = ""
    opener_line: re.Pattern = field(init=False, repr=False)
    sign_off_line: re.Pattern = field(init=False, repr=False)

    def __post_init__(self):
        for what, text in (("opener", self.opener), ("sign_off", self.sign_off)):
            if text in UNSET or "\n" in str(text):
                raise ValueError(f"comment.{what} for {self.agent} must be one line of text "
                                 f"(extensions.{self.agent}.comment in {self.source or 'the desk settings'})")
        self.opener_line = opener_pattern(self.opener)
        self.sign_off_line = sign_off_pattern(self.sign_off, self.name)


def opener_pattern(opener: str) -> re.Pattern:
    """An opener line, also when the author typed it with another greeting or punctuation."""
    text = opener.strip()
    m = GREETING.match(text)
    tail = re.sub(r"\W+$", "", text[m.end():] if m else text)
    if not tail:
        return re.compile(r"^\s*" + re.escape(text) + r"\s*$", re.I)
    lead = r"^\s*(hi|hello|hey)\b.*" if m else r"^\s*"
    return re.compile(lead + re.escape(tail) + r"\W*$", re.I)


def sign_off_pattern(sign_off: str, name: str) -> re.Pattern:
    """A sign-off line: its first four words, then the agent's name when the sign-off carries it."""
    text = sign_off.strip()
    dashed = DASH_LEAD.match(text)
    body = text[dashed.end():] if dashed else text
    words = body.split()
    stem = " ".join(words[:4])
    rest = " ".join(words[4:])
    lead = r"^\s*[—-]+\s*" if dashed else r"^\s*"
    pat = lead + re.escape(stem)
    if name and re.search(re.escape(name), rest, re.I):
        pat += r" .*" + re.escape(name)
    return re.compile(pat, re.I)


def _get(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return default if d in UNSET else d


def _env_path(value: str | None) -> Path | None:
    if value in UNSET:
        return None
    p = Path(os.path.expanduser(str(value).split(" (")[0].strip()))
    return p if p.is_absolute() else Path.home() / "GIT" / p


def identity_from(settings: dict, agent: str, source: str = "") -> Identity:
    """The agent's comment identity: extensions.all.comment, then extensions.<agent>.comment on top."""
    ext = settings.get("extensions") or {}
    key = agent
    if agent not in ext:
        by_name = [k for k, v in ext.items()
                   if isinstance(v, dict) and str(_get(v, "comment", "name", default="")).lower() == agent.lower()]
        if len(by_name) == 1:
            key = by_name[0]
    own = _get(ext, key, "comment", default={})
    if not own:
        have = sorted(k for k, v in ext.items() if k != "all" and isinstance(v, dict) and _get(v, "comment"))
        raise ValueError(f"no comment identity for {agent!r} in {source or 'the desk settings'}; "
                         f"add extensions.{agent}.comment (name, opener, sign_off) -- "
                         f"agents with one: {', '.join(have) or 'none'}")
    merged = {**(_get(ext, "all", "comment", default={}) or {}), **own}
    instance = _get(settings, "tracker", "instance")
    host = urlparse(str(instance)).hostname if instance else None
    if not host:
        raise ValueError(f"tracker.instance is not set in {source or 'the desk settings'} "
                         "(re-run onboarding section `tracker`)")
    projects = merged.get("card_projects")
    if projects in UNSET:
        projects = [p.get("key") for p in (_get(settings, "tracker", "projects", default=[]) or [])
                    if isinstance(p, dict) and p.get("key") not in UNSET]
    sign_off = str(merged.get("sign_off") or "")
    if ON_BEHALF_OF in sign_off:
        behalf = merged.get("on_behalf_of")
        if behalf in UNSET or not str(behalf).strip():
            raise ValueError(f"comment.sign_off for {key} names {ON_BEHALF_OF} but comment.on_behalf_of is not set "
                             f"(extensions.all.comment or extensions.{key}.comment in {source or 'the desk settings'})")
        sign_off = sign_off.replace(ON_BEHALF_OF, str(behalf).strip())
    return Identity(agent=key, name=str(merged.get("name") or key), opener=str(merged.get("opener") or ""),
                    sign_off=sign_off, host=host,
                    card_projects=tuple(str(p) for p in projects),
                    env_file=_env_path(_get(settings, "tracker", "write_env_file")),
                    markup=str(_get(settings, "tracker", "markup", default=CLOUD_MARKUP)), source=source)


# ---------------------------------------------------------------- settings files
def _project_root() -> Path:
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if (p / ".kittify").is_dir():
            return p
    return here


def _files_in(home: Path) -> list[Path]:
    return [p for p in [home / "product-desk.yaml", *sorted(home.glob("*/product-desk.yaml"))] if p.is_file()]


def _yaml():
    try:
        import yaml
    except ImportError:
        raise SystemExit("PyYAML is needed to read product-desk.yaml (pip install pyyaml)")
    return yaml


def _registered_desks(root: Path) -> list[Path]:
    cfg = root / ".kittify" / "config.yaml"
    if not cfg.is_file():
        return []
    try:
        data = _yaml().safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    home = os.environ.get("SPEC_KITTY_PACK_HOME", "")
    out = []
    for pack in _get(data, "doctrine", "org", "packs", default=[]) or []:
        local = isinstance(pack, dict) and pack.get("local_path")
        if not local:
            continue
        p = Path(os.path.expanduser(str(local).replace("${SPEC_KITTY_PACK_HOME}", home)
                                    .replace("$SPEC_KITTY_PACK_HOME", home)))
        p = p if p.is_absolute() else root / p
        out += [f for f in _files_in(p.parent / "product-desk") if f not in out]
    return out


def settings_files() -> list[Path]:
    """Candidate desk settings, first hit wins (toolguide product-desk-settings)."""
    if os.environ.get("PRODUCT_DESK_SETTINGS"):
        return [Path(os.environ["PRODUCT_DESK_SETTINGS"])]
    if os.environ.get("PRODUCT_DESK_HOME"):
        return _files_in(Path(os.environ["PRODUCT_DESK_HOME"]))
    root = _project_root()
    return _files_in(root / "product-desk") or _registered_desks(root)


def load_settings(path: str | None = None, product: str | None = None) -> tuple[dict, str]:
    files = [Path(path)] if path else settings_files()
    if not files:
        raise SystemExit("no product-desk.yaml found; pass --settings <file> or set PRODUCT_DESK_HOME "
                         "(procedure product-desk-onboarding writes one)")
    docs = []
    for f in files:
        if not f.is_file():
            raise SystemExit(f"desk settings not found: {f}")
        docs.append((f, _yaml().safe_load(f.read_text(encoding="utf-8")) or {}))
    if product:
        docs = [(f, d) for f, d in docs if _get(d, "product", "id") == product] or \
            [(f, d) for f, d in docs if _get(d, "product", "short_name") == product]
        if not docs:
            raise SystemExit(f"no desk settings for product {product!r} among {', '.join(map(str, files))}")
    if len(docs) > 1:
        ids = ", ".join(str(_get(d, "product", "id", default=f)) for f, d in docs)
        raise SystemExit(f"several desk settings found ({ids}); pass --product <id> or --settings <file>")
    return docs[0][1], str(docs[0][0])


# ---------------------------------------------------------------- parsing
def read_analysis(path: Path) -> str:
    """The analysis Markdown; a UTF-8 byte-order mark (Notepad, PowerShell 5.1 Out-File) is dropped."""
    return path.read_text(encoding="utf-8-sig")


def split_analysis(md: str, ident: Identity) -> tuple[list[str], str]:
    """Return (summary lines, full-analysis markdown). Opener and sign-off lines are dropped."""
    lines = [ln for ln in md.lstrip("\ufeff").replace("\r\n", "\n").split("\n")
             if not ident.opener_line.match(ln) and not ident.sign_off_line.match(ln)]
    s = next((i for i, ln in enumerate(lines) if SUMMARY_H.match(ln.strip())), None)
    f = next((i for i, ln in enumerate(lines) if FULL_H.match(ln.strip())), None)
    if s is None:
        raise ValueError("no '## Executive summary' section")
    if f is None or f < s:
        raise ValueError("no '## Full analysis' section after the executive summary")
    items: list[str] = []
    for ln in lines[s + 1:f]:
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", ln)
        if m:
            items.append(m.group(1).strip())
        elif ln.strip() and items:
            items[-1] += " " + ln.strip()
        elif ln.strip():
            items.append(ln.strip())
    full = "\n".join(lines[f + 1:]).strip("\n")
    if not items:
        raise ValueError("the executive summary is empty")
    if len(items) > MAX_SUMMARY:
        raise ValueError(f"the executive summary has {len(items)} lines; keep it to {MAX_SUMMARY} at most")
    if not full.strip():
        raise ValueError("the full analysis is empty")
    return items, full


# ---------------------------------------------------------------- inline Markdown -> ADF
INLINE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<link>\[(?P<lt>[^\]]+)\]\((?P<lu>https?://[^)\s]+)\))"
    r"|(?P<bold>\*\*(?P<bt>.+?)\*\*)"
    r"|(?P<em>(?<![\w*])[*_](?P<et>[^*_\s][^*_]*?)[*_](?![\w*]))"
    r"|(?P<url>https?://[^\s)>\]]+)"
)


class Keys:
    """Ticket keys to show as smart links on one Jira host."""

    def __init__(self, projects, host: str):
        self.host = host
        self.re = re.compile(r"\b(?:%s)-\d+\b" % "|".join(map(re.escape, projects))) if projects else None

    def finditer(self, t: str):
        return self.re.finditer(t) if self.re else iter(())


def _text(t: str, marks: list[dict] | None = None) -> dict:
    node = {"type": "text", "text": t}
    if marks:
        node["marks"] = marks
    return node


def _cards(t: str, marks, keys: Keys) -> list[dict]:
    out, pos = [], 0
    for m in keys.finditer(t):
        if m.start() > pos:
            out.append(_text(t[pos:m.start()], marks))
        out.append({"type": "inlineCard", "attrs": {"url": f"https://{keys.host}/browse/{m.group(0)}"}})
        pos = m.end()
    if pos < len(t):
        out.append(_text(t[pos:], marks))
    return out


def inline(t: str, keys: Keys, marks: list[dict] | None = None) -> list[dict]:
    out, pos = [], 0
    for m in INLINE.finditer(t):
        if m.start() > pos:
            out += _cards(t[pos:m.start()], marks, keys)
        if m.group("code"):
            out.append(_text(m.group("code")[1:-1], (marks or []) + [{"type": "code"}]))
        elif m.group("link"):
            out.append(_text(m.group("lt"), (marks or []) + [{"type": "link", "attrs": {"href": m.group("lu")}}]))
        elif m.group("bold"):
            out += inline(m.group("bt"), keys, (marks or []) + [{"type": "strong"}])
        elif m.group("em"):
            out += inline(m.group("et"), keys, (marks or []) + [{"type": "em"}])
        elif m.group("url"):
            u = m.group("url")
            out.append(_text(u, (marks or []) + [{"type": "link", "attrs": {"href": u}}]))
        pos = m.end()
    if pos < len(t):
        out += _cards(t[pos:], marks, keys)
    return out or [_text(" ")]


def _para(nodes: list[dict]) -> dict:
    return {"type": "paragraph", "content": nodes}


# ---------------------------------------------------------------- block Markdown -> ADF
LIST_ITEM = re.compile(r"^(?P<ind>\s*)(?P<mark>[-*+]|\d+[.)])\s+(?P<body>.*)$")


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def _table(rows: list[list[str]], keys) -> dict:
    width = max(len(r) for r in rows)

    def cell(v, header):
        return {"type": "tableHeader" if header else "tableCell", "attrs": {},
                "content": [_para(inline(v or " ", keys, [{"type": "strong"}] if header else None))]}

    content = [{"type": "tableRow", "content": [cell(r[i] if i < len(r) else "", n == 0) for i in range(width)]}
               for n, r in enumerate(rows)]
    return {"type": "table", "attrs": {"isNumberColumnEnabled": False, "layout": "default"}, "content": content}


def _list(items: list[tuple[int, bool, str]], keys) -> dict:
    """items: (indent, ordered, text). Two levels: deeper lines nest under the previous item."""
    base = items[0][0]
    ordered = items[0][1]
    top: list[dict] = []
    child: list[tuple[int, bool, str]] = []

    def flush():
        if child and top:
            top[-1]["content"].append(_list(child, keys))
        child.clear()

    for ind, o, text in items:
        if ind > base and top:
            child.append((ind, o, text))
            continue
        flush()
        top.append({"type": "listItem", "content": [_para(inline(text, keys))]})
    flush()
    node = {"type": "orderedList" if ordered else "bulletList", "content": top}
    if ordered:
        node["attrs"] = {"order": 1}
    return node


def blocks(md: str, keys) -> list[dict]:
    lines = md.split("\n")
    out: list[dict] = []
    i = 0
    para: list[str] = []

    def flush_para():
        if para:
            out.append(_para(inline(" ".join(p.strip() for p in para), keys)))
            para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            flush_para()
            i += 1
            continue
        if s.startswith("```"):
            flush_para()
            lang = s[3:].strip() or "text"
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            out.append({"type": "codeBlock", "attrs": {"language": lang},
                        "content": [_text("\n".join(body) or " ")]})
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", s)
        if h:
            flush_para()
            level = min(6, len(h.group(1)) + 2)
            out.append({"type": "heading", "attrs": {"level": level}, "content": inline(h.group(2), keys)})
            i += 1
            continue
        if s.startswith("|"):
            flush_para()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                r = _cells(lines[i])
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in r if c):
                    rows.append(r)
                i += 1
            if rows:
                out.append(_table(rows, keys))
            continue
        if LIST_ITEM.match(ln):
            flush_para()
            items = []
            while i < len(lines):
                m = LIST_ITEM.match(lines[i])
                if m:
                    items.append((len(m.group("ind").expandtabs(4)), m.group("mark")[0].isdigit(), m.group("body")))
                elif lines[i].strip() and lines[i].startswith(" ") and items:
                    ind, o, t = items[-1]
                    items[-1] = (ind, o, t + " " + lines[i].strip())
                else:
                    break
                i += 1
            out.append(_list(items, keys))
            continue
        if s.startswith(">"):
            flush_para()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append({"type": "panel", "attrs": {"panelType": "note"}, "content": blocks("\n".join(quote), keys)})
            continue
        if re.fullmatch(r"[-*_]{3,}", s):
            flush_para()
            out.append({"type": "rule"})
            i += 1
            continue
        para.append(ln)
        i += 1
    flush_para()
    return out


# ---------------------------------------------------------------- the comment
def build(md: str, ident: Identity, title: str = "Full analysis") -> dict:
    items, full = split_analysis(md, ident)
    keys = Keys(ident.card_projects, ident.host)
    if not title.strip() or "\n" in title:
        raise ValueError("the expand title must be one line of plain text")
    summary = {"type": "bulletList",
               "content": [{"type": "listItem", "content": [_para(inline(x, keys))]} for x in items]}
    body = {"version": 1, "type": "doc", "content": [
        _para([_text(ident.opener)]),
        {"type": "panel", "attrs": {"panelType": "info"},
         "content": [_para([_text("Executive summary", [{"type": "strong"}])]), summary]},
        {"type": "expand", "attrs": {"title": title.strip()}, "content": blocks(full, keys)},
        _para([_text(ident.sign_off, [{"type": "em"}])]),
    ]}
    check(body, ident)
    return body


def adf_text(node) -> str:
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        if node.get("type") == "inlineCard":
            return node.get("attrs", {}).get("url", "").rsplit("/", 1)[-1]
        sep = "\n" if node.get("type") in ("paragraph", "heading", "listItem", "tableRow", "codeBlock") else ""
        return "".join(adf_text(c) for c in node.get("content", [])) + sep
    if isinstance(node, list):
        return "".join(adf_text(c) for c in node)
    return ""


def check(body: dict, ident: Identity) -> None:
    top = body["content"]
    if adf_text(top[0]).strip() != ident.opener or adf_text(top[-1]).strip() != ident.sign_off:
        raise ValueError(f"the comment must open with {ident.name}'s greeting and close with {ident.name}'s sign-off")
    expands = [n for n in top if n["type"] == "expand"]
    if len(expands) != 1:
        raise ValueError("the comment must have exactly one Full analysis section")

    def nested(n):
        return any(c.get("type") in ("expand", "nestedExpand") or nested(c) for c in n.get("content", []))

    if nested(expands[0]):
        raise ValueError("an expand cannot hold another expand")
    if len(adf_text(body)) > MAX_CHARS:
        raise ValueError(f"the comment is longer than {MAX_CHARS} characters; shorten the full analysis")


def preview(body: dict) -> str:
    top = body["content"]
    exp = next(n for n in top if n["type"] == "expand")
    return "\n".join([
        adf_text(top[0]).strip(),
        "[Executive summary]",
        adf_text(top[1]).strip(),
        f"[▸ {exp['attrs']['title']} — collapsed, {len(exp['content'])} blocks]",
        adf_text(top[-1]).strip(),
    ])


# ---------------------------------------------------------------- Jira Cloud (REST v3, stdlib)
def read_env(path: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if path and path.exists():
        for ln in path.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", ln)
            if m:
                out[m.group(1)] = m.group(2).strip('"').strip("'")
    return out


class _Resp:
    def __init__(self, status: int, raw: bytes):
        self.status, self.raw = status, raw

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"Jira answered HTTP {self.status}")

    def json(self):
        return json.loads(self.raw.decode("utf-8") or "{}")


class _Http:
    """Basic-auth JSON calls over urllib. The login stays in this object and is never printed."""

    def __init__(self, email: str, token: str):
        self.__auth = "Basic " + base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")

    def __repr__(self):
        return "<_Http (login hidden)>"

    def _call(self, method: str, url: str, body=None, timeout=60) -> _Resp:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": self.__auth, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _Resp(r.status, r.read())
        except urllib.error.HTTPError as e:
            return _Resp(e.code, e.read())

    def post(self, url, json=None, timeout=60):
        return self._call("POST", url, json, timeout)

    def put(self, url, json=None, timeout=60):
        return self._call("PUT", url, json, timeout)

    def get(self, url, timeout=60):
        return self._call("GET", url, None, timeout)


class Jira:
    def __init__(self, ident: Identity, session=None, base: str | None = None, env_file: Path | None = None):
        if ident.markup not in UNSET and ident.markup != CLOUD_MARKUP:
            raise SystemExit(f"tracker.markup is {ident.markup!r}; this helper writes Jira Cloud comments "
                             f"({CLOUD_MARKUP}, REST v3) only")
        env_path = env_file or ident.env_file
        env = read_env(env_path)
        url = base or os.environ.get("JIRA_API_URL") or env.get("JIRA_API_URL") or f"https://{ident.host}"
        if (urlparse(url).hostname or "").lower() != ident.host.lower():
            raise SystemExit(f"refusing Jira host {urlparse(url).hostname!r}; only {ident.host} "
                             "(tracker.instance in the desk settings) is allowed")
        if "/rest/api/3" not in url:
            url = url.rstrip("/") + "/rest/api/3"
        self.base = url.rstrip("/") + "/"
        if session is None:
            email = os.environ.get("JIRA_API_EMAIL") or env.get("JIRA_API_EMAIL", "")
            token = os.environ.get("JIRA_API_TOKEN") or env.get("JIRA_API_TOKEN", "")
            if not (email and token):
                where = env_path.name if env_path else "the env file named by tracker.write_env_file"
                raise SystemExit(f"Jira Cloud credentials not found (JIRA_API_* in env or {where})")
            session = _Http(email, token)
        self.s = session

    def _ok(self, r):
        r.raise_for_status()
        return r.json()

    def add(self, key: str, body: dict) -> str:
        return self._ok(self.s.post(self.base + f"issue/{key}/comment", json={"body": body}, timeout=60))["id"]

    def update(self, key: str, cid: str, body: dict) -> str:
        return self._ok(self.s.put(self.base + f"issue/{key}/comment/{cid}", json={"body": body}, timeout=60))["id"]

    def read(self, key: str, cid: str) -> dict:
        return self._ok(self.s.get(self.base + f"issue/{key}/comment/{cid}", timeout=60)).get("body") or {}


def post(md: str, key: str, title: str, replace: str | None, apply: bool, ident: Identity,
         jira: Jira | None = None, env_file: Path | None = None) -> dict:
    if not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", key or ""):
        raise SystemExit(f"not a ticket key: {key!r}")
    body = build(md, ident, title)
    print(preview(body))
    if not apply:
        print(f"\n(dry run — nothing written to {key}; add --post to post)")
        return {"applied": False, "body": body}
    jira = jira or Jira(ident, env_file=env_file)
    cid = jira.update(key, replace, body) if replace else jira.add(key, body)
    back = jira.read(key, cid)
    kinds = [n.get("type") for n in back.get("content", [])]
    ok = ("expand" in kinds and "Executive summary" in adf_text(back)
          and ident.sign_off.split(" on behalf")[0] in adf_text(back))
    print(f"\n{'updated' if replace else 'posted'} comment {cid} on {key}; read back: {'OK' if ok else 'MISMATCH'}")
    if not ok:
        raise SystemExit(2)
    return {"applied": True, "id": cid}


# ---------------------------------------------------------------- self-test (synthetic, offline)
TEST_SETTINGS = {
    "product": {"id": "demo", "name": "Demo Product"},
    "tracker": {"instance": "https://demo.atlassian.net", "markup": CLOUD_MARKUP,
                "write_env_file": "demo-mcp/.env.demo-jira",
                "projects": [{"key": "DEMO", "role": "development"}, {"key": "REL", "role": "releases"},
                             {"key": "SUP", "role": "support"}]},
    "extensions": {
        "all": {"comment": {"card_projects": ["DEMO", "REL"], "on_behalf_of": "A. User"}},
        "demo-specialist": {"comment": {
            "name": "Dora", "opener": "Hi, Dora is here.",
            "sign_off": "— This message was drafted and sent by Demo Dora on behalf of {on_behalf_of} · the demo persona."}},
        "clerk-clara": {"comment": {
            "name": "Clara", "opener": "Hello, Clara here.", "sign_off": "Clara, the demo ticket clerk",
            "card_projects": ["SUP"]}},
        "qa-qata": {"tactics": []},
    },
}

SAMPLE = """Hi, Dora is here.

## Executive summary
- **Cause found:** the synthetic row lands in column 0070 (DEMO-1). Proposed: fix the class-name test.
- No customer data needed. Proposed: confirm with a rerun.

## Full analysis
### Evidence
Row 0010, column 0070 — see `ProductClass.isExample` and [the spec](https://example.org/).

| Version | Column 0070 |
|---|---|
| V1 | 490 |
| V2 | — |

1. First step
   - nested detail
2. Second step

```sql
SELECT 1
```

> Note: the baseline expects the wrong value.

— This message was drafted and sent by Demo Dora on behalf of A. User · the demo persona.
"""


class _FakeResp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class _FakeSession:
    def __init__(self):
        self.calls = []
        self.store = {}

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url))
        self.store["1"] = json["body"]
        return _FakeResp({"id": "1"})

    def put(self, url, json=None, timeout=None):
        self.calls.append(("PUT", url))
        self.store[url.rsplit("/", 1)[-1]] = json["body"]
        return _FakeResp({"id": url.rsplit("/", 1)[-1]})

    def get(self, url, timeout=None):
        self.calls.append(("GET", url))
        return _FakeResp({"body": self.store[url.rsplit("/", 1)[-1]]})


def selftest() -> int:
    import contextlib
    import copy
    import io

    fails = []

    def ok(cond, msg):
        if not cond:
            fails.append(msg)

    dora = identity_from(TEST_SETTINGS, "demo-specialist", "selftest")
    body = build(SAMPLE, dora)
    top = body["content"]
    ok([n["type"] for n in top] == ["paragraph", "panel", "expand", "paragraph"], f"layout {[n['type'] for n in top]}")
    ok(adf_text(top[0]).strip() == dora.opener, "opener")
    ok(adf_text(top[-1]).strip() == dora.sign_off, "sign-off")
    ok(dora.sign_off == "— This message was drafted and sent by Demo Dora on behalf of A. User · the demo persona.",
       f"on_behalf_of not filled in: {dora.sign_off!r}")
    ok(adf_text(body).count("Dora is here") == 1, "opener duplicated")
    ok(adf_text(body).count("drafted and sent") == 1, "sign-off duplicated")
    summ = top[1]["content"][1]["content"]
    ok(len(summ) == 2, "two summary lines")
    cards = [n for n in summ[0]["content"][0]["content"] if n.get("type") == "inlineCard"]
    ok(cards and cards[0]["attrs"]["url"] == "https://demo.atlassian.net/browse/DEMO-1", "ticket key as smart link")
    exp_types = [n["type"] for n in top[2]["content"]]
    for t in ("heading", "paragraph", "table", "orderedList", "codeBlock", "panel"):
        ok(t in exp_types, f"full analysis lacks {t}")
    ol = next(n for n in top[2]["content"] if n["type"] == "orderedList")
    ok(ol["content"][0]["content"][-1]["type"] == "bulletList", "nested list")
    ok(top[2]["attrs"]["title"] == "Full analysis", "expand title")
    ok("Executive summary" not in adf_text(top[2]), "summary leaked into the full analysis")
    ok("ISO-8601" in adf_text(build(SAMPLE.replace("Second step", "ISO-8601 dates"), dora)), "non-ticket token kept as text")
    sup = build(SAMPLE.replace("Second step", "see SUP-9"), dora)
    ok("SUP-9" in adf_text(sup) and "browse/SUP-9" not in json.dumps(sup), "a key outside card_projects became a card")
    variant = SAMPLE.replace("Hi, Dora is here.", "Hello Dora is here!").replace(
        "— This message was drafted and sent by Demo Dora", "- This message was drafted by Dora")
    ok(adf_text(build(variant, dora)).count("Dora is here") == 1, "typed opener/sign-off variants not dropped")
    for bom_md, why in (("\ufeff" + SAMPLE, "opener first"),
                        ("\ufeff" + SAMPLE[SAMPLE.index("## Executive summary"):], "summary heading first")):
        try:
            bb = build(bom_md, dora)
            ok(adf_text(bb).count("Dora is here") == 1 and "\ufeff" not in json.dumps(bb),
               f"BOM-prefixed analysis ({why}) left the BOM or a second opener in the body")
        except ValueError as e:
            fails.append(f"BOM-prefixed analysis ({why}) refused: {e}")
    import tempfile
    with tempfile.TemporaryDirectory(prefix="desk-comment-bom-") as tmp:
        bom_file = Path(tmp) / "analysis.md"
        bom_file.write_bytes(b"\xef\xbb\xbf" + SAMPLE.encode("utf-8"))
        text = read_analysis(bom_file)
        ok(not text.startswith("\ufeff") and text == SAMPLE, "read_analysis kept the UTF-8 BOM")

    # a second agent: its own words, its own card projects, nothing of the first
    clara = identity_from(TEST_SETTINGS, "Clara", "selftest")
    ok(clara.agent == "clerk-clara" and clara.card_projects == ("SUP",), "agent by name, own card_projects")
    cb = build(SAMPLE.replace("Hi, Dora is here.", "Hello, Clara here.").replace("DEMO-1", "SUP-2"), clara)
    ok(adf_text(cb["content"][0]).strip() == "Hello, Clara here." and
       adf_text(cb["content"][-1]).strip() == "Clara, the demo ticket clerk", "second agent identity")
    ok(adf_text(cb).count("Clara here") == 1, "second agent opener duplicated")
    ok(any(n.get("type") == "inlineCard" for n in cb["content"][1]["content"][1]["content"][0]["content"][0]["content"]),
       "second agent card")
    ok(opener_pattern("Hi, Dora is here.").match("hey there, DORA is here!!") is not None, "opener pattern")
    ok(opener_pattern("Hi, Dora is here.").match("Dora is here") is None, "opener pattern needs a greeting")
    ok(sign_off_pattern("— This message was drafted and sent by Demo Dora on behalf of X", "Dora")
       .match("-- this message was drafted by dora") is not None, "sign-off pattern keeps the name")

    # settings errors
    s = copy.deepcopy(TEST_SETTINGS)
    del s["tracker"]["projects"]
    s["extensions"]["all"] = {"comment": {"on_behalf_of": "A. User"}}
    ok(identity_from(s, "demo-specialist").card_projects == (), "no projects -> no cards")
    s2 = copy.deepcopy(TEST_SETTINGS)
    s2["extensions"]["all"] = {"comment": {"on_behalf_of": "A. User"}}
    ok(identity_from(s2, "demo-specialist").card_projects == ("DEMO", "REL", "SUP"), "default card_projects")
    s3 = copy.deepcopy(TEST_SETTINGS)
    s3["extensions"]["demo-specialist"]["comment"]["on_behalf_of"] = "B. Colleague"
    ok("on behalf of B. Colleague ·" in identity_from(s3, "demo-specialist").sign_off, "agent on_behalf_of overrides all")
    ok(identity_from(TEST_SETTINGS, "clerk-clara").sign_off == "Clara, the demo ticket clerk",
       "a sign-off without the placeholder is kept as written")
    for why, mutate in [
        ("placeholder without on_behalf_of",
         lambda d: d["extensions"]["all"]["comment"].pop("on_behalf_of")),
        ("placeholder with TBD on_behalf_of",
         lambda d: d["extensions"]["all"]["comment"].__setitem__("on_behalf_of", "TBD")),
        ("two-line on_behalf_of",
         lambda d: d["extensions"]["all"]["comment"].__setitem__("on_behalf_of", "A.\nUser")),
        ("agent without comment", lambda d: d["extensions"].__setitem__("demo-specialist", {})),
        ("TBD opener", lambda d: d["extensions"]["demo-specialist"]["comment"].__setitem__("opener", "TBD")),
        ("two-line sign-off", lambda d: d["extensions"]["demo-specialist"]["comment"].__setitem__("sign_off", "a\nb")),
        ("TBD tracker host", lambda d: d["tracker"].__setitem__("instance", "TBD")),
    ]:
        bad = copy.deepcopy(TEST_SETTINGS)
        mutate(bad)
        try:
            identity_from(bad, "demo-specialist")
            fails.append(f"accepted {why}")
        except ValueError:
            pass

    for bad, why in [
        (SAMPLE.replace("## Executive summary", "## Summary"), "missing summary"),
        (SAMPLE.replace("## Full analysis", "## Details"), "missing full analysis"),
        (SAMPLE.replace("- No customer", "- a\n- b\n- c\n- d\n- No customer"), "six summary lines"),
        ("## Executive summary\n- x\n## Full analysis\n\n", "empty full analysis"),
        ("## Full analysis\nx\n## Executive summary\n- y\n", "wrong order"),
    ]:
        try:
            build(bad, dora)
            fails.append(f"accepted {why}")
        except ValueError:
            pass
    try:
        build(SAMPLE, dora, title="two\nlines")
        fails.append("accepted a two-line title")
    except ValueError:
        pass
    try:
        build(SAMPLE.replace("Second step", "x" * (MAX_CHARS + 10)), dora)
        fails.append("accepted an oversized comment")
    except ValueError:
        pass

    fake = _FakeSession()
    j = Jira(dora, session=fake, base="https://demo.atlassian.net/rest/api/3")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        r = post(SAMPLE, "DEMO-1", "Full analysis", None, apply=False, ident=dora, jira=j)
        ok(not r["applied"] and not fake.calls, "dry run wrote")
        ok("add --post to post" in out.getvalue(), "dry-run hint names --post")
        r = post(SAMPLE, "DEMO-1", "Full analysis", None, apply=True, ident=dora, jira=j)
        ok(r["applied"] and fake.calls[0][0] == "POST" and fake.calls[-1][0] == "GET", "post + read back")
        fake.calls.clear()
        post(SAMPLE, "DEMO-1", "Full analysis", "77", apply=True, ident=dora, jira=j)
    ok(fake.calls[0] == ("PUT", "https://demo.atlassian.net/rest/api/3/issue/DEMO-1/comment/77"), "replace uses PUT")
    for base in ("https://jira.example.net/rest/api/2", "https://evil.example.com/?demo.atlassian.net",
                 "https://demo.atlassian.net.evil.example.com/rest/api/3"):
        try:
            Jira(dora, session=_FakeSession(), base=base)
            fails.append(f"accepted host {base}")
        except SystemExit:
            pass
    dc = copy.deepcopy(TEST_SETTINGS)
    dc["tracker"]["markup"] = "dc-wiki"
    try:
        Jira(identity_from(dc, "demo-specialist"), session=_FakeSession(), base="https://demo.atlassian.net")
        fails.append("accepted a dc-wiki tracker")
    except SystemExit:
        pass
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            post(SAMPLE, "not a key", "Full analysis", None, apply=False, ident=dora, jira=j)
        fails.append("accepted a bad key")
    except SystemExit:
        pass
    ok("hidden" in repr(_Http("someone@example.org", "s3cr3t-value")) and
       "s3cr3t" not in repr(_Http("someone@example.org", "s3cr3t-value")), "login visible in repr")
    p = _parser()
    ok(p.parse_args(["post", "--agent", "x", "--in", "f", "--key", "K-1", "--apply"]).post, "--apply alias")
    ok(not p.parse_args(["post", "--agent", "x", "--in", "f", "--key", "K-1"]).post, "post is a dry run by default")

    print("desk_comment selftest:", "PASS" if not fails else "FAILED")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


# ---------------------------------------------------------------- CLI
def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("render", "post", "identity"):
        p = sub.add_parser(name)
        p.add_argument("--settings", help="product-desk.yaml; default: found as in toolguide product-desk-settings")
        p.add_argument("--product", help="product id, when several desk settings are found")
        p.add_argument("--agent", default=os.environ.get("PRODUCT_DESK_AGENT"),
                       help="profile id (or comment.name) of the agent speaking; default PRODUCT_DESK_AGENT")
        if name == "identity":
            continue
        p.add_argument("--in", dest="src", required=True, help="the analysis Markdown file")
        p.add_argument("--title", default="Full analysis", help="title of the collapsed section (plain text)")
        if name == "render":
            p.add_argument("--out", help="write the ADF body here")
        else:
            p.add_argument("--key", required=True)
            p.add_argument("--replace", help="edit this existing comment id instead of adding one")
            p.add_argument("--post", "--apply", dest="post", action="store_true",
                           help="write to Jira; without it this is a dry run")
            p.add_argument("--env-file", help="env file with JIRA_API_*; default tracker.write_env_file")
    sub.add_parser("selftest")
    return ap


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    a = _parser().parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    if not a.agent:
        print("refused: name the agent speaking with --agent <profile id> (or set PRODUCT_DESK_AGENT)", file=sys.stderr)
        return 2
    settings, source = load_settings(a.settings, a.product)
    try:
        ident = identity_from(settings, a.agent, source)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if a.cmd == "identity":
        print(json.dumps({"settings": source, "agent": ident.agent, "name": ident.name, "opener": ident.opener,
                          "sign_off": ident.sign_off, "host": ident.host, "card_projects": list(ident.card_projects),
                          "env_file": str(ident.env_file) if ident.env_file else None, "markup": ident.markup},
                         indent=2, ensure_ascii=False))
        return 0
    md = read_analysis(Path(a.src))
    try:
        if a.cmd == "render":
            body = build(md, ident, a.title)
            print(preview(body))
            if a.out:
                Path(a.out).write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
            return 0
        post(md, a.key, a.title, a.replace, a.post, ident, env_file=Path(a.env_file) if a.env_file else None)
        return 0
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
