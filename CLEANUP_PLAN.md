# План очистки

- [ ] Убедиться, что ключи из локальных рабочих файлов ротированы до GitHub-публикации.
- [x] Перенести только bot source files, README, requirements и безопасные public docs.
- [x] Исключить `.keys`, service account JSON, local `.env`, финансовые данные, backups, deploy scripts и caches.
- [x] Заменить реальные клиентские alias на demo clients.
- [x] Заменить персональные категории на нейтральные demo-категории.
- [x] Создать безопасный `.env.example`.
- [x] Добавить публичные `AGENTS.md` / `CLAUDE.md`.
- [x] Добавить tests/demo examples с синтетическими финансовыми записями.
- [x] Запустить tests/syntax check (`2 passed`; `python3 -m py_compile` пройден).
- [x] Запустить проверку на секреты перед первой публикацией в GitHub.
