from __future__ import annotations

import asyncio

from app.core.database import engine
from app.models import Base


async def _run() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
