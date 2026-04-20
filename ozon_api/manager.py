import asyncio
from dataclasses import dataclass, field
from typing import Any

from camoufox import AsyncCamoufox, DefaultAddons
from human_requests import (ApiParent, HumanBrowser, HumanContext, HumanPage,
                            api_child_field)
from human_requests.abstraction import FetchResponse, HttpMethod, Proxy
from .endpoints.catalog import ClassCatalog


from .abstraction.errors import VPNError


@dataclass
class OzonAPI(ApiParent):
    """Клиент FixPrice."""

    timeout_ms: float = 25000.0
    """Время ожидания ответа от сервера в миллисекундах."""
    headless: bool = False
    """Запускать браузер в headless режиме?"""
    test_mode: bool = False
    """Режим тестирования предполагает более глубокий _warmup который не требуется для обычного использования"""
    proxy: str | dict | Proxy | None = field(default_factory=Proxy.from_env)
    """Прокси-сервер для всех запросов (если нужен). По умолчанию берет из окружения (если есть).
    Принимает как формат Playwright, так и строчный формат."""
    browser_opts: dict[str, Any] = field(default_factory=dict)
    """Дополнительные опции для браузера (см. https://camoufox.com/python/installation/)"""

    MAIN_SITE_URL: str = "https://www.ozon.ru/"
    API_URL: str = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2"

    # будет создана в __post_init__
    session: HumanBrowser = field(init=False, repr=False)
    """Внутренняя сессия браузера для выполнения HTTP-запросов."""
    # будет создано в warmup
    ctx: HumanContext = field(init=False, repr=False)
    """Внутренний контекст сессии браузера"""
    page: HumanPage = field(init=False, repr=False)
    """Внутренний страница сессии браузера"""

    Catalog: ClassCatalog = api_child_field(ClassCatalog)
    """API для работы с каталогом товаров."""

    async def __aenter__(self):
        """Вход в контекстный менеджер с автоматическим прогревом сессии."""
        await self._warmup()
        return self

    # Прогрев сессии (headless ➜ cookie `session` ➜ accessToken)
    async def _warmup(self) -> None:
        """Прогрев сессии через браузер для получения человекоподобности."""
        px = self.proxy if isinstance(self.proxy, Proxy) else Proxy(self.proxy)
        br = await AsyncCamoufox(
            headless=self.headless,
            proxy=px.as_dict(),
            humanize=True,
            **self.browser_opts,
            block_images=True,
            i_know_what_im_doing=True,
            exclude_addons=[DefaultAddons.UBO],
        ).start()

        self.session = HumanBrowser.replace(br)
        self.ctx = await self.session.new_context()
        self.page = await self.ctx.new_page()
        self.page.on_error_screenshot_path = "screenshot.png"

        await self.page.goto(self.MAIN_SITE_URL, wait_until="networkidle")

        if await self.page.query_selector("div.load-error"):
            await self.page.click("button#reload-button", timeout=self.timeout_ms)
            try:
                await self.page.wait_for_load_state(
                    "networkidle", timeout=self.timeout_ms
                )
            except Exception:
                pass

        wait_tasks = {
            asyncio.create_task(
                self.page.wait_for_selector(
                    selector="div#__ozon",
                    timeout=self.timeout_ms,
                    state="visible",
                )
            ): "ozon",
            asyncio.create_task(
                self.page.wait_for_selector(
                    selector="body > div.con",
                    timeout=self.timeout_ms,
                    state="visible",
                )
            ): "vpn",
        }
        last_exc: Exception | None = None
        try:
            pending = set(wait_tasks)
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    name = wait_tasks[task]
                    try:
                        await task
                    except Exception as exc:
                        last_exc = exc
                        continue
                    if name == "vpn":
                        raise VPNError()
                    return
            if last_exc is not None:
                raise last_exc
        finally:
            for task in wait_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*wait_tasks, return_exceptions=True)

    async def __aexit__(self, *exc):
        """Выход из контекстного менеджера с закрытием сессии."""
        await self.close()

    async def close(self):
        """Закрыть HTTP-сессию и освободить ресурсы."""
        await self.session.close()

    async def _request(
        self,
        method: HttpMethod,
        url: str,
        *,
        json_body: Any | None = None,
        add_unstandard_headers: bool = True,
        credentials: bool = True,
    ) -> FetchResponse:
        """Выполнить HTTP-запрос через внутреннюю сессию.

        Единая точка входа для всех HTTP-запросов библиотеки.
        """
        # Единая точка входа в чужую библиотеку для удобства
        return await self.page.fetch(
            url=url,
            method=method,
            body=json_body,
            mode="cors",
            credentials="include" if credentials else "omit",
            timeout_ms=self.timeout_ms,
            referrer=self.MAIN_SITE_URL,
            headers={"Accept": "application/json, text/plain, */*"},
        )
