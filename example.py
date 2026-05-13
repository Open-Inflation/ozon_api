from __future__ import annotations

import asyncio
from ozon_api.abstraction import OzonPage
from ozon_api.manager import OzonAPI


async def main() -> None:
    async def parse(model):
        products = model.extract_products()

        if not products:
            print("Товары не найдены.")
            return

        for product in products:
            print(product.render())
            
    async with OzonAPI(headless=False) as api:
        resp = await api.Catalog.feed()
        with open("response.json", "w", encoding="utf-8") as f:
            import json
            f.write(json.dumps(resp.json(), indent=4, ensure_ascii=False))
        model = OzonPage.model_validate(resp.json())
        await parse(model)
        for _i in range(100):
            await asyncio.sleep(1)
            resp = await api.Catalog.feed(page_url=model.next_page)
            model = OzonPage.model_validate(resp.json())
            await parse(model)



if __name__ == "__main__":
    asyncio.run(main())
