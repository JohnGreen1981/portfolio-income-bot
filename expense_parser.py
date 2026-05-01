import base64
import json
from datetime import date

from openai import AsyncOpenAI

from config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)

# Словарь нормализации магазинов: транскрипции голоса → правильное название
SHOP_ALIASES: dict[str, str] = {
    # Maxi
    "максе": "Maxi", "макси": "Maxi", "макс": "Maxi", "максы": "Maxi",
    "maxi": "Maxi",
    # Lidl
    "литл": "Lidl", "лидл": "Lidl", "лидель": "Lidl", "лидел": "Lidl",
    "lidl": "Lidl",
    # Aroma
    "аромат": "Aroma", "арома": "Aroma", "ароме": "Aroma", "аромы": "Aroma",
    "aroma": "Aroma",
    "domaća trgovina": "Aroma", "domaca trgovina": "Aroma",
}


def normalize_shop(shop: str) -> str:
    """Нормализует название магазина по словарю алиасов."""
    return SHOP_ALIASES.get(shop.lower().strip(), shop)

EXPENSE_SYSTEM_PROMPT = """Ты помощник для записи финансовых расходов.
Сегодняшняя дата: {today}

Из текста пользователя извлеки один или несколько расходов.
Для каждого расхода определи:
- category: категория из списка ниже
- amount: сумма (только число, без знаков валюты)
- currency: RUB/USD/EUR/RSD/GEL. "рубли/₽"→RUB, "доллары/$"→USD, "евро/€"→EUR, "динары/din"→RSD, "лари/₾"→GEL. Если валюта не указана явно — **RSD** (динар по умолчанию).
- shop: магазин или место (если не указан — "")
- description: краткое описание (2-4 слова)
- date: YYYY-MM-DD (если не указана — сегодня)

## КАТЕГОРИИ

**Продукты** — бакалея, хлеб, молоко, яйца, сыр, крупы, макароны, сладкое, консервы, замороженные полуфабрикаты.
  ❌ НЕ сюда: мясо/рыба/колбаса → «Мясо и рыба»; свежие овощи/фрукты → «Овощи и фрукты»; алкоголь → «Алкоголь»; кофейня → «Кафе/рестораны»

**Овощи и фрукты** — любые свежие или замороженные овощи, фрукты, зелень, грибы.

**Мясо и рыба** — говядина, свинина, курица, фарш, колбаса, сосиски, рыба, морепродукты, деликатесы.

**Бытовая химия** — порошок, средство для посуды, отбеливатель, туалетная бумага, мыло, шампунь, гель для душа, зубная паста, дезодорант, бытовая химия.
  ❌ НЕ сюда: декоративная косметика, уходовые процедуры → «Красота/уход»

**Аптека** — лекарства по рецепту и без, витамины, БАДы, таблетки, сиропы, пластыри, маски, экспресс-тесты, медицинские приборы (тонометр и т.п.).
  ❌ НЕ сюда: визит к врачу, анализы, клиника → «Медицина»

**Медицина** — приём врача, стоматолог, клиника, анализы, УЗИ, МРТ, медицинская страховка, операции.

**Алкоголь** — пиво, вино, водка, коньяк, виски, шампанское, сидр, ликёр.

**Табак** — сигареты (Winston, Marlboro, Parliament и др.), сигары, трубочный табак, вейп, электронные сигареты, жидкость для вейпа, IQOS, стики для IQOS (Terea, HEETS, Fiit), снюс, никотиновые пастилки.

**Напитки** — безалкогольные: вода, сок, газировка, энергетики, кофе/чай в магазине (не в кафе).

**Кафе/рестораны** — любая еда и напитки вне дома: кафе, ресторан, столовая, фастфуд, бургерная, суши, доставка еды (Яндекс.Еда, Delivery Club, Wolt и т.п.), кофейня.

**Транспорт** — такси (Яндекс, Uber, Bolt), метро, автобус, электричка, бензин/дизель, парковка, автосервис, каршеринг, авиабилеты, ж/д билеты.

**Одежда и обувь** — одежда, обувь, аксессуары, сумки, ремни, галстуки.

**Электроника** — телефоны, ноутбуки, планшеты, наушники, зарядки, кабели, аксессуары к технике, бытовая техника (телевизор, пылесос, холодильник и т.п.).

**Товары для дома** — текстиль (постельное, полотенца, шторы), посуда, декор, светильники, хранение, мелкая утварь для кухни/дома.

**Дом/ЖКХ** — аренда жилья, коммунальные услуги, электричество, газ, вода, ремонт, стройматериалы, инструменты.

**Связь/интернет** — мобильная связь, интернет (оператор, провайдер).
  ❌ НЕ сюда: Spotify, Netflix, ChatGPT и другие цифровые подписки → «Подписки»

**Подписки** — цифровые и сервисные подписки: Spotify, Netflix, YouTube Premium, ChatGPT, iCloud, VPN, Яндекс Плюс, Apple One, Adobe, GitHub Copilot и т.п.

**Семья/дети** — семейные расходы, детские кружки, секции, одежда, школьные и спортивные расходы, подарки детям.

**Долги** — выплаты по кредитам, ипотеке, займам; возврат личных долгов.

**Налоги** — налоговые платежи: НДФЛ, НДС, налог на имущество, транспортный налог, самозанятость, патент, штрафы налоговой.

**Развлечения** — кино, театр, концерт, музей, игры (Steam, PS, App Store), спорт/фитнес, хобби, книги для досуга, зоопарк, аквапарк.

**Красота/уход** — парикмахерская, барбершоп, маникюр, педикюр, массаж, spa, солярий, декоративная косметика, уходовая косметика для лица/тела.

**Образование** — онлайн-курсы, учебники, репетитор, языковые школы, сертификации, обучающие подписки.

**Прочее** — всё, что не подходит ни к одной из категорий выше.

## НОРМАЛИЗАЦИЯ МАГАЗИНОВ

Голосовой ввод часто искажает названия — всегда исправляй в правильное название:
- **Maxi**: «максе», «макси», «макс», «максы» → Maxi
- **Lidl**: «литл», «лидл», «лидель», «лидел» → Lidl
- **Aroma**: «аромат», «арома», «ароме», «аромы» → Aroma

## ПРАВИЛА

- Если в тексте несколько разных покупок — создай ОТДЕЛЬНЫЙ расход для каждой
- Если есть несколько товаров одной категории — объедини их в один расход
- Если сумму невозможно определить — верни {{"error": "no_amount"}}

Верни строго JSON:
{{"expenses": [{{"category": "...", "amount": 1234.0, "currency": "RUB", "shop": "...", "description": "...", "date": "YYYY-MM-DD"}}]}}"""

RECEIPT_SYSTEM_PROMPT = """Ты помощник для обработки фотографий кассовых чеков.
Сегодняшняя дата: {today}

## ШАГ 1: Считай данные чека
- Дата чека (если не видно — сегодня)
- Название магазина (если не видно — "")
- Итоговая сумма по чеку
- Валюта (₽→RUB, $→USD, €→EUR, din/RSD→RSD, ₾/GEL→GEL; если не видно — RUB)

## ШАГ 1б: Контекст магазина

Если магазин из списка — учитывай специализацию при категоризации:
- **Maxi, Lidl, Aroma, DIS, Roda, Univerexport, Domaća Trgovina** — продуктовый: типичны Продукты, Овощи и фрукты, Мясо и рыба, Напитки, Алкоголь
- **DM, Lilly** — дрогерия: типичны Бытовая химия, Аптека, Красота/уход (кремы, косметика → Красота/уход, НЕ Бытовая химия)
- **Tehnomanija, Gigatron** — электроника: типичны Электроника, Прочее
- **Шанхайска Робна Кућа** — универмаг: типичны Товары для дома, Одежда и обувь, Прочее

## ШАГ 2: Для КАЖДОЙ позиции определи категорию

Категории (в скобках — сербские названия для помощи):
- **Продукты** — хлеб (hleb, vekna), молоко (mleko), яйца (jaje), сыр (sir), йогурт (jogurt), сметана (pavlaka), масло (maslac, ulje), сахар (secer), мука (brasno), крупы, макароны, майонез (majonez), кетчуп, консервы, сладкое
- **Овощи и фрукты** — любые овощи и фрукты: paradajz, krastavac, paprika, krompir, luk, jabuka, banana, grozde и др.
- **Мясо и рыба** — мясо, птица, рыба, колбаса: piletina, svinjetina, govedina, kobasica, hrenovka, sunka, riba, losos и др.
- **Бытовая химия** — порошок, средства для уборки, туалетная бумага, шампунь, мыло
- **Аптека** — лекарства, витамины, медтовары
- **Алкоголь** — пиво (pivo), вино (vino), ракия (rakija), сидр (cider), водка, коньяк (konjak)
  ❌ НЕ путать с соками и водой → они «Напитки»
- **Табак** — сигареты, вейп, IQOS, стики (Terea, HEETS, Fiit), снюс
- **Напитки** — вода (voda), сок (sok), газировка (bezalkoholno), кофе в пачке
- **Электроника** — телефоны, ноутбуки, планшеты, наушники, зарядки, кабели, аксессуары к технике, бытовая техника (телевизор, пылесос и т.п.)
- **Товары для дома** — текстиль (постельное, полотенца, шторы), посуда, декор, светильники, хранение, мелкая утварь
- **Одежда и обувь** — одежда, обувь, сумки, ремни, аксессуары (не для техники)
- **Красота/уход** — кремы, косметика, уход за кожей/волосами
- **Прочее** — всё остальное (пакеты kesa, батарейки и т.п.)

⚠️ ВАЖНО: Terea, HEETS, FIIT, IQOS — всегда «Табак». Pivo, cider, rakija, vino — всегда «Алкоголь», НЕ «Напитки».

## ШАГ 3: Верни КАЖДУЮ позицию чека отдельно

НЕ группируй. Каждая строка чека = отдельный объект. Цена = сумма этой строки в чеке.
Если одна позиция встречается несколько раз — добавь её столько раз, сколько она есть в чеке.

Верни строго JSON:
{{
  "shop": "название магазина или пустая строка",
  "date": "YYYY-MM-DD",
  "currency": "RSD",
  "total_on_receipt": 514.99,
  "items": [
    {{"name": "Deterdžent", "amount": 1242.99, "category": "Бытовая химия"}},
    {{"name": "Zaječarsko pivo", "amount": 299.96, "category": "Алкоголь"}},
    {{"name": "Soja sos", "amount": 127.99, "category": "Продукты"}}
  ]
}}"""

ANALYTICS_SYSTEM_PROMPT = """Ты финансовый аналитик-ассистент. Отвечай на вопросы пользователя о его финансах.

Период анализа: {period}
Сегодня: {today}

ДОХОДЫ (итого {income_total:,.0f} ₽):
{income_data}

РАСХОДЫ (итого {expense_total:,.0f} ₽):
{expense_data}

Используй Markdown (жирный, курсив) и эмодзи. Будь лаконичен и конкретен.
Если пользователь просит изменить период — предложи выбрать его из кнопок меню."""


async def parse_expense_text(text: str) -> list[dict] | None:
    today = date.today().isoformat()
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": EXPENSE_SYSTEM_PROMPT.format(today=today)},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    try:
        data = json.loads(response.choices[0].message.content)
        if "error" in data or not data.get("expenses"):
            return None
        result = []
        for e in data["expenses"]:
            if not e.get("amount"):
                continue
            result.append({
                "category": e.get("category", "Прочее"),
                "amount": float(e["amount"]),
                "currency": e.get("currency", "RSD").upper(),
                "shop": normalize_shop(e.get("shop", "")),
                "description": e.get("description", ""),
                "date": e.get("date", today),
                "raw": text,
            })
        return result or None
    except Exception:
        return None


TOBACCO_KEYWORDS = {"terea", "heets", "fiit", "iqos", "marlboro", "winston", "parliament", "bond", "vogue", "dunhill"}

ALCOHOL_KEYWORDS = {
    "pivo", "beer", "kronenbourg", "heineken", "carlsberg", "stella", "budweiser",
    "corona", "beck", "pilsner", "lager", "weiss", "blanc",
    "cider", "somersby", "strongbow",
    "vino", "wine", "prosecco", "champagne",
    "vodka", "whisky", "whiskey", "bourbon", "cognac", "konjak", "rakija",
    "gin", "rum", "tequila", "brandy", "liqueur",
}
ALCOHOL_EXCEPTIONS = {"vinograd", "vinegar", "weinstein"}

MEAT_KEYWORDS = {
    "piletina", "pile", "pileći", "svinjetina", "junetina", "govedina", "jagnjetina",
    "mleveno", "file", "but", "krilca", "batak",
    "kobasica", "hrenovka", "slanina", "salama", "sunka", "prsuta", "kulen",
    "riba", "losos", "tuna", "skusa", "sardina", "skamp", "lignja",
}
MEAT_EXCEPTIONS = {"ribizla"}  # ribizla = смородина

VEGETABLE_KEYWORDS = {
    "paradajz", "krastavac", "paprika", "kupus", "luk", "krompir", "sargarepa",
    "brokoli", "karfiol", "tikva", "spanac", "praziluk", "rotkva", "cvekla",
    "jabuka", "banana", "pomorandza", "mandarina", "limun", "grejpfrut",
    "grozde", "jagoda", "malina", "borovnica", "tresnja", "sljiva", "breskva",
    "lubenica", "dinja", "ananas", "kivi",
}


def _merge_into_category(categories: list[dict], target_cat: str, items: list, amount: float):
    """Добавляет items/amount в существующую категорию или создаёт новую."""
    for c in categories:
        if c["category"] == target_cat:
            c["amount"] = c.get("amount", 0) + amount
            c["items"].extend(items)
            return
    categories.append({"category": target_cat, "amount": amount, "items": items})


def _is_keyword_match(item_lower: str, keywords: set, exceptions: set = frozenset()) -> bool:
    if any(ex in item_lower for ex in exceptions):
        return False
    return any(kw in item_lower for kw in keywords)


_FIXES = [
    ("Табак",           TOBACCO_KEYWORDS,    frozenset()),
    ("Алкоголь",        ALCOHOL_KEYWORDS,    ALCOHOL_EXCEPTIONS),
    ("Мясо и рыба",     MEAT_KEYWORDS,       MEAT_EXCEPTIONS),
    ("Овощи и фрукты",  VEGETABLE_KEYWORDS,  frozenset()),
]


def _fix_item_category(item_name: str, category: str) -> str:
    """Исправляет категорию одной позиции по словарям ключевых слов."""
    item_lower = item_name.lower()
    for target, keywords, exceptions in _FIXES:
        if _is_keyword_match(item_lower, keywords, exceptions):
            return target
    return category


def _group_items_to_categories(items: list[dict]) -> list[dict]:
    """Группирует позиции чека по категориям и суммирует суммы."""
    groups: dict[str, dict] = {}
    for item in items:
        cat = _fix_item_category(item.get("name", ""), item.get("category", "Прочее"))
        amt = float(item.get("amount", 0))
        if amt <= 0:
            continue
        if cat not in groups:
            groups[cat] = {"amount": 0.0, "items": []}
        groups[cat]["amount"] += amt
        groups[cat]["items"].append(item.get("name", ""))
    return [
        {"category": cat, "amount": round(info["amount"], 2), "items": info["items"]}
        for cat, info in groups.items()
    ]


async def parse_receipt_image(image_bytes: bytes) -> dict | None:
    today = date.today().isoformat()
    b64 = base64.b64encode(image_bytes).decode()
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": RECEIPT_SYSTEM_PROMPT.format(today=today),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=2000,
    )
    try:
        data = json.loads(response.choices[0].message.content)
        if "items" in data:
            data["categories"] = _group_items_to_categories(data["items"])
        return data
    except Exception:
        return None


def _build_analytics_context(
    income_records: list[dict],
    expense_records: list[dict],
    period_label: str,
) -> str:
    """Формирует system prompt с финансовыми данными для аналитик-чата."""
    income_total = sum(r["amount"] for r in income_records)
    expense_total = sum(r["amount"] for r in expense_records)

    income_lines = []
    for r in income_records:
        line = f"  {r['date']} | {r['client']} | {r['amount']:,.0f} ₽"
        if r.get("description"):
            line += f" | {r['description']}"
        income_lines.append(line)

    expense_lines = []
    for r in expense_records:
        line = f"  {r['date']} | {r['category']}"
        if r.get("shop"):
            line += f" ({r['shop']})"
        line += f" | {r['amount']:,.0f} ₽"
        expense_lines.append(line)

    return ANALYTICS_SYSTEM_PROMPT.format(
        period=period_label,
        today=date.today().isoformat(),
        income_total=income_total,
        expense_total=expense_total,
        income_data="\n".join(income_lines) or "нет данных",
        expense_data="\n".join(expense_lines) or "нет данных",
    )


async def chat_analytics(
    history: list[dict],
    income_records: list[dict],
    expense_records: list[dict],
    period_label: str,
) -> str:
    """Чат с финансовым аналитиком. history — список {"role": ..., "content": ...}."""
    if not income_records and not expense_records:
        return f"За период «{period_label}» нет данных для анализа."

    system_prompt = _build_analytics_context(income_records, expense_records, period_label)

    # Ограничиваем историю последними 20 сообщениями (10 обменов)
    recent_history = history[-20:] if len(history) > 20 else history

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}] + recent_history,
        temperature=0.3,
        max_tokens=1000,
    )
    return response.choices[0].message.content
