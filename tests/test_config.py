"""The configuration module must be importable without live credentials.

Previously it used os.environ[...] for the Supabase settings, so importing it
raised KeyError on any machine without those secrets - which made the whole
codebase untestable and made CI fail with an unhelpful traceback.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _import_in_subprocess(env_overrides):
    env = {k: v for k, v in os.environ.items() if k not in (
        "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "OPENROUTER_API_KEY",
        "RESEND_API_KEY",
    )}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import config; print('ok')"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )


def test_imports_with_no_secrets_configured():
    result = _import_in_subprocess({})
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_missing_secrets_lists_every_absent_required_name():
    result = subprocess.run(
        [sys.executable, "-c",
         "import config; print(','.join(config.missing_secrets()))"],
        cwd=ROOT, capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if k not in (
            "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",
            "OPENROUTER_API_KEY", "RESEND_API_KEY")},
    )
    assert result.returncode == 0, result.stderr
    missing = result.stdout.strip().split(",")
    assert set(missing) == {
        "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",
        "OPENROUTER_API_KEY", "RESEND_API_KEY",
    }


def test_require_secrets_names_the_missing_variable():
    result = subprocess.run(
        [sys.executable, "-c", "import config; config.require_secrets()"],
        cwd=ROOT, capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if k not in (
            "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",
            "OPENROUTER_API_KEY", "RESEND_API_KEY")},
    )
    assert result.returncode != 0
    assert "SUPABASE_URL" in result.stderr
    # Every missing name at once, not just the first.
    assert "RESEND_API_KEY" in result.stderr
