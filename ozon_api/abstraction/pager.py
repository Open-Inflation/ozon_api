from __future__ import annotations

import html
import json
import re
from typing import Any, TypeVar
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .product_card import render_product_card

T = TypeVar("T", bound=BaseModel)


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        if value and value[0] in "{[":
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
    return value


def _clean_text(value: Any) -> Any:
    if isinstance(value, str):
        return html.unescape(value).strip()
    return value


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)

    return result


def _parse_rating(texts: list[str]) -> float | None:
    for text in texts:
        normalized = text.replace(",", ".").strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", normalized):
            try:
                return float(normalized)
            except ValueError:
                pass
    return None


def _parse_reviews(texts: list[str]) -> int | None:
    for text in texts:
        low = text.lower()
        if "отзыв" in low or "review" in low:
            digits = re.sub(r"[^\d]", "", text)
            if digits:
                return int(digits)
    return None


def _parse_price_text(value: Any) -> tuple[int | float | None, str | None] | None:
    if not isinstance(value, str):
        return None

    cleaned = _clean_text(value)
    if not isinstance(cleaned, str) or not cleaned:
        return None

    normalized = re.sub(r"\s+", "", cleaned)
    match = re.search(r"(\d+(?:[.,]\d+)?)([^\d.,]+)?", normalized)
    if not match:
        return None

    raw_value = match.group(1).replace(",", ".")
    if "." in raw_value:
        try:
            parsed_value: int | float = float(raw_value)
        except ValueError:
            return None
        if parsed_value.is_integer():
            parsed_value = int(parsed_value)
    else:
        try:
            parsed_value = int(raw_value)
        except ValueError:
            return None

    currency = match.group(2) or None
    return parsed_value, currency


class OzonBaseModel(BaseModel):
    """Базовая модель Ozon, игнорирующая лишние поля."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )


class WidgetPlaceholder(OzonBaseModel):
    """Плейсхолдер layout с вложенными виджетами."""

    name: str
    widgets: list["LayoutWidget"] = Field(default_factory=list)


class LayoutWidget(OzonBaseModel):
    """Упрощённый виджет из layout, достаточный для поиска нужного state."""

    component: str
    state_id: str | None = Field(default=None, alias="stateId")
    params: dict[str, Any] = Field(default_factory=dict)
    placeholders: list[WidgetPlaceholder] = Field(default_factory=list)

    @field_validator("params", mode="before")
    @classmethod
    def parse_params(cls, value: Any) -> dict[str, Any]:
        value = _maybe_json(value)
        return value if isinstance(value, dict) else {}


class Action(OzonBaseModel):
    """Действие виджета или карточки товара."""

    link: str | None = None


class PriceLine(OzonBaseModel):
    """Отдельная строка цены."""

    text: str
    text_style: str | None = Field(default=None, alias="textStyle")

    @field_validator("text", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> Any:
        return _clean_text(value)


class PriceValue(OzonBaseModel):
    """Нормализованная цена товара."""

    value: int | float | None = None
    currency: str | None = None

    @classmethod
    def from_text(cls, value: Any) -> "PriceValue" | None:
        parsed = _parse_price_text(value)
        if not parsed:
            return None
        amount, currency = parsed
        return cls(value=amount, currency=currency)


class PriceV2Data(OzonBaseModel):
    """Цена товара в карточке."""

    price: list[PriceLine] = Field(default_factory=list)
    discount: str | None = None

    @field_validator("discount", mode="before")
    @classmethod
    def clean_discount(cls, value: Any) -> Any:
        return _clean_text(value)

    @property
    def current_price(self) -> str | None:
        for item in self.price:
            if item.text_style == "PRICE":
                return item.text
        return self.price[0].text if self.price else None

    @property
    def original_price(self) -> str | None:
        for item in self.price:
            if item.text_style == "ORIGINAL_PRICE":
                return item.text
        return None


class TextAtomData(OzonBaseModel):
    """Текстовый блок карточки или текстового виджета."""

    text: str

    @field_validator("text", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> Any:
        return _clean_text(value)


class LabelTextData(OzonBaseModel):
    """Текст внутри labelListV2."""

    text: str | None = None

    @field_validator("text", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> Any:
        return _clean_text(value)


class LabelItem(OzonBaseModel):
    """Один элемент списка меток."""

    title: str | None = None
    text: LabelTextData | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: Any) -> Any:
        return _clean_text(value)

    def as_text(self) -> str | None:
        if self.title:
            return self.title
        if self.text and self.text.text:
            return self.text.text
        return None


class LabelListData(OzonBaseModel):
    """Список текстовых меток карточки."""

    items: list[LabelItem] = Field(default_factory=list)

    def texts(self) -> list[str]:
        return [text for item in self.items if (text := item.as_text())]


class Badge(OzonBaseModel):
    """Короткий бейдж карточки товара."""

    text: str | None = None

    @field_validator("text", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> Any:
        return _clean_text(value)


class RemoteImage(OzonBaseModel):
    """Ссылка на удалённое изображение."""

    link: str


class ImageBlock(OzonBaseModel):
    """Контейнер изображения внутри карточки."""

    image: RemoteImage | None = None


class TileImage(OzonBaseModel):
    """Изображения и бейджи карточки товара."""

    items: list[ImageBlock] = Field(default_factory=list)
    left_bottom_badge: Badge | None = Field(default=None, alias="leftBottomBadge")
    left_bottom_badge_v2: Badge | None = Field(default=None, alias="leftBottomBadgeV2")
    second_left_bottom_badge_v2: Badge | None = Field(
        default=None,
        alias="secondLeftBottomBadgeV2",
    )

    def image_url(self) -> str | None:
        for item in self.items:
            if item.image and item.image.link:
                return item.image.link
        return None

    def badges(self) -> list[str]:
        values = [
            self.left_bottom_badge.text if self.left_bottom_badge else None,
            self.left_bottom_badge_v2.text if self.left_bottom_badge_v2 else None,
            self.second_left_bottom_badge_v2.text if self.second_left_bottom_badge_v2 else None,
        ]
        return _dedupe_keep_order([value for value in values if value])


class ComponentBlock(OzonBaseModel):
    """Унифицированный блок состояния карточки или текстового виджета."""

    type: str
    id: str | None = None
    price_v2: PriceV2Data | None = Field(default=None, alias="priceV2")
    text_atom: TextAtomData | None = Field(default=None, alias="textAtom")
    label_list: LabelListData | None = Field(default=None, alias="labelList")
    label_list_v2: LabelListData | None = Field(default=None, alias="labelListV2")

    def texts(self) -> list[str]:
        result: list[str] = []

        if self.text_atom and self.text_atom.text:
            result.append(self.text_atom.text)

        if self.label_list:
            result.extend(self.label_list.texts())

        if self.label_list_v2:
            result.extend(self.label_list_v2.texts())

        return _dedupe_keep_order(result)


def _extract_title(blocks: list[ComponentBlock]) -> str | None:
    for block in blocks:
        if block.id == "name" and block.text_atom and block.text_atom.text:
            return block.text_atom.text

    for block in blocks:
        if block.text_atom and block.text_atom.text:
            return block.text_atom.text

    return None


def _extract_price(blocks: list[ComponentBlock]) -> PriceV2Data | None:
    for block in blocks:
        if block.price_v2:
            return block.price_v2
    return None


def _extract_label_texts(blocks: list[ComponentBlock]) -> list[str]:
    result: list[str] = []

    for block in blocks:
        if block.label_list:
            result.extend(block.label_list.texts())
        if block.label_list_v2:
            result.extend(block.label_list_v2.texts())

    return _dedupe_keep_order(result)


class ParsedProduct(OzonBaseModel):
    """Нормализованная карточка товара, одинаковая для разных товарных виджетов."""

    sku: int | None = None
    title: str | None = None
    url: str | None = None
    image_url: str | None = None
    price: PriceValue | None = None
    original_price: PriceValue | None = None
    discount: str | None = None
    rating: float | None = None
    reviews: int | None = None
    badges: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)

    @field_validator("price", "original_price", mode="before")
    @classmethod
    def parse_price(cls, value: Any) -> Any:
        if isinstance(value, PriceValue) or isinstance(value, dict) or value is None:
            return value
        return PriceValue.from_text(value)

    def render(self, *, index: int | None = None, card_width: int | None = None) -> str:
        return render_product_card(self, index=index, card_width=card_width)

    @classmethod
    def from_blocks(
        cls,
        *,
        sku: int | None,
        url: str | None,
        image_url: str | None,
        badges: list[str],
        blocks: list[ComponentBlock],
    ) -> "ParsedProduct":
        price = _extract_price(blocks)
        label_texts = _extract_label_texts(blocks)

        rating = _parse_rating(label_texts)
        reviews = _parse_reviews(label_texts)

        filtered_labels: list[str] = []
        for text in label_texts:
            low = text.lower()
            normalized = text.replace(",", ".").strip()

            if rating is not None and re.fullmatch(r"\d+(?:\.\d+)?", normalized):
                continue

            if "отзыв" in low or "review" in low:
                continue

            filtered_labels.append(text)

        return cls(
            sku=sku,
            title=_extract_title(blocks),
            url=url,
            image_url=image_url,
            price=PriceValue.from_text(price.current_price) if price else None,
            original_price=PriceValue.from_text(price.original_price) if price else None,
            discount=price.discount if price else None,
            rating=rating,
            reviews=reviews,
            badges=_dedupe_keep_order(badges),
            labels=_dedupe_keep_order(filtered_labels),
        )


class TileGridItem(OzonBaseModel):
    """Карточка товара из tileGridDesktop."""

    action: Action | None = None
    id: int | None = None
    sku: int | None = None
    main_state: list[ComponentBlock] = Field(default_factory=list, alias="mainState")
    tile_image: TileImage | None = Field(default=None, alias="tileImage")

    def to_product(self) -> ParsedProduct:
        return ParsedProduct.from_blocks(
            sku=self.sku or self.id,
            url=self.action.link if self.action else None,
            image_url=self.tile_image.image_url() if self.tile_image else None,
            badges=self.tile_image.badges() if self.tile_image else [],
            blocks=self.main_state,
        )


class TileGridDesktopState(OzonBaseModel):
    """Состояние виджета tileGridDesktop."""

    items: list[TileGridItem] = Field(default_factory=list)


class SkuGridProduct(OzonBaseModel):
    """Карточка товара из skuGrid."""

    action: Action | None = None
    link: str | None = None
    sku_id: int | None = Field(default=None, alias="skuId")
    state: list[ComponentBlock] = Field(default_factory=list)
    items: list[ImageBlock] = Field(default_factory=list)
    left_bottom_badge: Badge | None = Field(default=None, alias="leftBottomBadge")

    def image_url(self) -> str | None:
        for item in self.items:
            if item.image and item.image.link:
                return item.image.link
        return None

    def badges(self) -> list[str]:
        return [self.left_bottom_badge.text] if self.left_bottom_badge and self.left_bottom_badge.text else []

    def to_product(self) -> ParsedProduct:
        return ParsedProduct.from_blocks(
            sku=self.sku_id,
            url=(self.action.link if self.action and self.action.link else self.link),
            image_url=self.image_url(),
            badges=self.badges(),
            blocks=self.state,
        )


class SkuGridProductContainer(OzonBaseModel):
    """Контейнер товаров внутри skuGrid."""

    products: list[SkuGridProduct] = Field(default_factory=list)


class SkuGridState(OzonBaseModel):
    """Состояние виджета skuGrid."""

    product_container: SkuGridProductContainer = Field(
        default_factory=SkuGridProductContainer,
        alias="productContainer",
    )


class TextBlockState(OzonBaseModel):
    """Состояние текстового блока, полезное для детекта ошибок."""

    body: list[ComponentBlock] = Field(default_factory=list)

    def texts(self) -> list[str]:
        result: list[str] = []
        for block in self.body:
            result.extend(block.texts())
        return _dedupe_keep_order(result)


class OzonPage(OzonBaseModel):
    """Минимальная страница Ozon с layout и состояниями виджетов."""

    layout: list[LayoutWidget] = Field(default_factory=list)
    widget_states: dict[str, Any] = Field(default_factory=dict, alias="widgetStates")
    next_page: str | None = Field(default=None, alias="nextPage")

    @field_validator("widget_states", mode="before")
    @classmethod
    def parse_widget_states(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {key: _maybe_json(raw_value) for key, raw_value in value.items()}

    def iter_widgets(self) -> list[LayoutWidget]:
        result: list[LayoutWidget] = []

        def walk(widgets: list[LayoutWidget]) -> None:
            for widget in widgets:
                result.append(widget)
                for placeholder in widget.placeholders:
                    walk(placeholder.widgets)

        walk(self.layout)
        return result

    def state_as(self, state_id: str, model: type[T]) -> T:
        return model.model_validate(self.widget_states[state_id])

    def extract_products(self) -> list[ParsedProduct]:
        result: list[ParsedProduct] = []

        for widget in self.iter_widgets():
            if not widget.state_id:
                continue

            if widget.component == "tileGridDesktop":
                state = self.state_as(widget.state_id, TileGridDesktopState)
                result.extend(item.to_product() for item in state.items)

            elif widget.component == "skuGrid":
                state = self.state_as(widget.state_id, SkuGridState)
                result.extend(item.to_product() for item in state.product_container.products)

        return result

    def extract_error_messages(self) -> list[str]:
        result: list[str] = []

        for widget in self.iter_widgets():
            if widget.component != "textBlock" or not widget.state_id:
                continue

            state = self.state_as(widget.state_id, TextBlockState)
            result.extend(state.texts())

        return _dedupe_keep_order(result)


WidgetPlaceholder.model_rebuild()
LayoutWidget.model_rebuild()
