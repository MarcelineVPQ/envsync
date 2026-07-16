"""Tests for envsync — run with: python -m pytest test_envsync.py"""

import envsync

TEMPLATE = """\
# ==================== Core ====================
# The database URL.
DATABASE_URL=postgresql://localhost/app

# Web server port (default 8080)
PORT=8080

# ==================== Security ====================
# Number of trusted proxies. Default 0.
TRUSTED_PROXY_COUNT=0
"""

# An older env: has DATABASE_URL (customized) and PORT, but predates TRUSTED_PROXY_COUNT.
# Also carries a LEGACY_KEY the template no longer knows about.
ENV = """\
DATABASE_URL=postgresql://prod-db/app
PORT=9090
LEGACY_KEY=something
"""


def test_diff_finds_missing_extra_and_present():
    d = envsync.diff(TEMPLATE, ENV)
    assert d.added == ["TRUSTED_PROXY_COUNT"]
    assert d.extra == ["LEGACY_KEY"]
    assert set(d.present) == {"DATABASE_URL", "PORT"}
    assert d.in_sync is False


def test_in_sync_when_all_present():
    env = TEMPLATE  # identical -> nothing missing, nothing extra
    assert envsync.diff(TEMPLATE, env).in_sync is True


def test_append_keeps_existing_values_and_adds_missing():
    out = envsync.build_append(TEMPLATE, ENV)
    vals = envsync.parse_values(out)
    # existing values untouched
    assert vals["DATABASE_URL"] == "postgresql://prod-db/app"
    assert vals["PORT"] == "9090"
    # missing var added with the template default + its comment
    assert vals["TRUSTED_PROXY_COUNT"] == "0"
    assert "Number of trusted proxies" in out
    # extra var preserved
    assert vals["LEGACY_KEY"] == "something"


def test_append_is_idempotent():
    once = envsync.build_append(TEMPLATE, ENV)
    twice = envsync.build_append(TEMPLATE, once)
    assert once == twice


def test_rewrite_follows_template_keeps_values_and_preserves_extras():
    out = envsync.build_rewrite(TEMPLATE, ENV)
    vals = envsync.parse_values(out)
    assert vals["DATABASE_URL"] == "postgresql://prod-db/app"  # kept
    assert vals["PORT"] == "9090"                              # kept
    assert vals["TRUSTED_PROXY_COUNT"] == "0"                  # from template
    assert vals["LEGACY_KEY"] == "something"                   # preserved in trailing block
    # structure/comments come from the template
    assert "==================== Security ====================" in out
    # template order is honored: DATABASE_URL before PORT before TRUSTED_PROXY_COUNT
    assert out.index("DATABASE_URL=") < out.index("PORT=") < out.index("TRUSTED_PROXY_COUNT=")


def test_export_prefix_and_missing_env_file():
    tmpl = "export API_KEY=changeme\n"
    d = envsync.diff(tmpl, "")           # env file doesn't exist yet -> empty
    assert d.added == ["API_KEY"]
    out = envsync.build_append(tmpl, "")
    assert envsync.parse_values(out)["API_KEY"] == "changeme"


def test_main_missing_env_ok_returns_zero(tmp_path):
    tmpl = tmp_path / ".env.example"
    tmpl.write_text("FOO=bar\n")
    env = tmp_path / ".env"  # does not exist
    assert envsync.main([str(tmpl), str(env), "--missing-env-ok"]) == 0


def test_main_reports_drift_nonzero(tmp_path):
    tmpl = tmp_path / ".env.example"
    tmpl.write_text("FOO=bar\nNEW=1\n")
    env = tmp_path / ".env"
    env.write_text("FOO=custom\n")  # missing NEW
    assert envsync.main([str(tmpl), str(env)]) == 1


def test_main_apply_syncs_then_exits_zero(tmp_path):
    tmpl = tmp_path / ".env.example"
    tmpl.write_text("FOO=bar\nNEW=1\n")
    env = tmp_path / ".env"
    env.write_text("FOO=custom\n")
    assert envsync.main([str(tmpl), str(env), "--apply"]) == 0
    vals = envsync.parse_values(env.read_text())
    assert vals["FOO"] == "custom" and vals["NEW"] == "1"
    # now in sync
    assert envsync.main([str(tmpl), str(env)]) == 0
