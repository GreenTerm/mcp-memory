from __future__ import annotations

import re
from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SUPPORTED_LANGUAGES = {"en", "ru"}


PHRASE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        "Project": "Проект",
        "Project ID": "ID проекта",
        "Project Root": "Папка проекта",
        "Write Mode": "Режим записи",
        "Running": "Запущен",
        "Offline": "Офлайн",
        "Open Workspace": "Открыть workspace",
        "Workspace Offline": "Workspace офлайн",
        "Workspace URL": "Ссылка на workspace",
        "Workspace HTTP server is responding.": "HTTP-сервер workspace отвечает.",
        "Workspace HTTP server is not running yet.": "HTTP-сервер workspace пока не запущен.",
        "Pick up your reverse-engineering workspace.": "Откройте нужное рабочее пространство реверс-инжиниринга.",
        "Every project stays local, searchable, and easy to reopen. This screen helps you find the right workspace and see whether it is already running.": "Каждый проект остаётся локальным, searchable и удобным для повторного открытия. Этот экран помогает быстро найти нужный workspace и понять, запущен ли он.",
        "Your project shelf is empty.": "Полка проектов пока пуста.",
        "Create the first workspace from CLI, then come back here to open it in the browser.": "Создайте первый workspace через CLI, а потом вернитесь сюда и откройте его в браузере.",
        "No registered projects yet": "Пока нет зарегистрированных проектов",
        "Once you create a project, it will appear here with a direct workspace link.": "После создания проекта он появится здесь с прямой ссылкой на workspace.",
        "Workspace Dashboard": "Панель workspace",
        "Project Snapshot": "Снимок проекта",
        "A calm overview of what is already in this workspace.": "Спокойный обзор того, что уже есть в этом workspace.",
        "Jump Back In": "Быстрый вход в работу",
        "Start broad, then narrow down only when you need to.": "Начните широко, а потом сузьте поиск только когда это действительно нужно.",
        "Search": "Поиск",
        "Search Workspace": "Поиск по workspace",
        "One search box, then small filters only when they help.": "Сначала одна строка поиска, затем небольшие фильтры только когда они помогают.",
        "Search across your project": "Ищите по всему проекту",
        "Try queries like main_handler, parser, helper_worker, or a tag such as parser.": "Попробуйте запросы вроде main_handler, parser, helper_worker или тег parser.",
        "No matches yet": "Совпадений пока нет",
        "Try a broader phrase, remove one filter, or search by tag only.": "Попробуйте более широкий запрос, уберите один фильтр или ищите только по тегу.",
        "Pending Changes": "Ожидающие изменения",
        "Pending change confirmed and applied.": "Ожидающее изменение подтверждено и применено.",
        "Pending change rejected.": "Ожидающее изменение отклонено.",
        "Change queued for confirmation.": "Изменение поставлено в очередь на подтверждение.",
        "Nothing is waiting right now": "Сейчас ничего не ожидает подтверждения",
        "New proposals will appear here when the project runs in confirm mode.": "Новые предложения появятся здесь, когда проект работает в режиме confirm.",
        "Review Proposals": "Проверка предложений",
        "Confirm only what you want persisted into the knowledge base.": "Подтверждайте только то, что действительно нужно сохранить в базе знаний.",
        "Audit Trail": "Журнал аудита",
        "No audit entries yet": "Записей аудита пока нет",
        "Once records are created or confirmed, the audit trail will appear here.": "Когда записи будут созданы или подтверждены, здесь появится журнал аудита.",
        "Project Audit": "Аудит проекта",
        "Review recent writes, confirmations, and provenance without leaving the workspace.": "Смотрите последние записи, подтверждения и происхождение данных, не покидая workspace.",
        "Function Version History": "История версий функции",
        "Structure Version History": "История версий структуры",
        "Global Hypothesis Version History": "История версий глобальной гипотезы",
        "No versions yet": "Версий пока нет",
        "This entity has not recorded any version snapshots yet.": "Для этой сущности пока не сохранено ни одного snapshot версии.",
        "Back To Record": "Назад к записи",
        "Open Audit Trail": "Открыть журнал аудита",
        "Entity": "Сущность",
        "Record": "Запись",
        "Versions": "Версии",
        "History": "История",
        "Each snapshot shows the stored record exactly as it was committed.": "Каждый snapshot показывает запись ровно в том виде, в каком она была зафиксирована.",
        "New Function": "Новая функция",
        "Edit Function": "Редактирование функции",
        "Function Form": "Форма функции",
        "Keep the form focused: enough detail to be useful, nothing more.": "Держите форму сфокусированной: достаточно деталей, чтобы быть полезной, и ничего лишнего.",
        "New Structure": "Новая структура",
        "Edit Structure": "Редактирование структуры",
        "Structure Form": "Форма структуры",
        "Use one line per field member so the layout stays easy to scan and edit.": "Используйте одну строку на одно поле, чтобы layout было легко просматривать и редактировать.",
        "New Global Hypothesis": "Новая глобальная гипотеза",
        "Edit Global Hypothesis": "Редактирование глобальной гипотезы",
        "Global Hypothesis Form": "Форма глобальной гипотезы",
        "Capture only the parts that matter to the current analytical claim.": "Фиксируйте только то, что важно для текущего аналитического утверждения.",
        "Not Found": "Не найдено",
        "This page is not available": "Эта страница недоступна",
        "Dashboard": "Панель",
        "Pending": "Ожидает",
        "Functions": "Функции",
        "Structures": "Структуры",
        "Hypotheses": "Гипотезы",
        "Global Hypotheses": "Глобальные гипотезы",
        "Function": "Функция",
        "Structure": "Структура",
        "Global Hypothesis": "Глобальная гипотеза",
        "Searchable function records in this workspace.": "Доступные для поиска записи функций в этом workspace.",
        "Recovered layouts and type notes.": "Восстановленные layout'ы и заметки по типам.",
        "Global analysis hypotheses.": "Глобальные аналитические гипотезы.",
        "Changes waiting for confirmation.": "Изменения, ожидающие подтверждения.",
        "Open Search": "Открыть поиск",
        "Review Pending Changes": "Проверить ожидающие изменения",
        "Browse Audit Trail": "Открыть журнал аудита",
        "CLI shortcuts for data management:": "CLI-команды для работы с данными:",
        "All entities": "Все сущности",
        "Search for functions, tags, or hypotheses": "Ищите функции, теги или гипотезы",
        "binary_id (optional)": "binary_id (необязательно)",
        "tag (optional)": "tag (необязательно)",
        "Reset": "Сбросить",
        "No summary available yet.": "Краткое описание пока отсутствует.",
        "No facts yet": "Фактов пока нет",
        "Observed facts will appear here once they are added.": "Наблюдаемые факты появятся здесь после добавления.",
        "No hypotheses yet": "Гипотез пока нет",
        "There are no linked hypotheses for this entity yet.": "Для этой сущности пока нет связанных гипотез.",
        "No evidence yet": "Свидетельств пока нет",
        "Evidence snippets and attachments will appear here once they are recorded.": "Здесь появятся snippets доказательств и вложения, когда они будут добавлены.",
        "No relations yet": "Связей пока нет",
        "Linked entities will appear here once relationships are added.": "Связанные сущности появятся здесь после добавления отношений.",
        "View proposal payload": "Показать payload предложения",
        "Confirm": "Подтвердить",
        "Reject": "Отклонить",
        "View snapshot": "Показать snapshot",
        "Filter Audit": "Фильтровать аудит",
        "entity_type (optional)": "entity_type (необязательно)",
        "entity_id (optional)": "entity_id (необязательно)",
        "View Version History": "Показать историю версий",
        "Edit Record": "Редактировать запись",
        "Save Function": "Сохранить функцию",
        "Save Structure": "Сохранить структуру",
        "Save Global Hypothesis": "Сохранить глобальную гипотезу",
        "Cancel": "Отмена",
        "Allow address conflict": "Разрешить конфликт адресов",
        "New": "Новая",
        "Probable": "Вероятная",
        "Confirmed": "Подтверждена",
        "Rejected": "Отклонена",
        "Key Metadata": "Ключевые метаданные",
        "Signals": "Сигналы",
        "Observed Facts": "Наблюдаемые факты",
        "Evidence": "Свидетельства",
        "Relations": "Связи",
        "Actions": "Действия",
        "Timeline": "Лента изменений",
        "Summary": "Сводка",
        "Fields": "Поля",
        "Statement": "Формулировка",
        "Status": "Статус",
        "Supporting Facts": "Поддерживающие факты",
        "Use these pages when you need to understand how a record changed over time.": "Используйте эти страницы, когда нужно понять, как запись менялась со временем.",
        "No fields yet": "Поля пока не заданы",
        "This structure has no member layout recorded yet.": "Для этой структуры пока не записан layout полей.",
        "Any": "Любой",
        "Address": "Адрес",
        "Binary": "Бинарь",
        "Source": "Источник",
        "Name": "Имя",
        "Offset": "Смещение",
        "Type": "Тип",
        "Size": "Размер",
        "Comment": "Комментарий",
    }
}

PHRASE_TRANSLATIONS["ru"].update(
    {
        "New Project": "Новый проект",
        "Create Project": "Создать проект",
        "Display Name": "Отображаемое имя",
        "Advanced Settings": "Расширенные настройки",
        "HTTP Port": "HTTP порт",
        "MCP Port": "MCP порт",
        "Create the first workspace from the browser, then start it when you are ready.": "Создайте первый workspace прямо в браузере, а запустите его, когда будете готовы.",
        "Set up a fresh local workspace that will appear on your project shelf right away.": "Настройте новое локальное workspace, и оно сразу появится на полке проектов.",
        "Project created successfully.": "Проект успешно создан.",
        "Project ID is required.": "ID проекта обязателен.",
        "Project ID already exists.": "Проект с таким ID уже существует.",
        "Display Name is required.": "Отображаемое имя обязательно.",
        "http_port must be a valid integer.": "HTTP порт должен быть корректным целым числом.",
        "mcp_port must be a valid integer.": "MCP порт должен быть корректным целым числом.",
        "http_port must be between 1 and 65535.": "HTTP порт должен быть в диапазоне от 1 до 65535.",
        "mcp_port must be between 1 and 65535.": "MCP порт должен быть в диапазоне от 1 до 65535.",
        "HTTP Port and MCP Port must be different.": "HTTP и MCP порты должны быть разными.",
        "Write Mode must be confirm or auto.": "Write Mode должен быть confirm или auto.",
        "Project Root must point to a directory.": "Project Root должен ссылаться на папку.",
        "Project Root already exists and is not empty. Home GUI create only supports a new workspace folder.": "Project Root уже существует и не пуст. Создание из home GUI поддерживает только новую папку workspace.",
        "Leave blank to use the default project folder under": "Оставьте пустым, чтобы использовать стандартную папку проектов в",
    }
)
PHRASE_TRANSLATIONS["ru"].update(
    {
        "Settings": "РќР°СЃС‚СЂРѕР№РєРё",
        "Project Settings": "РќР°СЃС‚СЂРѕР№РєРё РїСЂРѕРµРєС‚Р°",
        "Connection Target": "РўРѕС‡РєР° РїРѕРґРєР»СЋС‡РµРЅРёСЏ",
        "Use the MCP endpoint as the primary connection target for agents.": "РСЃРїРѕР»СЊР·СѓР№С‚Рµ MCP endpoint РєР°Рє РѕСЃРЅРѕРІРЅСѓСЋ С‚РѕС‡РєСѓ РїРѕРґРєР»СЋС‡РµРЅРёСЏ РґР»СЏ Р°РіРµРЅС‚РѕРІ.",
        "Workspace HTTP remains available at": "HTTP workspace РѕСЃС‚Р°С‘С‚СЃСЏ РґРѕСЃС‚СѓРїРЅС‹Рј РїРѕ Р°РґСЂРµСЃСѓ",
        "Adjust the project identity, write mode, and network endpoints without leaving the workspace.": "РР·РјРµРЅСЏР№С‚Рµ РёРјСЏ РїСЂРѕРµРєС‚Р°, СЂРµР¶РёРј Р·Р°РїРёСЃРё Рё СЃРµС‚РµРІС‹Рµ endpoint'С‹, РЅРµ РїРѕРєРёРґР°СЏ workspace.",
        "HTTP Host": "HTTP С…РѕСЃС‚",
        "MCP Host": "MCP С…РѕСЃС‚",
        "MCP is the primary endpoint for agent connections. HTTP is still used for the browser workspace.": "MCP РѕСЃС‚Р°С‘С‚СЃСЏ РѕСЃРЅРѕРІРЅС‹Рј endpoint РґР»СЏ Р°РіРµРЅС‚РѕРІ. HTTP РїРѕ-РїСЂРµР¶РЅРµРјСѓ РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РґР»СЏ browser workspace.",
        "Save Settings": "РЎРѕС…СЂР°РЅРёС‚СЊ РЅР°СЃС‚СЂРѕР№РєРё",
        "Project settings were saved successfully.": "РќР°СЃС‚СЂРѕР№РєРё РїСЂРѕРµРєС‚Р° СѓСЃРїРµС€РЅРѕ СЃРѕС…СЂР°РЅРµРЅС‹.",
        "Network settings were saved. Restart the project from Home UI to apply them.": "РЎРµС‚РµРІС‹Рµ РЅР°СЃС‚СЂРѕР№РєРё СЃРѕС…СЂР°РЅРµРЅС‹. Р§С‚РѕР±С‹ РїСЂРёРјРµРЅРёС‚СЊ РёС…, РїРµСЂРµР·Р°РїСѓСЃС‚РёС‚Рµ РїСЂРѕРµРєС‚ РёР· Home UI.",
        "HTTP Port must be a valid integer.": "HTTP РїРѕСЂС‚ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РєРѕСЂСЂРµРєС‚РЅС‹Рј С†РµР»С‹Рј С‡РёСЃР»РѕРј.",
        "MCP Port must be a valid integer.": "MCP РїРѕСЂС‚ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РєРѕСЂСЂРµРєС‚РЅС‹Рј С†РµР»С‹Рј С‡РёСЃР»РѕРј.",
        "http_host is required": "http_host РѕР±СЏР·Р°С‚РµР»РµРЅ.",
        "mcp_host is required": "mcp_host РѕР±СЏР·Р°С‚РµР»РµРЅ.",
        "display_name is required": "display_name РѕР±СЏР·Р°С‚РµР»РµРЅ.",
        "write_mode must be one of: confirm, auto": "write_mode РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РѕРґРЅРёРј РёР·: confirm, auto.",
        "http_port and mcp_port must be positive integers": "http_port Рё mcp_port РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ РїРѕР»РѕР¶РёС‚РµР»СЊРЅС‹РјРё С†РµР»С‹РјРё С‡РёСЃР»Р°РјРё.",
        "http_port and mcp_port must be between 1 and 65535": "http_port Рё mcp_port РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ РІ РґРёР°РїР°Р·РѕРЅРµ РѕС‚ 1 РґРѕ 65535.",
        "http_port and mcp_port must be different": "http_port Рё mcp_port РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ СЂР°Р·РЅС‹РјРё.",
    }
)


def resolve_language(raw_value: str | None) -> str:
    if raw_value and raw_value.strip().lower() in SUPPORTED_LANGUAGES:
        return raw_value.strip().lower()
    return "en"


def translate_text(lang: str, text: str) -> str:
    if lang == "en":
        return text
    return PHRASE_TRANSLATIONS.get(lang, {}).get(text, text)


def with_lang(url: str, lang: str) -> str:
    resolved = resolve_language(lang)
    parts = urlsplit(url)
    query_items = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "lang"]
    query_items.append(("lang", resolved))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_items), parts.fragment))


def ensure_lang(url: str, lang: str) -> str:
    parts = urlsplit(url)
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    if any(key == "lang" for key, _ in query_items):
        return url
    query_items.append(("lang", resolve_language(lang)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_items), parts.fragment))


def language_switcher(current_url: str, lang: str) -> str:
    links: list[str] = []
    for option in ("en", "ru"):
        class_name = "lang-chip is-active" if option == lang else "lang-chip"
        links.append(
            f'<a class="{class_name}" href="{escape(with_lang(current_url, option), quote=True)}">{escape(option.upper())}</a>'
        )
    return f'<div class="language-switcher">{"".join(links)}</div>'


def localize_markup(html: str, lang: str) -> str:
    localized = html.replace('<html lang="en">', f'<html lang="{resolve_language(lang)}">')
    if lang != "en":
        for english, translated in sorted(PHRASE_TRANSLATIONS.get(lang, {}).items(), key=lambda item: len(item[0]), reverse=True):
            localized = localized.replace(english, translated)

    def replace_url(match: re.Match[str]) -> str:
        attribute = match.group(1)
        url = match.group(2)
        if url.startswith("/") or url.startswith("http://") or url.startswith("https://"):
            updated = ensure_lang(url, lang)
            return f'{attribute}="{escape(updated, quote=True)}"'
        return match.group(0)

    return re.sub(r'(href|action)="([^"]+)"', replace_url, localized)
