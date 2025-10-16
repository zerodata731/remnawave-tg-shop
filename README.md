# Telegram-бот для продажи подписок Remnawave

Этот Telegram-бот предназначен для автоматизации продажи и управления подписками для панели **Remnawave**. Он интегрируется с API Remnawave для управления пользователями и подписками, а также использует различные платежные системы для приема платежей.

## ✨ Ключевые возможности

### Для пользователей:
-   **Регистрация и выбор языка:** Поддержка русского и английского языков.
-   **Просмотр подписки:** Пользователи могут видеть статус своей подписки, дату окончания и ссылку на конфигурацию.
-   **Пробная подписка:** Система пробных подписок для новых пользователей (активируется вручную по кнопке).
-   **Промокоды:** Возможность применять промокоды для получения скидок или бонусных дней.
-   **Реферальная программа:** Пользователи могут приглашать друзей и получать за это бонусные дни подписки.
-   **Оплата:** Поддержка оплаты через YooKassa, FreeKassa (REST API), CryptoPay, Telegram Stars и Tribute.

### Для администраторов:
-   **Защищенная админ-панель:** Доступ только для администраторов, указанных в `ADMIN_IDS`.
-   **Статистика:** Просмотр статистики использования бота (общее количество пользователей, забаненные, активные подписки), недавние платежи и статус синхронизации с панелью.
-   **Управление пользователями:** Блокировка/разблокировка пользователей, просмотр списка забаненных и детальной информации о пользователе.
-   **Рассылка:** Отправка сообщений всем пользователям, пользователям с активной или истекшей подпиской.
-   **Управление промокодами:** Создание и просмотр промокодов.
-   **Синхронизация с панелью:** Ручной запуск синхронизации пользователей и подписок с панелью Remnawave.
-   **Логи действий:** Просмотр логов всех действий пользователей.

## 🚀 Технологии

-   **Python 3.11**
-   **Aiogram 3.x:** Асинхронный фреймворк для Telegram ботов.
-   **aiohttp:** Для запуска веб-сервера (вебхуки).
-   **SQLAlchemy 2.x & asyncpg:** Асинхронная работа с базой данных PostgreSQL.
-   **YooKassa, FreeKassa API, aiocryptopay:** Интеграции с платежными системами.
-   **Pydantic:** Для управления настройками из `.env` файла.
-   **Docker & Docker Compose:** Для контейнеризации и развертывания.

## ⚙️ Установка и запуск

### Предварительные требования

-   Установленные Docker и Docker Compose.
-   Рабочая панель Remnawave.
-   Токен Telegram-бота.
-   Данные для подключения к платежным системам (YooKassa, CryptoPay и т.д.).

### Шаги установки

1.  **Клонируйте репозиторий:**
    ```bash
    git clone https://github.com/machka-pasla/remnawave-tg-shop
    cd remnawave-tg-shop
    ```

2.  **Создайте и настройте файл `.env`:**
    Скопируйте `env.example` в `.env` и заполните своими данными.
    ```bash
    cp .env.example .env
    nano .env 
    ```
    Ниже перечислены ключевые переменные.

    <details>
    <summary><b>Основные настройки</b></summary>

    | Переменная | Описание | Пример |
    | --- | --- | --- |
    | `BOT_TOKEN` | **Обязательно.** Токен вашего Telegram-бота. | `1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
    | `ADMIN_IDS` | **Обязательно.** ID администраторов в Telegram через запятую. | `12345678,98765432` |
    | `DEFAULT_LANGUAGE` | Язык по умолчанию для новых пользователей. | `ru` |
    | `SUPPORT_LINK` | (Опционально) Ссылка на поддержку. | `https://t.me/your_support` |
    | `SUBSCRIPTION_MINI_APP_URL` | (Опционально) URL Mini App для показа подписки. | `https://t.me/your_bot/app` |
    </details>

    <details>
    <summary><b>Настройки платежей и вебхуков</b></summary>

    | Переменная | Описание |
    | --- | --- |
    | `WEBHOOK_BASE_URL`| **Обязательно.** Базовый URL для вебхуков, например `https://your.domain.com`. |
    | `WEB_SERVER_HOST` | Хост для веб-сервера. | `0.0.0.0` |
    | `WEB_SERVER_PORT` | Порт для веб-сервера. | `8080` |
    | `YOOKASSA_ENABLED` | Включить/выключить YooKassa (`true`/`false`). |
    | `YOOKASSA_SHOP_ID` | ID вашего магазина в YooKassa. |
    | `YOOKASSA_SECRET_KEY`| Секретный ключ магазина YooKassa. |
    | `CRYPTOPAY_ENABLED` | Включить/выключить CryptoPay (`true`/`false`). |
    | `CRYPTOPAY_TOKEN` | Токен из вашего CryptoPay App. |
    | `FREEKASSA_ENABLED` | Включить/выключить FreeKassa (`true`/`false`). |
    | `FREEKASSA_MERCHANT_ID` | ID вашего магазина в FreeKassa. |
    | `FREEKASSA_API_KEY` | API-ключ для запросов к FreeKassa REST API. |
    | `FREEKASSA_SECOND_SECRET` | Секретное слово №2 — используется для проверки уведомлений от FreeKassa. |
    | `FREEKASSA_PAYMENT_URL` | (Опционально, legacy SCI) Базовый URL платёжной формы FreeKassa. По умолчанию `https://pay.freekassa.ru/`. |
    | `FREEKASSA_PAYMENT_IP` | Внешний IP вашего сервера, который будет передаваться в запрос оплаты. |
    | `STARS_ENABLED` | Включить/выключить Telegram Stars (`true`/`false`). |
    | `TRIBUTE_ENABLED`| Включить/выключить Tribute (`true`/`false`). |
    </details>

    <details>
    <summary><b>Настройки подписок</b></summary>

    Для каждого периода (1, 3, 6, 12 месяцев) можно настроить доступность и цены:
    - `1_MONTH_ENABLED`: `true` или `false`
    - `RUB_PRICE_1_MONTH`: Цена в рублях
    - `STARS_PRICE_1_MONTH`: Цена в Telegram Stars
    - `TRIBUTE_LINK_1_MONTH`: Ссылка для оплаты через Tribute
    Аналогичные переменные есть для `3_MONTHS`, `6_MONTHS`, `12_MONTHS`.
    </details>

    <details>
    <summary><b>Настройки панели Remnawave</b></summary>
    
    | Переменная | Описание |
    | --- | --- |
    | `PANEL_API_URL` | URL API вашей панели Remnawave. |
    | `PANEL_API_KEY` | API ключ для доступа к панели. |
    | `PANEL_WEBHOOK_SECRET`| Секретный ключ для проверки вебхуков от панели. |
    | `USER_SQUAD_UUIDS` | ID отрядов для новых пользователей. |
    | `USER_TRAFFIC_LIMIT_GB`| Лимит трафика в ГБ (0 - безлимит). |
    </gidetails>

    <details>
    <summary><b>Настройки пробного периода</b></summary>

    | Переменная | Описание |
    | --- | --- |
    | `TRIAL_ENABLED` | Включить/выключить пробный период (`true`/`false`). |
    | `TRIAL_DURATION_DAYS`| Длительность пробного периода в днях. |
    | `TRIAL_TRAFFIC_LIMIT_GB`| Лимит трафика для пробного периода в ГБ. |
    </details>

3.  **Запустите контейнеры:**
    ```bash
    docker compose up -d
    ```
    Эта команда скачает образ и запустит сервис в фоновом режиме.

4.  **Настройка вебхуков (Обязательно):**
    Вебхуки являются **обязательным** компонентом для работы бота, так как они используются для получения уведомлений от платежных систем (YooKassa, FreeKassa, CryptoPay, Tribute) и панели Remnawave.

    Вам понадобится обратный прокси (например, Nginx) для обработки HTTPS-трафика и перенаправления запросов на контейнер с ботом.

    **Пути для перенаправления:**
    -   `https://<ваш_домен>/webhook/yookassa` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/yookassa`
    -   `https://<ваш_домен>/webhook/freekassa` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/freekassa`
    -   `https://<ваш_домен>/webhook/cryptopay` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/cryptopay`
    -   `https://<ваш_домен>/webhook/tribute` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/tribute`
    -   `https://<ваш_домен>/webhook/panel` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/panel`
    -   **Для Telegram:** Бот автоматически установит вебхук, если в `.env` указан `WEBHOOK_BASE_URL`. Путь будет `https://<ваш_домен>/<BOT_TOKEN>`.

    Где `remnawave-tg-shop` — это имя сервиса из `docker-compose.yml`, а `<WEB_SERVER_PORT>` — порт, указанный в `.env`.

5.  **Просмотр логов:**
    ```bash
    docker compose logs -f remnawave-tg-shop
    ```

## 🐳 Docker

Файлы `Dockerfile` и `docker-compose.yml` уже настроены для сборки и запуска проекта. `docker-compose.yml` использует готовый образ с GitHub Container Registry, но вы можете раскомментировать `build: .` для локальной сборки.

## 📁 Структура проекта

```
.
├── bot/
│   ├── filters/          # Пользовательские фильтры Aiogram
│   ├── handlers/         # Обработчики сообщений и колбэков
│   ├── keyboards/        # Клавиатуры
│   ├── middlewares/      # Промежуточные слои (i18n, проверка бана)
│   ├── services/         # Бизнес-логика (платежи, API панели)
│   ├── states/           # Состояния FSM
│   └── main_bot.py       # Основная логика бота
├── config/
│   └── settings.py       # Настройки Pydantic
├── db/
│   ├── dal/              # Слой доступа к данным (DAL)
│   ├── database_setup.py # Настройка БД
│   └── models.py         # Модели SQLAlchemy
├── locales/              # Файлы локализации (ru, en)
├── .env.example          # Пример файла с переменными окружения
├── Dockerfile            # Инструкции для сборки Docker-образа
├── docker-compose.yml    # Файл для оркестрации контейнеров
├── requirements.txt      # Зависимости Python
└── main.py               # Точка входа в приложение
```

## 🔮 Планы на будущее

-   Расширенные типы промокодов (например, скидки в процентах).

## ❤️ Поддержка
- Карты РФ и зарубежные: [Tribute](https://t.me/tribute/app?startapp=dqdg)
- Crypto: `USDT TRC-20 TT3SqBbfU4vYm6SUwUVNZsy278m2xbM4GE`
