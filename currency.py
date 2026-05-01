"""
Курсы валют от ЦБ РФ с дневным кешированием.
Поддерживаемые валюты: RUB, USD, EUR, RSD (динар), GEL (лари)
"""
from datetime import date
from xml.etree import ElementTree

import httpx

# Дневной кеш: {date: {code: rate_per_1_unit_in_rub}}
_cache: dict = {"date": None, "rates": {}}

# Запасные курсы на случай недоступности ЦБ
_FALLBACK_RATES: dict[str, float] = {
    "RUB": 1.0,
    "USD": 92.0,
    "EUR": 100.0,
    "RSD": 0.85,
    "GEL": 34.0,
}

CURRENCY_SYMBOLS: dict[str, str] = {
    "RUB": "₽",
    "USD": "$",
    "EUR": "€",
    "RSD": "din",
    "GEL": "₾",
}


async def get_rates() -> dict[str, float]:
    """Возвращает курсы валют к рублю (1 единица валюты = X рублей)."""
    today = date.today()
    if _cache["date"] == today and _cache["rates"]:
        return _cache["rates"]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("https://www.cbr.ru/scripts/XML_daily.asp")
        root = ElementTree.fromstring(response.text)
        rates: dict[str, float] = {"RUB": 1.0}
        for valute in root.findall("Valute"):
            code = valute.find("CharCode").text
            nominal = int(valute.find("Nominal").text)
            value = float(valute.find("Value").text.replace(",", "."))
            rates[code] = value / nominal
        _cache["date"] = today
        _cache["rates"] = rates
        return rates
    except Exception:
        return _cache["rates"] or _FALLBACK_RATES


async def to_rub(amount: float, currency: str) -> tuple[float, float]:
    """
    Конвертирует сумму в рубли.
    Возвращает (сумма_в_рублях, курс).
    """
    if currency == "RUB":
        return round(amount, 2), 1.0
    rates = await get_rates()
    rate = rates.get(currency, _FALLBACK_RATES.get(currency, 1.0))
    return round(amount * rate, 2), round(rate, 4)


def format_amount(amount: float, currency: str) -> str:
    """«1 500 $» или «1 500 ₽». Для EUR/USD/GEL показывает центы если есть."""
    symbol = CURRENCY_SYMBOLS.get(currency, currency)
    if currency in ("RUB", "RSD"):
        return f"{amount:,.0f} {symbol}"
    # EUR, USD, GEL — показываем 2 знака только если есть дробная часть
    if amount == int(amount):
        return f"{amount:,.0f} {symbol}"
    return f"{amount:,.2f} {symbol}"


def format_amount_with_rub(amount_orig: float, currency: str, amount_rub: float) -> str:
    """«50,49 $ (4 645 ₽)» или просто «4 600 ₽» если уже рубли"""
    if currency == "RUB":
        return f"{amount_rub:,.0f} ₽"
    return f"{format_amount(amount_orig, currency)} ({amount_rub:,.0f} ₽)"
