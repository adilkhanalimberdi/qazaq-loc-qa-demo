# Форматы файлов

## report.json

Плоский JSON-массив находок. Поля совпадают со схемой организаторов, лишних полей нет.

| Поле | Тип | Значение |
| --- | --- | --- |
| `key` | string | ключ ARB |
| `issue_type` | string | один из 11 типов, см. README |
| `severity` | `high` \| `medium` \| `low` | high ломает игру или смысл, low это замечание |
| `source` | string | исходная строка |
| `target` | string | текущий перевод; пустой, если ключа нет |
| `evidence` | string | что найдено, с числами; у находок LLM начинается с `LLM:` |
| `suggestion` | string \| null | предложенный текст; прошёл проверку плейсхолдеров и ICU |
| `confidence` | 0..1 | у правил фиксированная, у LLM оценка модели |
| `reviewed_by_human` | bool | `true` после `locqa apply --report`, если носитель принял или отредактировал строку |

На один ключ приходится не больше одной находки каждого типа. Порядок: severity (high первым), затем позиция ключа в исходнике.

## report_meta.json

Сводка прогона: версия инструмента, sha256 входных файлов, языки, список проверок, счётчики по типам и severity, предупреждения (дубли ключей, лишние ключи) и блок `llm`.

## cost.json

Пишется рядом с `report.json` при `--llm`; то же, что `report_meta.json → llm`.

| Поле | Значение |
| --- | --- |
| `model`, `prompt_version` | модель и версия промпта (часть ключа кеша) |
| `requests`, `cached_requests` | запросы к API и ответы из кеша |
| `input_tokens`, `output_tokens` | токены (thinking-токены входят в output) |
| `price_usd_per_1m`, `cost_usd`, `budget_usd` | тариф, итог и лимит |
| `strings_selected`, `strings_answered` | сколько строк отправлено и сколько получило ответ |
| `suggestions_added`, `suggestions_rejected` | предложения, принятые и отброшенные кодом |
| `dismissed` | находки правил, которые модель уверенно сочла ложными (только `same_as_source`, `inconsistent_term`) |
| `new_findings` | находки модели (`machine_translation_suspect` и др.) |
| `stopped` | почему слой остановился раньше (бюджет, сеть), иначе null |

Тарифы лежат в `src/locqa/llm/cost.py`. Для модели, которой там нет, задайте `LOCQA_PRICE_INPUT` и `LOCQA_PRICE_OUTPUT` (USD за 1M токенов).

## glossary.csv

| Колонка | Обязательна | Значение |
| --- | --- | --- |
| `ru` | да | термин в исходнике |
| `kk` | да | разрешённые переводы через `\|`; пусто: термин ещё не решён, проверка пропускается |
| `en` | да | английский вариант |
| `note` | да | комментарий по употреблению |
| `register` | нет | `literary` или `slang`; для сленга находки мягче |
| `forbidden_kk` | нет | запрещённые варианты через `\|` |
| `severity` | нет | severity нарушения, по умолчанию medium |
| `ru_forms` | нет | точные словоформы исходника через `\|`; без колонки ищется по основе термина |

Казахские варианты сравниваются по основе с учётом аффиксов и чередования к/г, қ/ғ, п/б (`сыйлық` находит `сыйлығын`).

## review.csv

Одна строка на ключ, UTF-8 с BOM.

| Колонка | Кто заполняет | Значение |
| --- | --- | --- |
| `key`, `severity`, `issue_types`, `source`, `target`, `suggestion`, `evidence`, `confidence` | `review-sheet` | из report.json |
| `decision` | носитель | `accept`: взять `final_text`, а если он пустой, `suggestion`; `edit`: взять `final_text`; `reject` или пусто: не менять |
| `final_text` | носитель | свой вариант |
| `reviewer`, `comment` | носитель | кто проверил и заметки |

## intl_kk_fixed.arb и fixed_review.json

`apply` меняет только значения подтверждённых ключей и добавляет недостающие (после ближайшего предыдущего ключа исходника). Повторяющиеся `@@comment`, порядок, отступы и экранирование остальных строк сохраняются байт в байт.

У каждой изменённой строки в метаданных:

```json
"@greeting": {"x-reviewed_by_human": true, "x-reviewed_at": "2026-10-30T12:00:00+00:00", "x-reviewer": "native1"}
```

Если `@key` уже был, поля добавляются к нему. `fixed_review.json` содержит список изменений: `key`, `old`, `new`, `decision`, `reviewer`, `comment`, `issue_types`, `reviewed_by_human`.
