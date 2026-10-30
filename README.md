# locqa

CLI для контроля качества локализации Flutter ARB-файлов. Сравнивает эталонный ARB (например русский) с переводом (например казахским), находит ошибки 11 типов, пишет `report.json` и HTML-отчёт, готовит таблицу для носителя языка и вносит в файл только те исправления, которые носитель подтвердил.

Проект сделан для кейса Grand Mobile «Qazaq Loc QA» на Decentrathon 6.0. Работает с любой парой ARB-файлов: знания о конкретных языках лежат в `src/locqa/langs.py`, а без профиля языка проверки работают в универсальном режиме.

## Установка

Нужен Python 3.11+.

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"         # правила, отчёты, тесты
pip install -e ".[dev,llm]"     # плюс LLM-слой (Gemini)
locqa --help
```

Для LLM скопируйте `.env.example` в `.env` и впишите `GEMINI_API_KEY`.

## Полный цикл за пять команд

```bash
# 1. Проверка: report.json, report_meta.json и HTML
locqa check --source data/intl_ru.arb --target data/intl_kk.arb \
  --glossary glossary/glossary.csv \
  --context data/intl_en.arb --context data/intl_uz.arb \
  --out out/report.json --html out/report.html

#    то же с LLM: предложения исправлений и поиск машинного перевода (+ out/cost.json)
locqa check ... --llm --budget-usd 2            # только находки правил и подозрительные строки
locqa check ... --llm --llm-scope all           # все строки, около $1 на gemini-2.5-flash

# 2. Таблица для носителя: одна строка на ключ, сначала high
locqa review-sheet --report out/report.json --out out/review.csv --min-severity medium

# 3. Носитель заполняет в review.csv колонки decision (accept / edit / reject) и final_text

# 4. Применить решения: только accept и edit, каждая строка с флагом проверки человеком
locqa apply --source data/intl_ru.arb --target data/intl_kk.arb \
  --review out/review.csv --out out/intl_kk_fixed.arb --report out/report.json

# 5. Проверить результат: плейсхолдеры, ICU, ключи, флаги, flutter gen-l10n (если установлен)
locqa validate --source data/intl_ru.arb --target out/intl_kk_fixed.arb \
  --original data/intl_kk.arb
```

Попробовать без данных кейса можно на синтетических фикстурах: `tests/fixtures/src_ru.arb` и `tests/fixtures/tgt_kk.arb`.

## Команды

| Команда | Что делает |
| --- | --- |
| `check` | Находит ошибки, пишет `report.json`, `report_meta.json`, по желанию HTML и `cost.json` |
| `review-sheet` | Делает `review.csv` для носителя (UTF-8 с BOM, открывается в Excel); `--chunk N` делит на части |
| `apply` | Вносит подтверждённые строки в ARB точечно: остальные байты файла не меняются |
| `validate` | Проверяет исправленный файл; с `--original` ещё потерю ключей, порядок и флаги проверки |
| `report` | Пересобирает HTML из `report.json` |

Основные флаги `check`:

| Флаг | Что делает |
| --- | --- |
| `--glossary FILE` | `glossary.csv` для `glossary_violation`; без него проверка пропускается |
| `--context FILE` | ARB на другом языке: контекст для LLM и для `wrong_language`. Повторяется |
| `--only a,b` / `--skip a,b` | выбрать проверки по имени (`issue_type`) |
| `--min-severity low\|medium\|high` | не писать находки ниже уровня |
| `--lang kk` | язык перевода, если его нет в `@@locale` и имени файла |
| `--llm` | LLM-слой; `--llm-model`, `--llm-scope suspects\|all`, `--max-llm-strings`, `--budget-usd`, `--llm-cache` |

Коды возврата: `0` нет находок (или все проверки `validate` прошли), `1` есть находки или отклонённые строки, `2` ошибка ввода, `3` ошибка LLM (результаты правил всё равно записаны).

## Что находит

| Тип | Как | Severity |
| --- | --- | --- |
| `untranslated` | ключа нет в переводе или значение пустое | high |
| `same_as_source` | перевод совпадает с исходником; бренды, числа, латиница пропускаются. Одно слово без русских окончаний считается возможным заимствованием | medium / low |
| `placeholder_mismatch` | `{name}`, теги `<g>` и `\n` не совпадают с исходником | high / medium / low |
| `plural_mismatch` | сломанный ICU, потерянный plural, нет `other`, пустые ветки, категории не того языка | high / medium / low |
| `glossary_violation` | термин из глоссария переведён запрещённым вариантом или ни одним из разрешённых | из глоссария |
| `length_overflow` | короткий элемент интерфейса в переводе в 2–2.5+ раза длиннее; повторяющийся «хвост» поднимает severity | high / medium / low |
| `machine_translation_suspect` | только LLM: калька, русская грамматика, неестественный порядок слов | от модели |
| `inconsistent_term` | один и тот же короткий исходник переведён в разных ключах разными словами | medium / low |
| `suffix_harmony` | аффикс сразу после плейсхолдера: `{name}-ға` | medium |
| `orthography` | латинские буквы в кириллических словах и казахские буквы, набранные русскими (`жане` при `және` в файле) | medium / low |
| `wrong_language` | текст в другом алфавите или совпадает с переводом на другой язык из `--context` | high / medium |

У каждой находки evidence с числами и конкретными словами. Правила не исправляют текст сами: `suggestion` заполняют только `orthography` и `inconsistent_term` (детерминированно) и LLM, и любое предложение проверяется кодом на плейсхолдеры и ICU.

## Форматы

Подробно в [`docs/SCHEMA.md`](docs/SCHEMA.md), методология в [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md). Находка в `report.json` (пример из описания кейса):

```json
{
  "key": "garage_rent_button",
  "issue_type": "length_overflow",
  "severity": "high",
  "source": "Арендовать",
  "target": "Жалға алу үшін басыңыз",
  "evidence": "28 символов против 10 в исходнике, ключ похож на кнопку",
  "suggestion": "Жалға алу",
  "confidence": 0.95,
  "reviewed_by_human": true
}
```

## Данные

Файлы организаторов кладутся в `data/` и не попадают в git. Тесты используют только синтетические фикстуры из `tests/fixtures/`. Перед коммитом запускайте `python scripts/check_no_data_leak.py` (в CI он тоже запускается).

## Разработка

```bash
ruff check . && ruff format --check .
pytest
```

GitHub Action (`.github/workflows/check.yml`) гоняет линтер, тесты и проверку утечек, а в pull request запускает `locqa check` на каждом изменённом ARB и прикладывает HTML-отчёт как artifact.

## Ограничения

- `flutter gen-l10n` запускается в `validate`, только если Flutter установлен.
- Флаг проверки человеком пишется в `@key` как `x-reviewed_by_human: true` (формат не задан организаторами, см. `docs/OPEN_QUESTIONS.md`).
- `machine_translation_suspect` без LLM не ищется: надёжных правил для кальки нет.
- Глоссарий в `glossary/glossary.csv` пока черновик из данных; строки с пометкой «РЕШИТЬ НОСИТЕЛЮ» ждут решения носителя.
