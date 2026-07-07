from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause


def jsonb_text(sql: str, *param_names: str) -> TextClause:
    """Return text(sql) for statements that CAST JSON text params AS jsonb.

    SVS uses ``jsonb_param(value)`` + ``CAST(:name AS jsonb)`` for raw SQL
    portability across SQLAlchemy 2, psycopg3, and managed Postgres. The param
    names are kept for readability/call-site auditing and intentionally do not
    bind SQLAlchemy JSONB types.
    """
    return text(sql)
