"""Smoke test: alembic upgrade head creates both tables; downgrade drops them."""
import os
import subprocess
import tempfile
import pytest


def _run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=30
    )


def test_upgrade_and_downgrade():
    """Run 'alembic upgrade head' then 'alembic downgrade base' on a temp DB."""
    svc_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    env_vars = os.environ.copy()
    env_vars["DB_PATH"] = db_path

    try:
        # -- upgrade --
        result = _run(
            ["python", "-m", "alembic", "-x", f"db_path={db_path}", "upgrade", "head"],
            cwd=svc_dir,
        )
        assert result.returncode == 0, f"upgrade failed:\n{result.stderr}"

        # -- verify tables exist --
        import sqlite3
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "agent_sessions" in tables, f"agent_sessions not found in {tables}"
        assert "session_events" in tables, f"session_events not found in {tables}"

        # -- downgrade --
        result = _run(
            ["python", "-m", "alembic", "-x", f"db_path={db_path}", "downgrade", "base"],
            cwd=svc_dir,
        )
        assert result.returncode == 0, f"downgrade failed:\n{result.stderr}"

        # -- verify tables gone --
        conn = sqlite3.connect(db_path)
        tables_after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "agent_sessions" not in tables_after
        assert "session_events" not in tables_after

    finally:
        os.unlink(db_path)
