# Income Bot

Telegram-бот для учета доходов и расходов: текст, голос, фото чека, Google Sheets и AI-аналитика.

Это очищенная портфельная версия. В репозитории нет production `.env`, `.keys`, Google service account JSON, spreadsheet IDs, финансовых записей, приватных категорий и VPS-доступов.

## Что показывает проект

- AI parsing свободного финансового ввода.
- Распознавание чеков по фото и группировку позиций по категориям.
- Голосовой, текстовый и фото workflow в Telegram.
- Мультивалютность и конвертацию в рубли.
- Google Sheets integration: доходы, расходы, месячные сводки.
- UX подтверждения и ручной коррекции категории.
- AI-аналитику по периоду: сегодня, неделя, месяц, год.
- AI-assisted development: постановка workflow, prompt design, интеграции, ручная проверка и очистка для публикации.

## Пользовательский сценарий

1. Пользователь выбирает режим: доходы, расходы или аналитика.
2. В доходах бот принимает текст/голос, GPT выделяет клиента, сумму, дату и описание.
3. В расходах бот принимает текст/голос/фото чека, GPT выделяет сумму, валюту, магазин, категорию и позиции.
4. Бот показывает preview и дает подтвердить или исправить категорию.
5. Запись попадает в Google Sheets.
6. В аналитике бот загружает данные за период и отвечает на вопросы по финансам.

## Стек

- Python 3.11+
- aiogram 3
- OpenAI API: GPT parsing, receipt OCR, Whisper, analytics
- Google Sheets API через gspread
- pydantic-settings
- httpx

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

## Проверка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Тесты в clean repo используют только синтетические данные и не обращаются к OpenAI или Google Sheets.

Нужные переменные окружения:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
GOOGLE_SPREADSHEET_ID=your_google_spreadsheet_id
GOOGLE_CREDENTIALS_JSON=credentials.example.json
ALLOWED_USER_ID=123456789
```

Google service account JSON не входит в репозиторий. Для реального запуска нужно создать сервисный аккаунт, включить Google Sheets API / Google Drive API и расшарить таблицу на email сервисного аккаунта.

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
```

## Безопасность и данные

- Не коммитить `.env`, `.keys`, service account JSON, spreadsheet ID, реальные финансовые записи, Telegram ID и VPS-доступы.
- В публичной версии клиенты заменены на `Demo Client A/B/C`.
- Персональные категории заменены на нейтральные demo-категории.
- GPT может ошибаться в суммах и категориях; поэтому в workflow есть preview, подтверждение и ручная коррекция.

## Портфельная рамка

Проект представлен как AI-assisted finance automation prototype. Фокус: прикладной workflow, multi-modal input, prompt design, нормализация данных, Google Sheets integration и UX контроля результата, а не production fintech или бухгалтерская система.
