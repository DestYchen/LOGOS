from __future__ import annotations

import asyncio
from typing import Iterable, Sequence

from sqlalchemy import text

from app.core.database import engine
from app.core.enums import (
    BatchStatus,
    DocumentStatus,
    DocumentType,
    ValidationSeverity,
)
from app.models import Base


async def _fetch_enum_labels(enum_name: str) -> set[str]:
    query = text(
        """
        SELECT e.enumlabel
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE t.typname = :enum_name
        ORDER BY e.enumsortorder
        """
    )
    async with engine.connect() as conn:
        result = await conn.execute(query, {"enum_name": enum_name})
        return set(result.scalars().all())


async def _quote(value: str) -> str:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT quote_literal(:value)"), {"value": value})
        return result.scalar_one()


async def _add_enum_values(enum_name: str, values: Sequence[str]) -> None:
    if not values:
        return
    async with engine.connect() as conn:
        autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        for value in values:
            quoted = await _quote(value)
            statement = text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS {quoted}")
            await autocommit_conn.execute(statement)


async def _rename_enum_value(enum_name: str, old: str, new: str) -> None:
    old_quoted = await _quote(old)
    new_quoted = await _quote(new)
    statement = text(f"ALTER TYPE {enum_name} RENAME VALUE {old_quoted} TO {new_quoted}")
    async with engine.connect() as conn:
        autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit_conn.execute(statement)


async def _update_document_type_rows(old: str, new: str) -> None:
    statement = text("UPDATE documents SET doc_type = :new WHERE doc_type = :old")
    async with engine.connect() as conn:
        await conn.execute(statement, {"old": old, "new": new})
        await conn.commit()


async def _sync_document_type_enum() -> None:
    enum_name = "documenttype"
    existing = await _fetch_enum_labels(enum_name)

    if "BILL_OF_LADING" in existing and "BILL_OF_LANDING" not in existing:
        await _rename_enum_value(enum_name, "BILL_OF_LADING", "BILL_OF_LANDING")
        existing = await _fetch_enum_labels(enum_name)
    elif "BILL_OF_LADING" in existing and "BILL_OF_LANDING" in existing:
        await _update_document_type_rows("BILL_OF_LADING", "BILL_OF_LANDING")

    expected = [member.value for member in DocumentType]
    missing = [value for value in expected if value not in existing]
    await _add_enum_values(enum_name, missing)

    if "BILL_OF_LADING" in await _fetch_enum_labels(enum_name):
        await _update_document_type_rows("BILL_OF_LADING", "BILL_OF_LANDING")


async def _sync_enum(enum_name: str, expected_values: Iterable[str]) -> None:
    existing = await _fetch_enum_labels(enum_name)
    missing = [value for value in expected_values if value not in existing]
    await _add_enum_values(enum_name, missing)


async def _sync_enums() -> None:
    await _sync_document_type_enum()
    await _sync_enum("documentstatus", [member.value for member in DocumentStatus])
    await _sync_enum("batchstatus", [member.value for member in BatchStatus])
    await _sync_enum("validationseverity", [member.value for member in ValidationSeverity])


async def _run() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _sync_enums()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
