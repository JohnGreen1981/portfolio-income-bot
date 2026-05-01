# Income Bot

## Назначение

Очищенный портфельный репозиторий Telegram-бота для учета доходов и расходов.

Проект показывает прикладную AI automation: пользователь отправляет текст, голос или фото чека, GPT разбирает операцию, Python нормализует результат, бот записывает данные в Google Sheets и дает аналитику по выбранному периоду.

## Стек

- Python 3.11+
- aiogram 3
- OpenAI API: text parsing, receipt OCR, Whisper, analytics
- Google Sheets API через gspread
- pydantic-settings
- httpx

## Структура

```text
bot.py                   Telegram handlers, FSM, подтверждения и коррекция категорий
parser.py                парсинг доходов и транскрипция голоса
expense_parser.py        парсинг расходов, OCR чеков, analytics prompt
currency.py              курсы валют и конвертация
sheets.py                запись и чтение Google Sheets
setup_monthly_sheets.py  создание месячных сводных листов
config.py                настройки окружения
requirements.txt         зависимости
requirements-dev.txt     зависимости для тестов
.env.example             безопасный шаблон окружения
```

## Портфельная рамка

Проект представлен как AI-assisted finance automation prototype. В портфолио акцент на workflow, multi-modal input, prompt design, нормализацию данных, Google Sheets integration и UX подтверждения/исправления.

Не описывать проект как production fintech или бухгалтерскую систему.

## Данные

В публичный репозиторий не входят реальные `.env`, `.keys`, Google service account JSON, spreadsheet IDs, финансовые записи, приватные категории и deploy credentials.

Все клиенты, категории и примеры в public repo должны быть нейтральными demo-значениями.

## Правила

- Не коммитить `.env`, `.keys`, service account JSON, реальные финансовые записи, spreadsheet ID, Telegram ID, VPS пути и deploy credentials.
- `.env.example` должен содержать только placeholder-значения.
- При изменении Python-кода запускать `python3 -m py_compile *.py` и `pytest`.
- Перед GitHub push запускать проверку на секреты.
- `CLAUDE.md` должен оставаться ссылкой на `AGENTS.md`.
