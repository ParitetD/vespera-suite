# Vespera Search Suite

Локальный OSINT-инструмент: единая панель для поиска по открытым источникам
(username/ник, email, телефон, соцсети, фото, метаданные файлов).

Технологический стек: **Python 3.11+ / FastAPI / httpx / pydantic / SQLite**.

## Установка

```bash
# 1. Зависимости Python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Для модуля метаданных (проверка наличия exiftool)
sudo apt install exiftool

# 3. Конфигурация (все ключи опциональны — graceful degradation)
cp .env.example .env
# Отредактируйте .env (HIBP_API_KEY, VK_ACCESS_TOKEN и др.)
```

## Запуск

```bash
./run.sh
# или:
source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Откройте http://localhost:8000 — тёмная тема по умолчанию.

Примеры запросов:

```bash
curl -N "http://localhost:8000/api/search?type=username&value=some_username"
curl -s "http://localhost:8000/api/search?type=email&value=user@example.com" | jq .
curl -s "http://localhost:8000/api/history?limit=10"
```

`GET /api/search` — SSE-поток (живые логи всех модулей + финальный JSON `{'type':'result', ...}`).
`POST /api/search` — синхронный JSON-ответ.
`GET /api/health` — `{"status": "ok", "modules": [...]}` (имена активных модулей).
`GET /api/modules` — список модулей: имя + поддерживаемые типы запросов (`username`, `email`, `phone`, `social`, `photo`, `metadata`, `file`).
`GET /api/history?limit=50` — история поисков (`limit` ограничен 500; отрицательный — 0).
`GET /api/history/{id}` — один результат (404, если не найден).
`DELETE /api/history` — очистить всю историю: `{"deleted": N}`.

**Кэш:** оба варианта `GET/POST /api/search` сначала ищут результат в SQLite-кэше
(та же ключевая строка `type:value:modules`). Кэш живёт 10 минут — результаты поиска динамичны.

## Архитектура

```
vespera-suite/
├── app/
│   ├── main.py               # точка входа FastAPI
│   ├── config.py             # pydantic-settings (.env)
│   ├── api/
│   │   ├── routes.py         # REST + SSE-поиск + история
│   │   └── schemas.py        # валидация запросов
│   ├── core/
│   │   ├── orchestrator.py   # фильтр модулей → параллельный запуск → агрегация
│   │   ├── aggregator.py     # нормализация в единый отчёт + summary
│   │   └── rate_limiter.py   # единый per-domain token bucket
│   ├── modules/
│   │   ├── base.py           # BaseModule + safe_search (изоляция отказов)
│   │   ├── username_module.py   # WhatsMyName (691 сайт) + прямые проверки
│   │   ├── email_module.py      # HIBP, hacked-emails, ghostproject, MX
│   │   ├── phone_module.py      # phonenumbers, phonenumber.to, Truecaller, numverify
│   │   ├── social_module.py     # VK API, Яндекс People, Facebook, Twitter
│   │   ├── photo_module.py      # Yandex Images, TinEye, Search4faces
│   │   └── metadata_module.py   # exiftool, Pillow, python-docx, PyPDF2
│   ├── utils/
│   │   ├── http_client.py    # единый AsyncClient (UA-ротация, retry)
│   │   ├── normalizer.py     # единая схема результата
│   │   └── validators.py     # regex/phonenumbers-валидация
│   ├── db/                   # SQLAlchemy: история запросов + кэш
│   └── static/               # UI (Vanilla JS + Tailwind CDN)
├── data/
│   ├── wmn-data.json         # WhatsMyName dataset (vendored, 691 сайт)
│   └── vespera.db            # SQLite-база (генерируется)
├── tests/                    # pytest: orchestrator + username + email
├── .env.example              # шаблон конфигурации
├── requirements.txt
└── run.sh
```

## Добавление нового модуля

1. Наследуйтесь от `BaseModule` (`app/modules/base.py`), определите
   `name`, `supported_inputs`.
2. Реализуйте `async def search(self, query) -> List[dict]` — возвращайте
   нормализованные результаты (`app/utils/normalizer.norm`).
3. Добавьте в `app/core/orchestrator.py::get_modules()`.
4. Всё остальное (rate-limit, timeout, try/except, логирование) берётся
   из базовой части.

## Конфигурация (.env)

```
HIBP_API_KEY=          # HaveIBeenPwned API (утечки по email)
SERPAPI_KEY=           # SerpAPI (запас, если понадобятся)
VK_ACCESS_TOKEN=       # VK API users.search (профили по ФИО)
NUMVERIFY_API_KEY=     # numverify (детализация по номеру телефона)
PROXY_URL=             # http://user:pass@host:port
RATE_LIMIT_DEFAULT=1.0 # req/с на домен по умолчанию
REQUEST_TIMEOUT=30.0
LOG_LEVEL=INFO
DB_PATH=./data/vespera.db
HOST=0.0.0.0
PORT=8000
```

## Тесты

```bash
source .venv/bin/activate
pip install -q -r requirements.txt && pip install -q pytest pytest-asyncio
pytest tests/ -v
```

Пример ожидаемого вывода:

```
tests/test_orchestrator.py ...   [100%]  3 passed
tests/test_username_module.py .. [100%]  3 passed
tests/test_email_module.py ...... [100%]  5 passed
```

## Пример запуска (ожидаемый вывод)

```
$ ./run.sh
INFO:     Uvicorn running on http://0.0.0.0:8000
```

```
$ curl -s http://localhost:8000/api/health
{"status": "ok"}
```

---

## Предупреждение о законности (читайте внимание)

Vespera Search Suite — **инструмент для поиска информации по открытым источникам**.
Используйте его в рамках закона:

- **Доксинг запрещён.** Поиск по чужим данным для преследования, угроз или прочих вредоносных целей противоречит этому README и законодательству.
- **Не автоматизируйте действия, нарушающие ToS:** приложения Truecaller/GetContact/NumBuster/Skype/Telegram/WhatsApp — только инструкции в UI, автоматизация там запрещена.
- **Уважайте приватность:** не используйте данные для контактов, вымогательства, социальных инженерных атак без согласия.
- **Юридическая ответственность:** настоящий пользователь несёт ответственность за использование результатов поиска.
