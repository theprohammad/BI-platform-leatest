"""Migration tests (spec §7): the alembic chain must build a schema identical
to the ORM metadata (drift guard), and downgrade to empty."""
import pathlib

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db.models import Base
import app.graph.models  # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _cfg(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_migration_chain_matches_metadata(tmp_path):
    url = f"sqlite:///{tmp_path}/mig.db"
    command.upgrade(_cfg(url), "head")
    engine = create_engine(url)
    insp = inspect(engine)
    migrated = {t: {c["name"] for c in insp.get_columns(t)}
                for t in insp.get_table_names() if t != "alembic_version"}
    expected = {t.name: {c.name for c in t.columns}
                for t in Base.metadata.tables.values()}
    assert set(migrated) == set(expected), (
        f"table drift: only-migrated={set(migrated)-set(expected)} "
        f"only-metadata={set(expected)-set(migrated)}")
    for table, cols in expected.items():
        assert migrated[table] == cols, f"column drift in {table}: {migrated[table] ^ cols}"
    engine.dispose()


def test_migration_downgrade_to_empty(tmp_path):
    url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(url)
    tables = [t for t in inspect(engine).get_table_names() if t != "alembic_version"]
    assert tables == []
    engine.dispose()
