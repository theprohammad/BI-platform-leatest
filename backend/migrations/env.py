"""Alembic environment. Migrations run on a SYNC engine (sqlite/psycopg URL);
the app converts its async DSN before invoking upgrade (db/session.py)."""
from alembic import context
from sqlalchemy import create_engine

from app.db.models import Base
import app.graph.models  # noqa: F401  register all graph tables

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=context.config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(context.config.get_main_option("sqlalchemy.url"))
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
