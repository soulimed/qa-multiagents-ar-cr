#!/usr/bin/env python3
"""Run this skill's tools with the team's values filled in from its desk settings.

  rn_tools.py fields pull --version 1.2.0 [--with-commits] [--all-statuses] [--out-dir DIR]
  rn_tools.py fields push --version 1.2.0 [--input <tag>-1.2.0-rn.json] [--apply] [--overwrite]
  rn_tools.py wiki --page <id> --body <stem>.confluence.xml --version 1.2.0 [--title auto] [--apply] [--skip-labels]
  rn_tools.py skeleton --version 1.2.0          # head of the notes file: page title, section heading, intro
  rn_tools.py pdf --md <notes>.md [--title "<title>"]
  rn_tools.py confluence --md <notes>.md        # -> <stem>.confluence.xml (REST storage body)
  rn_tools.py paste --md <notes>.md             # -> <stem>-PASTE.html (manual paste copy)
  rn_tools.py selftest                          # builds every command line from synthetic settings
  add --show to print the tool's command line and run nothing.

fields  tools/rn-fields.ps1: the tracker host (tracker.instance; any other host and every
        tracker.read_only_archives entry is refused), the development project, the fix-version
        prefix, the release-notes and exclude field ids, the exclude option, the done statuses,
        and the login file credentials.jira_release_notes. push is a dry run without --apply.
wiki    runs `rn_export.py page-check` first and stops when the page title names another
        version, then tools/wiki-push.ps1 with wiki.instance, credentials.wiki and the labels in
        release_notes.wiki.labels. A dry run without --apply. The page keeps its title unless
        --title is given; --title auto uses release_notes.wiki.page_title (else release_notes.title).
skeleton  release_notes.wiki.page_title (else title) with {v} filled, section_heading, intro.

Capability rela.release_notes must be on; a missing setting is named, never guessed.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "product-desk-tickets" / "scripts"))
sys.path.insert(0, str(HERE))
import _desk  # noqa: E402  (takes --settings / --product off the command line)

TOOLS = HERE.parent / "tools"


class NotSetUp(Exception):
    pass


def need(value, key: str):
    if value in _desk.UNSET:
        raise NotSetUp(key)
    return value


def login_file(doc: dict | None, key: str) -> Path:
    """The login file named in credentials.<key>; REGNOLOGY_MCP_HOME, when set, holds it."""
    rel = str(need(_desk.get(doc, "credentials", key), f"credentials.{key}")).split(" (")[0].strip()
    if os.environ.get("REGNOLOGY_MCP_HOME"):
        return Path(os.environ["REGNOLOGY_MCP_HOME"]) / Path(rel).name
    p = _desk.expand(rel)
    if p is None:
        raise NotSetUp(f"credentials.{key}")
    return p


def product_tag(doc: dict | None) -> str:
    rn = _desk.get(doc, "desk", "rela", "release_notes", default={}) or {}
    tag = rn.get("product_tag")
    if tag in _desk.UNSET:
        out = str(rn.get("output_file") or "")
        tag = out.split("-{v}", 1)[0] if "-{v}" in out else None
    return str(need(tag, "desk.rela.release_notes.product_tag (or output_file with -{v})"))


def ps(script: str, *args: str) -> list[str]:
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TOOLS / script), *args]


def fields_cmd(doc: dict | None, a) -> list[str]:
    site = str(need(_desk.get(doc, "tracker", "instance"), "tracker.instance"))
    projects = _desk.project_keys(doc, ("development",))
    rnf = _desk.get(doc, "desk", "rela", "release_notes", default={}) or {}
    done = need(rnf.get("done_statuses"), "desk.rela.release_notes.done_statuses")
    cmd = ps("rn-fields.ps1", "-Command", a.action, "-Version", a.version,
             "-EnvFile", str(login_file(doc, "jira_release_notes")),
             "-SiteUrl", a.site or site, "-AllowedSite", site,
             "-Project", need(projects[0] if projects else None, "tracker.projects (role development)"),
             "-FixVersionPrefix", need(_desk.fix_version_prefix(doc), "tracker.fix_version_pattern"),
             "-ProductTag", product_tag(doc),
             "-RnField", str(need(_desk.get(doc, "tracker", "fields", "release_notes"), "tracker.fields.release_notes")),
             "-ExcludeField", str(need(_desk.get(doc, "tracker", "fields", "exclude_from_release_notes"),
                                       "tracker.fields.exclude_from_release_notes")),
             "-ExcludeValue", str(need(rnf.get("exclude_value"), "desk.rela.release_notes.exclude_value")),
             "-DoneStatuses", ",".join(str(s) for s in done))
    archives = [urlparse(str(u)).hostname or str(u) for u in _desk.get(doc, "tracker", "read_only_archives", default=[]) or []]
    if archives:
        cmd += ["-RefuseHosts", ",".join(archives)]
    for flag, on in (("-WithCommits", a.with_commits), ("-AllStatuses", a.all_statuses),
                     ("-Apply", a.apply), ("-Overwrite", a.overwrite)):
        if on:
            cmd.append(flag)
    if a.out_dir:
        cmd += ["-OutDir", a.out_dir]
    if a.input:
        cmd += ["-InputJson", a.input]
    return cmd


def wiki_cmd(doc: dict | None, a) -> list[str]:
    base = str(need(_desk.get(doc, "wiki", "instance"), "wiki.instance"))
    cmd = ps("wiki-push.ps1", "-PageId", a.page, "-BodyFile", a.body,
             "-EnvFile", str(login_file(doc, "wiki")), "-BaseUrl", base)
    labels = _desk.get(doc, "desk", "rela", "release_notes", "wiki", "labels", default=[]) or []
    if a.skip_labels:
        cmd.append("-SkipLabels")
    elif labels:
        cmd += ["-Labels", ",".join(str(x) for x in labels)]
    title = a.title
    if title == "auto":
        import rn_export
        title = need(rn_export.page_title(doc, a.version), "release_notes.wiki.page_title")
    for flag, val in (("-Title", title), ("-Message", a.message)):
        if val:
            cmd += [flag, val]
    if a.apply:
        cmd.append("-Apply")
    return cmd


def pdf_cmd(doc: dict | None, a) -> list[str]:
    import rn_export
    md = Path(a.md).read_text(encoding="utf-8")
    rn = _desk.get(doc, "desk", "rela", "release_notes", default={}) or {}
    cmd = ps("make-pdf.ps1", "-Md", a.md, "-Title", a.title or rn_export.title_of(md).split(" - ")[0],
             "-Subtitle", str(rn.get("pdf_subtitle") or "Release notes"))
    if rn.get("pdf_footer"):
        cmd += ["-Footer", str(rn["pdf_footer"])]
    return cmd


def node_cmd(script: str, suffix: str, a) -> list[str]:
    src = Path(a.md)
    out = a.out or str(src.with_name(src.stem + suffix))
    return ["node", str(TOOLS / script), str(src), out]


def run(cmd: list[str], show: bool) -> int:
    if show:
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        return 0
    return subprocess.run(cmd).returncode


def selftest() -> int:
    """Every command line built from synthetic settings, and a missing setting named; no tool runs."""
    import copy
    import tempfile
    fails: list[str] = []
    demo = {"tracker": {"instance": "https://tracker.example.com",
                        "read_only_archives": ["https://archive.example.org/jira"],
                        "projects": [{"key": "SUP", "role": "support"}, {"key": "DEMO", "role": "development"}],
                        "fix_version_pattern": "Demo Product {v}",
                        "fields": {"release_notes": "rn-field", "exclude_from_release_notes": "exclude-field"}},
            "wiki": {"instance": "https://wiki.example.com/wiki"},
            "credentials": {"jira_release_notes": "~/demo/.env.tracker (read and write)", "wiki": "~/demo/.env.wiki"},
            "desk": {"rela": {"release_notes": {
                "output_file": "demo-{v}-rn.md", "done_statuses": ["Done", "Closed"], "exclude_value": "Yes",
                "title": "Demo {v} - Notes", "wiki": {"page_title": "Demo Page {v}", "labels": ["doc-rn", "demo"]}}}}}

    def fields(**kw):
        a = dict(action="pull", version="1.2.0", site=None, with_commits=False, all_statuses=False, apply=False,
                 overwrite=False, out_dir=None, input=None)
        a.update(kw)
        return argparse.Namespace(**a)

    def wiki(**kw):
        a = dict(page="42", body="notes.confluence.xml", version="1.2.0", title=None, message=None,
                 skip_labels=False, apply=False)
        a.update(kw)
        return argparse.Namespace(**a)

    def val(cmd: list[str], flag: str):
        return cmd[cmd.index(flag) + 1] if flag in cmd else None

    def stops(name: str, key: str, edit, build) -> None:
        doc = copy.deepcopy(demo)
        edit(doc)
        try:
            build(doc)
            fails.append(f"{name}: built a command line without {key}")
        except NotSetUp as e:
            if key not in str(e):
                fails.append(f"{name}: named {e}, expected {key}")

    saved = os.environ.pop("REGNOLOGY_MCP_HOME", None)
    try:
        cmd = fields_cmd(demo, fields())
        want = {"-Command": "pull", "-Version": "1.2.0", "-SiteUrl": "https://tracker.example.com",
                "-AllowedSite": "https://tracker.example.com", "-Project": "DEMO", "-FixVersionPrefix": "Demo Product",
                "-ProductTag": "demo", "-RnField": "rn-field", "-ExcludeField": "exclude-field",
                "-ExcludeValue": "Yes", "-DoneStatuses": "Done,Closed", "-RefuseHosts": "archive.example.org"}
        got = {k: val(cmd, k) for k in want}
        if got != want or Path(cmd[5]).name != "rn-fields.ps1" or "-Apply" in cmd:
            fails.append(f"fields pull: {got}")
        if not str(val(cmd, "-EnvFile")).endswith(".env.tracker"):
            fails.append(f"login file keeps its note: {val(cmd, '-EnvFile')}")
        cmd = fields_cmd(demo, fields(action="push", apply=True, site="https://other.example.net"))
        if "-Apply" not in cmd or val(cmd, "-SiteUrl") != "https://other.example.net" \
                or val(cmd, "-AllowedSite") != "https://tracker.example.com":
            fails.append("fields push: --site must reach the tool, which refuses it against tracker.instance")
        with tempfile.TemporaryDirectory() as home:
            os.environ["REGNOLOGY_MCP_HOME"] = home
            if login_file(demo, "wiki") != Path(home) / ".env.wiki":
                fails.append("REGNOLOGY_MCP_HOME holds the login file")
            os.environ.pop("REGNOLOGY_MCP_HOME")

        cmd = wiki_cmd(demo, wiki(title="auto"))
        if Path(cmd[5]).name != "wiki-push.ps1" or val(cmd, "-Labels") != "doc-rn,demo" \
                or val(cmd, "-Title") != "Demo Page 1.2.0" or val(cmd, "-BaseUrl") != "https://wiki.example.com/wiki" \
                or "-Apply" in cmd:
            fails.append(f"wiki: {cmd[6:]}")
        cmd = wiki_cmd(demo, wiki(skip_labels=True, apply=True))
        if "-SkipLabels" not in cmd or "-Labels" in cmd or "-Title" in cmd or "-Apply" not in cmd:
            fails.append(f"wiki --skip-labels --apply: {cmd[6:]}")
        if node_cmd("md-to-confluence.mjs", ".confluence.xml", argparse.Namespace(md="out/n.md", out=None))[-1] \
                != str(Path("out/n.confluence.xml")):
            fails.append("confluence output beside the notes")

        stops("no tracker", "tracker.instance", lambda d: d["tracker"].pop("instance"), lambda d: fields_cmd(d, fields()))
        stops("no development project", "tracker.projects", lambda d: d["tracker"]["projects"].pop(),
              lambda d: fields_cmd(d, fields()))
        stops("no done statuses", "done_statuses", lambda d: d["desk"]["rela"]["release_notes"].update(done_statuses="TBD"),
              lambda d: fields_cmd(d, fields()))
        stops("no product tag", "product_tag", lambda d: d["desk"]["rela"]["release_notes"].update(output_file="rn.md"),
              lambda d: fields_cmd(d, fields()))
        stops("no login file", "credentials.wiki", lambda d: d["credentials"].pop("wiki"), lambda d: wiki_cmd(d, wiki()))
        stops("no wiki", "wiki.instance", lambda d: d.pop("wiki"), lambda d: wiki_cmd(d, wiki()))
    finally:
        os.environ.pop("REGNOLOGY_MCP_HOME", None)
        if saved is not None:
            os.environ["REGNOLOGY_MCP_HOME"] = saved
    for f in fails:
        print("FAIL", f)
    print("selftest OK: field, wiki and converter command lines; missing settings named" if not fails
          else "selftest FAILED")
    return 1 if fails else 0


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true", help="print the tool's command line, run nothing")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fields")
    p.add_argument("action", choices=["pull", "push"])
    p.add_argument("--version", required=True)
    p.add_argument("--site", help="the tracker URL to use; anything but tracker.instance is refused")
    p.add_argument("--with-commits", action="store_true")
    p.add_argument("--all-statuses", action="store_true")
    p.add_argument("--out-dir")
    p.add_argument("--input")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p = sub.add_parser("wiki")
    p.add_argument("--page", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--title", help="a new page title; `auto` sets the team's page title for --version")
    p.add_argument("--message")
    p.add_argument("--skip-labels", action="store_true")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("pdf")
    p.add_argument("--md", required=True)
    p.add_argument("--title")
    for name in ("confluence", "paste"):
        p = sub.add_parser(name)
        p.add_argument("--md", required=True)
        p.add_argument("--out")
    p = sub.add_parser("skeleton")
    p.add_argument("--version", required=True)
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    doc, source = _desk.load()
    _desk.gate("rela", "release_notes", doc, source)
    try:
        if a.cmd == "fields":
            return run(fields_cmd(doc, a), a.show)
        if a.cmd == "wiki":
            cmd = wiki_cmd(doc, a)
            if a.show:
                return run(cmd, True)
            import rn_export
            rn_export.DOC, rn_export.SOURCE = doc, source
            check = rn_export.cmd_page_check(argparse.Namespace(page=a.page, version=a.version))
            if check != 0:
                print("wiki push not run: the page check did not pass", file=sys.stderr)
                return check
            return run(cmd, False)
        if a.cmd == "skeleton":
            import rn_export
            try:
                print(rn_export.skeleton(doc, a.version), end="")
            except KeyError as e:
                raise NotSetUp(e.args[0]) from None
            return 0
        if a.cmd == "pdf":
            return run(pdf_cmd(doc, a), a.show)
        if a.cmd == "confluence":
            return run(node_cmd("md-to-confluence.mjs", ".confluence.xml", a), a.show)
        return run(node_cmd("md-to-plain-html.mjs", "-PASTE.html", a), a.show)
    except NotSetUp as e:
        print(f"{e} is not set in the desk settings; ask Olga to finish onboarding section rela-release-notes",
              file=sys.stderr)
        return _desk.NOT_SET_UP


if __name__ == "__main__":
    sys.exit(main())
