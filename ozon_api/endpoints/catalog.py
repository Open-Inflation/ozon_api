"""Каталог и работа с ним"""

from typing import TYPE_CHECKING
from dataclasses import dataclass
from human_requests import ApiChild, ApiParent, api_child_field
from human_requests.abstraction import FetchResponse, HttpMethod


if TYPE_CHECKING:
    from ozon_api.manager import OzonAPI


class ProductService(ApiChild["OzonAPI"]):
    """Сервис для работы с товарами в каталоге."""

    async def info():
        pass # TODO

    async def other_offers_from_sellers():
        pass # TODO


@dataclass(init=False)
class ClassCatalog(ApiChild["OzonAPI"], ApiParent):
    """
    """

    Product: ProductService = api_child_field(
        lambda parent: ProductService(parent.parent)
    )
    """Сервис для работы с товарами в каталоге."""

    def __init__(self, parent: "OzonAPI"):
        super().__init__(parent)
        ApiParent.__post_init__(self)
    
    async def tree(self):
        pass # TODO

    async def subtree(self):
        pass # TODO

    async def feed(self, page_url: str | None = None) -> FetchResponse:
        # TODO сделать выбор категорий *как-то*
        url = self.parent.API_URL

        return await self._parent._request(
            HttpMethod.GET, url=url
        )
