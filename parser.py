import io
import json
from datetime import date
from difflib import get_close_matches

from openai import AsyncOpenAI

from config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)

# Словарь нормализации клиентов: транскрипции голоса -> правильное demo-название
CLIENT_ALIASES: dict[str, str] = {
    # Demo Client A
    "клиент а": "Demo Client A",
    "client a": "Demo Client A",
    "первый клиент": "Demo Client A",
    # Demo Client B
    "клиент б": "Demo Client B",
    "client b": "Demo Client B",
    "второй клиент": "Demo Client B",
    # Demo Client C
    "клиент ц": "Demo Client C",
    "client c": "Demo Client C",
    "третий клиент": "Demo Client C",
}


def normalize_client(client_name: str) -> str:
    """Нормализует имя клиента: сначала точное совпадение, затем fuzzy matching."""
    key = client_name.lower().strip()
    if key in CLIENT_ALIASES:
        return CLIENT_ALIASES[key]
    # Fuzzy fallback: ищем ближайший alias.
    matches = get_close_matches(key, CLIENT_ALIASES.keys(), n=1, cutoff=0.75)
    if matches:
        return CLIENT_ALIASES[matches[0]]
    return client_name


async def transcribe_voice(audio_bytes: bytes) -> str | None:
    try:
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "voice.ogg"
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ru",
        )
        return response.text
    except Exception:
        return None

SYSTEM_PROMPT = """Ты помощник для записи финансовых поступлений.
Сегодняшняя дата: {today}

Из текста пользователя извлеки:
- client: имя или название клиента (если не указан — "Неизвестно")
- amount: сумма в рублях (только число, без знаков валюты). Конвертируй словесные числа: «тысяч/тысячи/тыс/к» → ×1000, «миллион/млн» → ×1000000. Примеры: «45 тысяч» → 45000, «5к» → 5000, «1.5 млн» → 1500000
- description: краткое описание за что получена оплата
- date: дата поступления в формате YYYY-MM-DD (если не указана — сегодня)

## НОРМАЛИЗАЦИЯ КЛИЕНТОВ

Голосовой ввод часто искажает названия — всегда исправляй в правильное название:
- **Demo Client A**: «клиент а», «первый клиент», «client a» → Demo Client A
- **Demo Client B**: «клиент б», «второй клиент», «client b» → Demo Client B
- **Demo Client C**: «клиент ц», «третий клиент», «client c» → Demo Client C

Верни строго JSON: {{"client": "...", "amount": 12345.0, "description": "...", "date": "YYYY-MM-DD"}}

Если сумму невозможно определить — верни {{"error": "no_amount"}}"""


async def parse_income(text: str) -> dict | None:
    today = date.today().isoformat()

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(today=today),
            },
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    try:
        data = json.loads(response.choices[0].message.content)
        if "error" in data or not data.get("amount"):
            return None
        return {
            "client": normalize_client(data.get("client", "Неизвестно")),
            "amount": float(data["amount"]),
            "description": data.get("description", ""),
            "date": data.get("date", today),
            "raw": text,
        }
    except Exception:
        return None
