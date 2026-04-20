import asyncio
from ozon_api.manager import OzonAPI
from ozon_api.abstraction import OzonPage
from pprint import pprint

async def main():
    async with OzonAPI() as api:
        resp = await api.Catalog.feed()
        model = OzonPage.model_validate(resp.json())

        products = model.extract_products()

        for product in products:
            print(product.sku)
            print(product.title)
            print(product.url)
            print(product.image_url)
            print(product.price)
            print(product.original_price)
            print(product.discount)
            print(product.rating)
            print(product.reviews)
            print(product.badges)
            print(product.labels)
            print("---")

if __name__ == "__main__":
    asyncio.run(main())