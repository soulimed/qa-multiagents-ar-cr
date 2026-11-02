#!/usr/bin/env python3
"""Release-note file export and per-customer variant. Dry run by default.

  rn_export.py export  --md <notes>.md --format md|html|pdf|docx [--out DIR] [--apply]
  rn_export.py variant --md <notes>.md --customer "<customer>" [--apply]
  rn_export.py page-check --page <id> --version 1.2.0   # before any wiki --apply
  rn_export.py selftest

Everything team-specific comes from the team's desk settings (capability rela.release_notes):
the PDF subtitle and footer, the customer map, the support project, the organization field,
the wiki host and its login file.

export
  html / pdf : the branded pipeline in this skill's tools/ folder (make-pdf.ps1 -> md-to-branded-html.mjs).
  docx       : a Word document with the same headings, bold labels and bullets (python-docx).
  md         : a copy.
  Without --apply it prints what it would write and writes nothing.

variant
  Keeps only the notes whose ticket is linked to a support case of that customer.
  The link is read from the tracker (issue links -> support case -> its organization field,
  tracker.fields.organizations) and mapped to board clients through the file in
  release_notes.customer_variant.client_map.
  The notes themselves are unchanged: customer names stay out of the text;
  the customer is only in the file name. The internal/excluded section is dropped.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "product-desk-tickets" / "scripts"))
import _desk  # noqa: E402  (takes --settings / --product off the command line)

RN_TOOLS = HERE.parent / "tools"
KEY = re.compile(r"^###\s+([A-Z][A-Z0-9]+-\d+)\s*$")
DOC: dict | None = None
SOURCE = ""


def rn(*path, default=None):
    return _desk.get(DOC, "desk", "rela", "release_notes", *path, default=default)


# ---------------------------------------------------------------- markdown model
def sections(md: str) -> tuple[list[str], list[tuple[str, list[tuple[str, list[str]]], list[str]]]]:
    """(preamble lines, [(module heading, [(ticket key, block lines)], module lines without a ticket)])."""
    pre, mods = [], []
    cur = None
    for ln in md.splitlines():
        if ln.startswith("## "):
            cur = (ln, [], [])
            mods.append(cur)
        elif cur is None:
            pre.append(ln)
        elif KEY.match(ln):
            cur[1].append((KEY.match(ln).group(1), [ln]))
        elif cur[1]:
            cur[1][-1][1].append(ln)
        else:
            cur[2].append(ln)
    return pre, mods


def filter_md(md: str, keep: set[str]) -> tuple[str, list[str]]:
    pre, mods = sections(md)
    out, kept = list(pre), []
    for head, blocks, loose in mods:
        if "internal" in head.lower() or "excluded" in head.lower():
            continue
        chosen = [(k, b) for k, b in blocks if k in keep]
        if not chosen:
            continue
        out += [head, *[x for x in loose if x.strip() and x.strip() != "---"], ""]
        for k, b in chosen:
            kept.append(k)
            body = list(b)
            while body and body[-1].strip() in ("", "---"):
                body.pop()
            out += body + [""]
        out += ["---", ""]
    return "\n".join(out).rstrip("-\n ") + "\n", kept


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")


# ---------------------------------------------------------------- customer mapping
def _dotted(d, path: str):
    for p in str(path).split("."):
        d = d.get(p) if isinstance(d, dict) else None
    return d


def org_to_client() -> dict[str, str]:
    import yaml
    cfg_file = _desk.expand(rn("customer_variant", "client_map"))
    if cfg_file is None:
        raise SystemExit("release_notes.customer_variant.client_map is not set in the desk settings; "
                         "ask Olga to finish onboarding section rela-release-notes")
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    out = {}
    for i, lst in enumerate(rn("customer_variant", "client_lists", default=["clients"])):
        for c in _dotted(cfg, lst) or []:
            for org in c.get("organizations") or []:
                if i == 0:
                    out[org.strip().lower()] = c["name"]
                else:
                    out.setdefault(org.strip().lower(), c["name"])
    return out


def customers_for(keys: list[str]) -> dict[str, set[str]]:
    org_field = _desk.get(DOC, "tracker", "fields", "organizations")
    support = tuple(f"{k}-" for k in _desk.project_keys(DOC, ("support",)))
    if not org_field or not support:
        raise SystemExit("tracker.fields.organizations and a tracker project with role support are needed "
                         "for a customer variant; ask Olga to finish onboarding section rela-release-notes")
    jira, mapping, out = _desk.Tracker(DOC), org_to_client(), {}
    for k in keys:
        links = (jira.get(f"issue/{k}", fields="issuelinks").get("fields") or {}).get("issuelinks") or []
        sups = {(l.get("outwardIssue") or l.get("inwardIssue") or {}).get("key") for l in links}
        names = set()
        for s in sorted(x for x in sups if x and x.startswith(support)):
            orgs = (jira.get(f"issue/{s}", fields=org_field).get("fields") or {}).get(org_field) or []
            for o in orgs:
                n = (o.get("name") if isinstance(o, dict) else str(o)).strip()
                names.add(mapping.get(n.lower(), n))
        out[k] = names
    return out


# ---------------------------------------------------------------- docx
def inline(par, text: str) -> None:
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if part.startswith("**") and part.endswith("**"):
            par.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`"):
            r = par.add_run(part[1:-1])
            r.font.name = "Consolas"
        elif part:
            par.add_run(part)


def to_docx(md: str, out: Path) -> None:
    from docx import Document
    doc = Document()
    for ln in md.splitlines():
        s = ln.rstrip()
        if not s or s == "---":
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            doc.add_heading(m.group(2), level=len(m.group(1)) - 1 if len(m.group(1)) > 1 else 0)
        elif re.match(r"^\s*[-*]\s+", s):
            inline(doc.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*]\s+", "", s))
        else:
            inline(doc.add_paragraph(), s)
    doc.save(str(out))


def title_of(md: str) -> str:
    return next((l[2:].strip() for l in md.splitlines() if l.startswith("# ")), "Release notes")


# ---------------------------------------------------------------- commands
def cmd_export(a) -> int:
    src = Path(a.md)
    md = src.read_text(encoding="utf-8")
    out_dir = Path(a.out) if a.out else src.parent
    target = out_dir / (src.stem + {"md": ".md", "html": ".html", "pdf": ".pdf", "docx": ".docx"}[a.format])
    if a.format == "md" and target.resolve() == src.resolve():
        print(f"{src.name} is already the Markdown export")
        return 0
    print(f"{'WRITE' if a.apply else 'DRY RUN'}: {a.format} -> {target}")
    if not a.apply:
        print("  nothing written; add --apply after review")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.format == "md":
        shutil.copyfile(src, target)
    elif a.format == "docx":
        to_docx(md, target)
    else:
        cmd = ["powershell", "-NoProfile", "-File", str(RN_TOOLS / "make-pdf.ps1"), "-Md", str(src),
               "-Title", title_of(md).split(" - ")[0], "-Subtitle", str(rn("pdf_subtitle", default="Release notes"))]
        if rn("pdf_footer"):
            cmd += ["-Footer", str(rn("pdf_footer"))]
        subprocess.run(cmd, check=True)
        made = src.with_suffix("." + a.format)
        if made.resolve() != target.resolve():
            shutil.copyfile(made, target)
    print(f"  wrote {target}")
    return 0


def cmd_variant(a) -> int:
    src = Path(a.md)
    md = src.read_text(encoding="utf-8")
    keys = [k for _, blocks, _ in sections(md)[1] for k, _ in blocks]
    cust = customers_for(sorted(set(keys)))
    want = a.customer.lower()
    keep = {k for k, names in cust.items() if any(want in n.lower() for n in names)}
    text, kept = filter_md(md, keep)
    target = src.with_name(f"{src.stem}-{slug(a.customer)}.md")
    print(f"{len(kept)} of {len(set(keys))} note(s) are linked to a support case of '{a.customer}':")
    for k in sorted(set(keys)):
        print(f"  {'keep' if k in keep else '    '} {k}: {', '.join(sorted(cust.get(k) or [])) or 'no customer support case'}")
    print(f"{'WRITE' if a.apply else 'DRY RUN'}: {target}")
    if a.apply and kept:
        target.write_text(text, encoding="utf-8")
        print(f"  wrote {target} (local; the file name carries the customer, the text does not)")
    elif not kept:
        print("  no note for this customer; nothing to write")
    else:
        print("  nothing written; add --apply after review")
    return 0


def title_matches(title: str, version: str) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(version)}(?![\d.])", title or "") is not None


def page_title(doc: dict | None, version: str) -> str | None:
    """The team's page title for a version: release_notes.wiki.page_title, else release_notes.title."""
    rnb = _desk.get(doc, "desk", "rela", "release_notes", default={}) or {}
    pattern = _desk.get(rnb, "wiki", "page_title") or _desk.get(rnb, "title")
    return str(pattern).replace("{v}", version) if pattern else None


def skeleton(doc: dict | None, version: str) -> str:
    """The head of a notes file in the team's format: page title, section heading, intro; entries follow.

    The H1 is the page title (the wiki converter drops it, the page carries it); the section heading is a
    bold line, because a `## ` heading opens a module group.
    """
    rnb = _desk.get(doc, "desk", "rela", "release_notes", default={}) or {}
    title, heading = page_title(doc, version), _desk.get(rnb, "section_heading")
    missing = [k for k, v in (("release_notes.title", title), ("release_notes.section_heading", heading)) if not v]
    if missing:
        raise KeyError(", ".join(missing))
    intro = _desk.get(rnb, "intro")
    return f"# {title}\n\n**{heading}**\n\n" + (f"{intro}\n\n" if intro else "")


def wiki_env_file(doc: dict | None) -> Path | None:
    """The wiki login file named in credentials.wiki (REGNOLOGY_MCP_HOME, when set, holds it)."""
    value = _desk.get(doc, "credentials", "wiki")
    if value is None:
        return None
    rel = str(value).split(" (")[0].strip()
    if os.environ.get("REGNOLOGY_MCP_HOME"):
        return Path(os.environ["REGNOLOGY_MCP_HOME"]) / Path(rel).name
    return _desk.expand(rel)


def cmd_page_check(a) -> int:
    """Refuse a wiki push when the target page is titled for another version."""
    base = _desk.get(DOC, "wiki", "instance")
    f = wiki_env_file(DOC)
    if not base or f is None:
        print("wiki.instance and credentials.wiki are not set in the desk settings; "
              "ask Olga to finish onboarding section rela-release-notes", file=sys.stderr)
        return _desk.NOT_SET_UP
    env = _desk.read_env_file(f)
    user, token = env.get("CONFLUENCE_CLOUD_EMAIL"), env.get("CONFLUENCE_CLOUD_API_TOKEN")
    if not (user and token):
        print(f"wiki credentials not found (CONFLUENCE_CLOUD_EMAIL / CONFLUENCE_CLOUD_API_TOKEN in {f.name})",
              file=sys.stderr)
        return 1
    import requests
    r = requests.get(f"{str(base).rstrip('/')}/rest/api/content/{a.page}",
                     params={"expand": "version,space"}, timeout=60, auth=(user, token))
    r.raise_for_status()
    page = r.json()
    title = page.get("title") or ""
    ok = title_matches(title, a.version)
    print(f"page {a.page} '{title}' (space {page['space']['key']}, version {page['version']['number']})")
    print(f"  {'OK' if ok else 'STOP'}: title {'names' if ok else 'does not name'} {a.version}")
    expected = page_title(DOC, a.version)
    if ok and expected and title != expected:
        print(f"  note: the team's title for {a.version} is '{expected}'; the push keeps the page's title "
              "unless it is run with --title auto")
    if not ok:
        print("  Do not push this body to this page. Confirm the right page id with the user.")
    return 0 if ok else 4


def selftest() -> int:
    md = ("# T - Release notes\n\nIntro.\n\n---\n\n## Alpha\n\n### DEV-1\n\n**A**\n\n**Problem**\nx\n\n"
          "### DEV-2\n\n**B**\n\n---\n\n## Beta\n\n### DEV-3\n\n**C**\n\n---\n\n"
          "## Internal / excluded from customer notes\n\n- DEV-9 test only\n")
    text, kept = filter_md(md, {"DEV-2"})
    fails = []
    if kept != ["DEV-2"] or "DEV-1" in text or "Beta" in text or "DEV-9" in text or "## Alpha" not in text:
        fails.append(f"filter:\n{text}")
    if "Intro." not in text:
        fails.append("preamble kept")
    try:
        import tempfile
        from docx import Document
        p = Path(tempfile.gettempdir()) / "rn_export_selftest.docx"
        to_docx(md, p)
        paras = [x.text for x in Document(str(p)).paragraphs]
        if "DEV-1" not in paras or not any(x == "Problem" for x in paras):
            fails.append(f"docx paragraphs {paras[:8]}")
        p.unlink()
    except ImportError:
        fails.append("python-docx missing")
    if not title_matches("Demo Product 1.2.0 - Release notes", "1.2.0") \
            or title_matches("Demo Product 1.3.0 - Release notes", "1.2.0") \
            or title_matches("Demo 1.2.01", "1.2.0"):
        fails.append("page title guard")
    demo = {"desk": {"rela": {"release_notes": {"title": "Demo {v} - Notes", "section_heading": "Changes",
                                                "intro": "Solved here.", "wiki": {"page_title": "Demo Page {v}"}}}}}
    if page_title(demo, "1.2.0") != "Demo Page 1.2.0" \
            or skeleton(demo, "1.2.0") != "# Demo Page 1.2.0\n\n**Changes**\n\nSolved here.\n\n":
        fails.append(f"page title and skeleton from settings: {skeleton(demo, '1.2.0')!r}")
    demo["desk"]["rela"]["release_notes"]["wiki"]["page_title"] = "TBD"
    if page_title(demo, "1.2.0") != "Demo 1.2.0 - Notes":
        fails.append("page title falls back to release_notes.title")
    try:
        skeleton({"desk": {"rela": {"release_notes": {"title": "x"}}}}, "1")
        fails.append("skeleton without a section heading must stop")
    except KeyError:
        pass
    cfg = {"clients": [{"name": "Acme", "organizations": ["ACME Org"]}],
           "side": {"clients": [{"name": "Other", "organizations": ["acme org", "Side Org"]}]}}
    if [c["name"] for c in _dotted(cfg, "side.clients")] != ["Other"] or _dotted(cfg, "none.x") is not None:
        fails.append("dotted client list lookup")
    for f in fails:
        print("FAIL", f)
    print("selftest OK: variant filter, docx render, page title guard" if not fails else "selftest FAILED")
    return 1 if fails else 0


def main(argv=None) -> int:
    global DOC, SOURCE
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("export")
    p.add_argument("--md", required=True)
    p.add_argument("--format", required=True, choices=["md", "html", "pdf", "docx"])
    p.add_argument("--out")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("variant")
    p.add_argument("--md", required=True)
    p.add_argument("--customer", required=True)
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("page-check")
    p.add_argument("--page", required=True)
    p.add_argument("--version", required=True)
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    DOC, SOURCE = _desk.load()
    _desk.gate("rela", "release_notes", DOC, SOURCE)
    return {"export": cmd_export, "variant": cmd_variant, "page-check": cmd_page_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
