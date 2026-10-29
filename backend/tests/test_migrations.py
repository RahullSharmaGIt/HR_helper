import os
import tempfile

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_alembic_migrations():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db_path = tmp.name
        db_url = f"sqlite:///{db_path}"

        alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        alembic_cfg.set_main_option(
            "script_location", os.path.join(os.path.dirname(__file__), "..", "alembic")
        )
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        # 1. Upgrade to head
        command.upgrade(alembic_cfg, "head")

        engine = create_engine(db_url)
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        expected_tables = {
            "candidates",
            "resumes",
            "projects",
            "repository_selections",
            "analysis_jobs",
            "analysis_results",
            "alembic_version",
        }
        assert expected_tables.issubset(table_names)

        # 2. Downgrade to base
        command.downgrade(alembic_cfg, "base")

        inspector = inspect(engine)
        assert len(set(inspector.get_table_names()) - {"alembic_version"}) == 0
