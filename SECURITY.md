# Безопасность

Не коммитить OpenAI keys, Telegram tokens, Google service account JSON, spreadsheet IDs, финансовые записи, персональные категории расходов, реальные клиентские alias и deployment credentials.

Перед публикацией проверить:

- `.env.example` содержит только placeholder-значения;
- `.keys`, `.env`, service account JSON и backup-файлы не попали в git;
- в коде нет реальных client names, spreadsheet IDs, Telegram IDs и VPS paths;
- secret scan не находит токены и ключи.
