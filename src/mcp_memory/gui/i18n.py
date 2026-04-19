from __future__ import annotations

import re
from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SUPPORTED_LANGUAGES = {"en", "ru"}


PHRASE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        "Projects": "Проекты",
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
        "Project Overview": "Обзор проекта",
        "Project Snapshot": "Снимок проекта",
        "A calm overview of what is already in this workspace.": "Спокойный обзор того, что уже есть в этом workspace.",
        "Project Stats": "Статистика проекта",
        "The current shape of this local workspace.": "Текущий состав этого локального workspace.",
        "Quick Entries": "Быстрые переходы",
        "Open the working surface you need next.": "Откройте нужную рабочую поверхность.",
        "Storage Paths": "Локальные пути",
        "Everything stays local to this project workspace.": "Все остается локально внутри workspace проекта.",
        "Recent Updates": "Последние обновления",
        "Latest searchable records from this project.": "Последние searchable-записи этого проекта.",
        "Local offline-first reverse-engineering knowledge base.": "Локальная offline-first база знаний для reverse engineering.",
        "Binaries": "Бинари",
        "Distinct binary IDs referenced by records.": "Уникальные binary_id, на которые ссылаются записи.",
        "HTTP Endpoint": "HTTP endpoint",
        "MCP Endpoint": "MCP endpoint",
        "DB Path": "Путь к БД",
        "Exports Dir": "Папка export",
        "Backups Dir": "Папка backup",
        "No recent updates yet": "Последних обновлений пока нет",
        "Created or updated records will appear here once the project has searchable content.": "Созданные или обновленные записи появятся здесь, когда в проекте будет searchable content.",
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
        "Filter by text, binary, tag, or sort order.": "Фильтруйте по тексту, binary, тегу или сортировке.",
        "Filter by text, binary, tag, status, or sort order.": "Фильтруйте по тексту, binary, тегу, статусу или сортировке.",
        "No functions found": "Функции не найдены",
        "No structures found": "Структуры не найдены",
        "No global hypotheses found": "Глобальные гипотезы не найдены",
        "Try a broader query or clear one filter.": "Попробуйте более широкий запрос или сбросьте один фильтр.",
        "Search by name or summary": "Поиск по имени или summary",
        "Any status": "Любой статус",
        "Sort by name": "Сортировать по имени",
        "Sort by updated": "Сортировать по обновлению",
        "Apply Filters": "Применить фильтры",
        "Facts": "Факты",
        "Relations": "Связи",
        "History": "История",
        "Function Metadata": "Метаданные функции",
        "Structure Metadata": "Метаданные структуры",
        "Hypothesis Metadata": "Метаданные гипотезы",
        "Hypothesis Status": "Статус гипотезы",
        "Function ID": "ID функции",
        "Structure ID": "ID структуры",
        "Hypothesis ID": "ID гипотезы",
        "Raw Name": "Исходное имя",
        "Updated": "Обновлено",
        "Confidence unknown": "Уверенность неизвестна",
        "Open Focused Graph": "Открыть граф связей",
        "Graph Filters": "Фильтры графа",
        "Relation Graph": "Граф связей",
        "Graph Nodes": "Узлы графа",
        "Focus one entity or scan recent relation clusters.": "Сфокусируйтесь на одной сущности или просмотрите недавние группы связей.",
        "No graph links yet": "Связей для графа пока нет",
        "Create relations first, or loosen one graph filter.": "Сначала создайте связи или ослабьте один из фильтров графа.",
        "Open Search": "Открыть поиск",
        "Open Functions": "Открыть функции",
        "Export Project": "Экспорт проекта",
        "Import Project": "Импорт проекта",
        "Export JSON": "Экспорт JSON",
        "Import JSON": "Импорт JSON",
        "Project export completed.": "Экспорт проекта завершен.",
        "Project import completed.": "Импорт проекта завершен.",
        "Output Path": "Путь вывода",
        "Input Path": "Путь ввода",
        "Replace existing records": "Заменить существующие записи",
        "Write a JSON bundle to a local path.": "Запишите JSON bundle в локальный путь.",
        "Read a JSON bundle from a local path. Use replace only when you mean it.": "Прочитайте JSON bundle из локального пути. Используйте замену только осознанно.",
        "Create Backup": "Создать backup",
        "Restore Backup": "Восстановить backup",
        "Project backup created.": "Backup проекта создан.",
        "Project backup restored as a new project.": "Backup проекта восстановлен как новый проект.",
        "Create a local zip archive for this project.": "Создайте локальный zip-архив этого проекта.",
        "Restore into an explicit new project target. The current project is not overwritten.": "Восстановите в явно заданный новый проект. Текущий проект не перезаписывается.",
        "Project Root": "Папка проекта",
        "Input Path is required.": "Путь ввода обязателен.",
        "Project Root is required.": "Папка проекта обязательна.",
        "Hops must be 1 or 2.": "Глубина должна быть 1 или 2.",
        "Min confidence must be a number.": "Минимальная уверенность должна быть числом.",
        "Any focus type": "Любой тип фокуса",
        "Any entity type": "Любой тип сущности",
        "1 hop": "1 шаг",
        "2 hops": "2 шага",
        "Each snapshot shows the stored record exactly as it was committed.": "Каждый снимок показывает сохраненную запись ровно в том виде, в котором она была зафиксирована.",
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
        "Setup Guide": "Мастер настройки",
        "Create one local workspace, copy the MCP endpoint, then open the project tools when you are ready.": "Создайте один локальный workspace, скопируйте MCP endpoint и откройте инструменты проекта, когда будете готовы.",
        "Local Home": "Локальный дом",
        "Everything stays on this machine.": "Все остается на этой машине.",
        "Use the same local project creation flow as the main form.": "Используется тот же локальный flow создания проекта, что и в основной форме.",
        "MCP Endpoint": "MCP endpoint",
        "Connect agents through the MCP endpoint.": "Подключайте агентов через MCP endpoint.",
        "Local Paths": "Локальные пути",
        "Backups and exports stay beside the project workspace.": "Backups и exports остаются рядом с workspace проекта.",
        "No project selected yet": "Проект пока не выбран",
        "Create a project first, then the MCP config will appear here.": "Сначала создайте проект, затем здесь появится MCP config.",
        "Registry Path": "Путь registry",
        "App Home": "Дом приложения",
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
        "Settings": "Настройки",
        "Project Settings": "Настройки проекта",
        "Connection Target": "Точка подключения",
        "Use the MCP endpoint as the primary connection target for agents.": "Используйте MCP endpoint как основную точку подключения для агентов.",
        "Workspace HTTP remains available at": "HTTP workspace остается доступным по адресу",
        "Adjust the project identity, write mode, and network endpoints without leaving the workspace.": "Изменяйте имя проекта, режим записи и сетевые endpoint'ы, не покидая workspace.",
        "HTTP Host": "HTTP хост",
        "MCP Host": "MCP хост",
        "MCP is the primary endpoint for agent connections. HTTP is still used for the browser workspace.": "MCP остается основным endpoint'ом для подключения агентов. HTTP по-прежнему используется для browser workspace.",
        "Save Settings": "Сохранить настройки",
        "Project settings were saved successfully.": "Настройки проекта успешно сохранены.",
        "Network settings were saved. Restart the project from Home UI to apply them.": "Сетевые настройки сохранены. Чтобы применить их, перезапустите проект из Home UI.",
        "HTTP Port must be a valid integer.": "HTTP порт должен быть корректным целым числом.",
        "MCP Port must be a valid integer.": "MCP порт должен быть корректным целым числом.",
        "http_host is required": "http_host обязателен.",
        "mcp_host is required": "mcp_host обязателен.",
        "display_name is required": "display_name обязателен.",
        "write_mode must be one of: confirm, auto": "write_mode должен быть одним из: confirm, auto.",
        "http_port and mcp_port must be positive integers": "http_port и mcp_port должны быть положительными целыми числами.",
        "http_port and mcp_port must be between 1 and 65535": "http_port и mcp_port должны быть в диапазоне от 1 до 65535.",
        "http_port and mcp_port must be different": "http_port и mcp_port должны быть разными.",
        "Confirm mode": "Режим: подтверждение",
        "Auto mode": "Режим: авто",
        "Skip to content": "Перейти к содержимому",
        "Search workspace": "Поиск по workspace",
        "Toggle sidebar": "Переключить боковое меню",
        "Workspace navigation": "Навигация workspace",
        "Toggle color theme": "Переключить тему",
        "Theme": "Тема",
        "Language selector": "Выбор языка",
        "Switch language to English": "Переключить язык на английский",
        "Switch language to Russian": "Переключить язык на русский",
        "Project actions": "Действия проекта",
        "Edit Project": "Редактировать проект",
        "Adjust the project name, write mode, and local endpoints from Home UI.": "Изменяйте имя проекта, режим записи и локальные endpoint'ы из Home UI.",
        "Save Project": "Сохранить проект",
        "Project updated successfully.": "Проект успешно обновлён.",
        "Project removed from the shelf.": "Проект удалён с полки.",
        "Project action failed.": "Не удалось выполнить действие с проектом.",
        "HTTP Host is required.": "HTTP Host обязателен.",
        "MCP Host is required.": "MCP Host обязателен.",
        "Edit": "Редактировать",
        "Delete": "Удалить",
        "Back to Projects": "Назад к проектам",
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
        label = "Switch language to English" if option == "en" else "Switch language to Russian"
        links.append(
            f'<a class="{class_name}" href="{escape(with_lang(current_url, option), quote=True)}" aria-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}">{escape(option.upper())}</a>'
        )
    return f'<div class="language-switcher" aria-label="Language selector">{"".join(links)}</div>'


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
