#!/usr/bin/env python3
"""Side-by-side parity: the original lena_comment.py against desk_comment.py.

Both run on the same synthetic analyses, the copy with the RA LQR desk settings
(and with a synthetic settings file holding the original's constants). Every
render and every dry-run post must give the same exit code, stdout, stderr and
ADF body. The one intended difference: the dry-run hint names --post where the
original names --apply.

Clara, Qata and Rela are checked the same way: the copy running as each of them
must give the original's output with that agent's opener and sign-off in place of
Lena's, and its own smart-link projects. Each RA LQR sign-off names the person
through {on_behalf_of} and must resolve to the original sign-off byte for byte. An agent without a comment block must be
refused, for a render and for a dry-run post alike.

The original is only read and run in place, with bytecode writing off, and its
SHA-256 is checked before and after. Nothing is ever posted: no run gets
--apply or --post, and the JIRA_API_* variables are removed from the children's
environment. When the original is not installed the test is skipped.

    python parity_test.py [--original <lena_comment.py>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
COPY = HERE.parent / "scripts" / "desk_comment.py"
RALQR_SETTINGS = HERE.parents[3] / "packs" / "doctrine-product-reg-liquidity-ralqr" / "product-desk" / "product-desk.yaml"
CANDIDATES = [
    Path.home() / ".claude" / "skills" / "ra-lqr-liquidity-tools" / "scripts" / "lena_comment.py",
    Path.home() / "GIT" / "lqr-ai-hub" / "LQR-Agents" / "skills" / "ra-lqr-liquidity-tools" / "scripts" / "lena_comment.py",
]
OPENER = "Hi, Lena is here."
SIGN_OFF = ("— This message was drafted and sent by Liquidity Lena on behalf of Feres Rahmouni "
            "· the RA LQR liquidity persona.")
SYNTHETIC_SETTINGS = f"""schema_version: "1.0"
product: {{id: parity-demo, name: Parity demo}}
tracker:
  instance: https://regnology-cloud.atlassian.net
  write_env_file: regnology-mcp/.env.regnology-cloud-jira
  markup: cloud-markdown
  projects: [{{key: FRRALM}}, {{key: FRRREL}}]
extensions:
  release-rela:
    tactics: []
  liquidity-lena:
    comment:
      name: Lena
      opener: "{OPENER}"
      sign_off: "{SIGN_OFF}"
"""

BASE = f"""{OPENER}

## Executive summary
- **Cause found:** the synthetic row lands in column 0070 (FRRALM-1). Proposed: fix the class-name test.
- Release FRRREL-2 is not affected; SUP-3 stays text. Proposed: confirm with a rerun.

## Full analysis
### Evidence
Row 0010, column 0070 — see `ProductClass.isExample`, [the spec](https://example.org/) and https://example.org/x.

| Version | Column 0070 |
|---|---|
| V1 | 490 |
| V2 | — |

1. First step with *emphasis* and **bold FRRALM-4**
   - nested detail
2. Second step, ISO-8601 dates

- bullet one
  continued line

```sql
SELECT 1
```

> Note: the baseline expects the wrong value.

---

{SIGN_OFF}
"""

CASES = {
    "base": BASE,
    "typed-variants": BASE.replace(OPENER, "Hello Lena is here!").replace(
        SIGN_OFF, "- This message was drafted by Lena, see above"),
    "crlf": BASE.replace("\n", "\r\n"),
    "no-opener": BASE.replace(OPENER + "\n", ""),
    "missing-summary": BASE.replace("## Executive summary", "## Summary"),
    "missing-full": BASE.replace("## Full analysis", "## Details"),
    "six-lines": BASE.replace("- Release", "- a\n- b\n- c\n- d\n- Release"),
    "empty-full": "## Executive summary\n- x\n## Full analysis\n\n",
    "wrong-order": "## Full analysis\nx\n## Executive summary\n- y\n",
    "oversized": BASE.replace("Second step", "x" * 30010),
}
TITLES = [None, "Full analysis - 2 findings"]

# The other RA LQR agents, as the desk settings must carry them: (opener, sign-off, extra smart-link project).
AGENTS = {
    "clerk-clara": ("Hi, Clara is here.", "— This message was drafted and sent by Clara on behalf of Feres Rahmouni "
                    "· the RA LQR ticket clerk persona.", "SUP"),
    "qa-qata": ("Hi, Qata is here.", "— This message was drafted and sent by Qata on behalf of Feres Rahmouni "
                "· the RA LQR quality checker persona.", None),
    "release-rela": ("Hi, Rela is here.", "— This message was drafted and sent by Rela on behalf of Feres Rahmouni "
                     "· the RA LQR release manager persona.", None),
}
AGENT_CASES = ("base", "crlf", "no-opener", "missing-summary", "oversized")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.get("content", []) or []:
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def swap(node, f):
    """Every string in a parsed JSON value passed through f."""
    if isinstance(node, str):
        return f(node)
    if isinstance(node, list):
        return [swap(v, f) for v in node]
    if isinstance(node, dict):
        return {k: swap(v, f) for k, v in node.items()}
    return node


def child_env(tmp: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("JIRA_API_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    for k in ("PRODUCT_DESK_HOME", "PRODUCT_DESK_SETTINGS", "PRODUCT_DESK_AGENT"):
        env.pop(k, None)
    return env


def run(script: Path, args: list[str], tmp: Path) -> tuple[int, str, str]:
    assert not {"--apply", "--post"} & set(args), "the parity test never writes to Jira"
    r = subprocess.run([sys.executable, "-B", str(script), *args], cwd=tmp, env=child_env(tmp),
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    return r.returncode, r.stdout, r.stderr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--original", help="path of the original lena_comment.py")
    a = ap.parse_args(argv)
    original = Path(a.original) if a.original else next((p for p in CANDIDATES if p.is_file()), None)
    if original is None or not original.is_file():
        print("parity_test: SKIP -- the original lena_comment.py is not installed "
              f"(looked in {', '.join(str(p) for p in CANDIDATES)})")
        return 0
    before = sha(original)
    fails: list[str] = []
    checks = 0
    with tempfile.TemporaryDirectory(prefix="desk-comment-parity-") as t:
        tmp = Path(t)
        synthetic = tmp / "product-desk.yaml"
        synthetic.write_text(SYNTHETIC_SETTINGS, encoding="utf-8")
        settings = [("synthetic", synthetic)] + ([("ra-lqr", RALQR_SETTINGS)] if RALQR_SETTINGS.is_file() else [])
        for name, text in CASES.items():
            src = tmp / f"{name}.md"
            src.write_bytes(text.encode("utf-8"))
            for title in TITLES:
                extra = ["--title", title] if title else []
                o_out = tmp / f"{name}.orig.json"
                o = run(original, ["render", "--in", str(src), "--out", str(o_out), *extra], tmp)
                o_post = run(original, ["post", "--in", str(src), "--key", "FRRALM-1", *extra], tmp)
                for label, sfile in settings:
                    c_out = tmp / f"{name}.{label}.json"
                    who = ["--settings", str(sfile), "--agent", "liquidity-lena"]
                    c = run(COPY, ["render", *who, "--in", str(src), "--out", str(c_out), *extra], tmp)
                    c_post = run(COPY, ["post", *who, "--in", str(src), "--key", "FRRALM-1", *extra], tmp)
                    tag = f"{name}{' / ' + title if title else ''} [{label}]"
                    checks += 1
                    if o != c:
                        fails.append(f"render differs: {tag}\n  original: {o}\n  copy:     {c}")
                    if o_out.exists() != c_out.exists() or (
                            o_out.exists() and json.loads(o_out.read_text("utf-8")) != json.loads(c_out.read_text("utf-8"))):
                        fails.append(f"ADF body differs: {tag}")
                    c_post_norm = (c_post[0], c_post[1].replace("add --post to post", "add --apply to post"), c_post[2])
                    checks += 1
                    if o_post != c_post_norm:
                        fails.append(f"dry-run post differs: {tag}\n  original: {o_post}\n  copy:     {c_post}")
                    if c_out.exists():
                        c_out.unlink()
                if o_out.exists():
                    o_out.unlink()
        bad_key = (run(original, ["post", "--in", str(tmp / "base.md"), "--key", "not-a-key"], tmp),
                   run(COPY, ["post", "--settings", str(synthetic), "--agent", "liquidity-lena",
                              "--in", str(tmp / "base.md"), "--key", "not-a-key"], tmp))
        checks += 1
        if bad_key[0] != bad_key[1]:
            fails.append(f"bad key differs:\n  original: {bad_key[0]}\n  copy:     {bad_key[1]}")

        # Each other agent: the copy must do exactly what the original does, with that agent's
        # opener and sign-off where the original has Lena's. SUP-3 is taken out of the text so an
        # agent with SUP among its smart-link projects still compares exactly; it is checked apart.
        if RALQR_SETTINGS.is_file():
            def as_agent(s: str, opener: str, sign_off: str) -> str:
                return s.replace(OPENER, opener).replace(SIGN_OFF, sign_off)

            for agent, (opener, sign_off, extra) in AGENTS.items():
                who = ["--settings", str(RALQR_SETTINGS), "--agent", agent]
                for name in AGENT_CASES:
                    text = CASES[name].replace("SUP-3 stays text", "the support ticket stays text")
                    o_src, c_src = tmp / f"{name}.lena.md", tmp / f"{name}.{agent}.md"
                    o_src.write_bytes(text.encode("utf-8"))
                    c_src.write_bytes(as_agent(text, opener, sign_off).encode("utf-8"))
                    o_out, c_out = tmp / f"{name}.lena.json", tmp / f"{name}.{agent}.json"
                    o = run(original, ["render", "--in", str(o_src), "--out", str(o_out)], tmp)
                    c = run(COPY, ["render", *who, "--in", str(c_src), "--out", str(c_out)], tmp)
                    o_post = run(original, ["post", "--in", str(o_src), "--key", "FRRALM-1"], tmp)
                    c_post = run(COPY, ["post", *who, "--in", str(c_src), "--key", "FRRALM-1"], tmp)
                    want = tuple(as_agent(x, opener, sign_off) if isinstance(x, str) else x for x in o)
                    want_post = tuple(as_agent(x, opener, sign_off) if isinstance(x, str) else x for x in o_post)
                    c_post = (c_post[0], c_post[1].replace("add --post to post", "add --apply to post"), c_post[2])
                    checks += 3
                    if want != c:
                        fails.append(f"render differs as {agent}: {name}\n  expected: {want}\n  copy:     {c}")
                    if want_post != c_post:
                        fails.append(f"dry-run post differs as {agent}: {name}\n  expected: {want_post}\n  copy:     {c_post}")
                    o_body = swap(json.loads(o_out.read_text("utf-8")), lambda s: as_agent(s, opener, sign_off)) \
                        if o_out.exists() else None
                    if (o_body is None) != (not c_out.exists()) or (
                            o_body is not None and o_body != json.loads(c_out.read_text("utf-8"))):
                        fails.append(f"ADF body differs as {agent}: {name}")
                    if name == "base" and c_out.exists():
                        body = json.loads(c_out.read_text("utf-8"))
                        texts = [n["text"] for n in walk(body) if n.get("type") == "text"]
                        checks += 1
                        if not (texts and texts[0].strip() == opener and texts[-1].strip() == sign_off):
                            fails.append(f"{agent}: the comment does not open with its opener and close with its sign-off")
                    for p in (o_src, c_src, o_out, c_out):
                        if p.exists():
                            p.unlink()
                # The smart-link projects: SUP-3 is a card only for an agent that lists SUP.
                sup = tmp / f"sup.{agent}.md"
                sup.write_bytes(as_agent(CASES["base"], opener, sign_off).encode("utf-8"))
                sup_out = tmp / f"sup.{agent}.json"
                r = run(COPY, ["render", *who, "--in", str(sup), "--out", str(sup_out)], tmp)
                cards = [n["attrs"]["url"] for n in walk(json.loads(sup_out.read_text("utf-8")))
                         if n.get("type") == "inlineCard"] if sup_out.exists() else []
                has_sup = any(u.endswith("/browse/SUP-3") for u in cards)
                checks += 1
                if r[0] != 0 or has_sup != (extra == "SUP") or not any(u.endswith("/browse/FRRALM-1") for u in cards):
                    fails.append(f"{agent}: smart links {cards} (rc {r[0]}), SUP expected: {extra == 'SUP'}")

        # The RA LQR settings name the person once (comment.on_behalf_of); each agent's sign-off
        # carries the placeholder and must resolve to exactly the original sign-off.
        if RALQR_SETTINGS.is_file():
            raw = RALQR_SETTINGS.read_text(encoding="utf-8")
            checks += 1
            if "on behalf of Feres Rahmouni" in raw or "{on_behalf_of}" not in raw:
                fails.append("RA LQR settings: sign-offs must use {on_behalf_of}, not a hard-coded name")
            for agent, sign_off in [("liquidity-lena", SIGN_OFF)] + [(k, v[1]) for k, v in AGENTS.items()]:
                r = run(COPY, ["identity", "--settings", str(RALQR_SETTINGS), "--agent", agent], tmp)
                checks += 1
                got = json.loads(r[1]).get("sign_off") if r[0] == 0 else None
                if got != sign_off:
                    fails.append(f"{agent}: resolved sign-off {got!r} (rc {r[0]}), original {sign_off!r}")

        # An agent without a comment block is refused before anything is built or sent.
        for cmd in ("render", "post"):
            args = [cmd, "--settings", str(synthetic), "--agent", "release-rela", "--in", str(tmp / "base.md")]
            args += ["--key", "FRRALM-1"] if cmd == "post" else ["--out", str(tmp / "refused.json")]
            r = run(COPY, args, tmp)
            checks += 1
            if r[0] == 0 or "no comment identity for 'release-rela'" not in r[1] + r[2] \
                    or "dry run" in r[1] or (tmp / "refused.json").exists():
                fails.append(f"{cmd} as an agent without a comment block was not refused: {r}")
    after = sha(original)
    if before != after:
        fails.append(f"the original changed during the test: {before} -> {after}")
    print(f"parity_test: original {original} (sha256 {before[:12]}, unchanged: {before == after})")
    print(f"parity_test: {checks} comparisons, settings {', '.join(l for l, _ in settings)}:",
          "PASS" if not fails else f"FAILED ({len(fails)})")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
