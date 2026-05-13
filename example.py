from __future__ import annotations

import asyncio
import sys


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ozon_api.abstraction import OzonPage
from ozon_api.manager import OzonAPI


async def main() -> None:
    async with OzonAPI(headless=False) as api:
        resp = await api.Catalog.feed()
        model = OzonPage.model_validate(resp.json())
        products = model.extract_products()

        if not products:
            print("Товары не найдены.")
            return

        print(products[0].render())


if __name__ == "__main__":
    asyncio.run(main())
