#!/usr/bin/env python3
"""
envsync — reconcile an existing .env against a template (.env.example).

Reads a base template that documents every variable (with its comments/defaults)
and an existing env file that holds real values, then tells you — or fixes —
what has drifted:

  * ADDED   : in the template but missing from your env  -> can be added
  * EXTRA   : in your env but not in the template         -> maybe deprecated/typo
  * PRESENT : in both                                     -> your value is kept

Cardinal rule: a value you have already set is NEVER overwritten. The template
only supplies the value for variables you don't have yet.

Usage:
    envsync.py TEMPLATE ENVFILE                 # dry-run report (default)
    envsync.py TEMPLATE ENVFILE --apply         # append missing vars in place
    envsync.py TEMPLATE ENVFILE --apply --mode rewrite   # restructure to match template
    envsync.py TEMPLATE ENVFILE --apply --backup         # write ENVFILE.bak first

Exit status: 0 = in sync (or applied), 1 = drift found in a dry run (handy for CI).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# KEY=VALUE, tolerating a leading `export ` and surrounding whitespace.
_VAR_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def _is_assignment(line: str) -> Optional[re.Match]:
    """Match a variable assignment, but not a commented-out one."""
    if line.lstrip().startswith("#"):
        return None
    return _VAR_RE.match(line)


@dataclass
class Block:
    """A template variable together with the comment/blank lines that precede it.

    A trailing Block with key=None captures comments at the end of the file that
    aren't attached to any variable.
    """

    comments: List[str] = field(default_factory=list)
    key: Optional[str] = None
    value: Optional[str] = None


def parse_values(text: str) -> Dict[str, str]:
    """Return {KEY: raw_value} for every assignment in the file (last wins)."""
    values: Dict[str, str] = {}
    for line in text.splitlines():
        m = _is_assignment(line)
        if m:
            values[m.group(1)] = m.group(2)
    return values


def parse_blocks(text: str) -> List[Block]:
    """Split a template into ordered Blocks (each var + its leading comments)."""
    blocks: List[Block] = []
    pending: List[str] = []
    for line in text.splitlines():
        m = _is_assignment(line)
        if m:
            blocks.append(Block(comments=pending, key=m.group(1), value=m.group(2)))
            pending = []
        else:
            pending.append(line)
    if pending:
        blocks.append(Block(comments=pending, key=None, value=None))
    return blocks


@dataclass
class Diff:
    added: List[str]      # in template, missing from env
    extra: List[str]      # in env, not in template
    present: List[str]    # in both

    @property
    def in_sync(self) -> bool:
        return not self.added and not self.extra


def diff(template_text: str, env_text: str) -> Diff:
    tmpl_blocks = parse_blocks(template_text)
    tmpl_keys = [b.key for b in tmpl_blocks if b.key]
    env_values = parse_values(env_text)
    added = [k for k in tmpl_keys if k not in env_values]
    extra = [k for k in env_values if k not in set(tmpl_keys)]
    present = [k for k in tmpl_keys if k in env_values]
    return Diff(added=added, extra=extra, present=present)


def _render_block(b: Block, value: str, include_comments: bool) -> List[str]:
    out: List[str] = []
    if include_comments:
        out.extend(b.comments)
    out.append(f"{b.key}={value}")
    return out


def build_append(template_text: str, env_text: str, include_comments: bool = True) -> str:
    """Return env_text with any missing template vars appended (values from template)."""
    d = diff(template_text, env_text)
    if not d.added:
        return env_text
    tmpl_blocks = {b.key: b for b in parse_blocks(template_text) if b.key}
    lines: List[str] = env_text.splitlines()
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("# ---- Added by envsync (present in the template, were missing here) ----")
    for key in d.added:
        b = tmpl_blocks[key]
        lines.append("")
        lines.extend(_render_block(b, b.value, include_comments))
    return "\n".join(lines) + "\n"


def build_rewrite(template_text: str, env_text: str) -> str:
    """Rewrite to follow the template's structure/comments, keeping existing values.

    Variables the user has set keep their value; everything else takes the template
    default. Extra variables (in env, not in template) are preserved in a trailing
    block so nothing is silently dropped.
    """
    env_values = parse_values(env_text)
    out: List[str] = []
    for b in parse_blocks(template_text):
        out.extend(b.comments)
        if b.key is not None:
            value = env_values.get(b.key, b.value)
            out.append(f"{b.key}={value}")
    extras = [k for k in env_values if k not in {b.key for b in parse_blocks(template_text) if b.key}]
    if extras:
        if out and out[-1].strip():
            out.append("")
        out.append("# ---- Not in the template (kept from your env; review for typos/deprecation) ----")
        for k in extras:
            out.append(f"{k}={env_values[k]}")
    return "\n".join(out).rstrip("\n") + "\n"


def _report(template: Path, envfile: Path, d: Diff) -> None:
    print(f"template : {template}")
    print(f"env file : {envfile}")
    print(f"in sync  : {'yes' if d.in_sync else 'NO'}")
    print()
    if d.added:
        print(f"MISSING ({len(d.added)}) — in the template but not your env:")
        for k in d.added:
            print(f"  + {k}")
        print()
    if d.extra:
        print(f"EXTRA ({len(d.extra)}) — in your env but not the template (deprecated? typo?):")
        for k in d.extra:
            print(f"  ? {k}")
        print()
    print(f"in both  : {len(d.present)} variable(s), values untouched")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Reconcile an env file against a template.")
    ap.add_argument("template", type=Path, help="the base template (e.g. .env.example)")
    ap.add_argument("envfile", type=Path, help="the env file to check/update (e.g. .env)")
    ap.add_argument("--apply", action="store_true", help="write changes (default: report only)")
    ap.add_argument("--mode", choices=["append", "rewrite"], default="append",
                    help="append (default: add missing vars in place) or rewrite (restructure to template)")
    ap.add_argument("--backup", action="store_true", help="write ENVFILE.bak before applying")
    ap.add_argument("--no-comments", action="store_true", help="append mode: omit template comments")
    ap.add_argument("--missing-env-ok", action="store_true",
                    help="exit 0 (not 1) when ENVFILE doesn't exist — for pre-commit on machines with no .env")
    args = ap.parse_args(argv)

    if not args.template.exists():
        print(f"error: template not found: {args.template}", file=sys.stderr)
        return 2
    if not args.envfile.exists() and args.missing_env_ok:
        print(f"{args.envfile} not present — nothing to reconcile (--missing-env-ok).")
        return 0
    template_text = args.template.read_text()
    env_text = args.envfile.read_text() if args.envfile.exists() else ""

    d = diff(template_text, env_text)
    _report(args.template, args.envfile, d)

    if not args.apply:
        # Non-zero on drift so CI / pre-commit can gate on it.
        return 0 if d.in_sync else 1

    if args.mode == "append":
        new_text = build_append(template_text, env_text, include_comments=not args.no_comments)
    else:
        new_text = build_rewrite(template_text, env_text)

    if new_text == env_text:
        print("\nnothing to write — already in sync.")
        return 0

    if args.backup and args.envfile.exists():
        backup = args.envfile.with_suffix(args.envfile.suffix + ".bak")
        backup.write_text(env_text)
        print(f"\nbackup   : {backup}")
    args.envfile.write_text(new_text)
    print(f"\nwrote    : {args.envfile} ({args.mode} mode)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
