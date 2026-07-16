# envsync

[![tests](https://github.com/MarcelineVPQ/envsync/actions/workflows/tests.yml/badge.svg)](https://github.com/MarcelineVPQ/envsync/actions/workflows/tests.yml)

A tiny, dependency-free tool that keeps a real `.env` in sync with a documented
template (`.env.example`). When the template grows a new variable, envsync tells
you your `.env` is behind — and can add the newcomer (with its comment + default)
without touching a single value you've already set.

Built to scratch a specific itch: a template file accumulates new variables over
time, and every deployed `.env` silently falls behind until something breaks at
boot for a missing key.

## Install

None. It's one stdlib-only file:

```bash
python3 envsync.py TEMPLATE ENVFILE [options]
```

## Usage

```bash
# Dry-run report (default). Exit 0 = in sync, 1 = drift (nice for CI/pre-commit).
python3 envsync.py .env.example .env

# Add missing vars in place, keeping your file's layout. Backs up to .env.bak.
python3 envsync.py .env.example .env --apply --backup

# Restructure .env to follow the template's sections/comments, filling in your
# existing values; anything of yours the template doesn't know about is kept in a
# trailing block (never dropped).
python3 envsync.py .env.example .env --apply --mode rewrite --backup
```

## What it reports

| Bucket    | Meaning                                            | What envsync does            |
|-----------|----------------------------------------------------|------------------------------|
| `MISSING` | in the template, not in your env                   | can add (template default)   |
| `EXTRA`   | in your env, not in the template (typo/deprecated) | flags it, never deletes      |
| in both   | present in both                                    | **your value is kept as-is** |

## Rules

- **A value you've already set is never overwritten.** The template only supplies
  the value for variables you don't have yet.
- **Nothing is deleted.** `EXTRA` variables are reported (rewrite mode keeps them
  in a trailing block) so a real-but-undocumented key isn't lost to a typo guess.
- **Idempotent.** Running `--apply` twice is a no-op the second time.
- Handles `export KEY=val`, empty `KEY=`, and a missing target file (treated as
  empty — good for scaffolding a fresh `.env` from the template).

## Modes

- **append** (default): least surprising. Appends the missing variables (with their
  template comments) under an `# ---- Added by envsync ----` header, leaving the
  rest of your file exactly as it was.
- **rewrite**: produces a clean, fully-documented file that mirrors the template's
  order and section headers, with your values slotted in. Good for a periodic
  tidy-up; reorders the file, so use `--backup`.

## Use it as a pre-commit hook

envsync ships a `.pre-commit-hooks.yaml`, so another repo can gate commits on
`.env` drift. The hook runs only when **`.env.example`** is staged (the template
is what grows new variables) and reports whether the local `.env` is behind. It
never fails just because `.env` is absent, so CI / env-var-only machines aren't
blocked.

In the consuming repo's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/<you>/envsync
    rev: v0.1.0
    hooks:
      - id: envsync
```

Or, without a remote, as a local hook:

```yaml
repos:
  - repo: local
    hooks:
      - id: envsync
        name: envsync — .env vs .env.example
        entry: python3 /path/to/envsync.py --missing-env-ok .env.example .env
        language: system
        files: (^|/)\.env\.example$
        pass_filenames: false
```

Now when you `git commit` an updated `.env.example`, the hook fails the commit if
your `.env` is missing a newly-documented variable — run
`envsync.py .env.example .env --apply` to fix it, then re-commit.

## Tests

```bash
python -m pytest test_envsync.py
```
