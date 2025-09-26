# ТЗ (единый файл): внутренний сервис сверки внешнеторговых документов

## 0) Резюме (с учётом всех правок)
Внутренний веб-сервис для офиса. Сотрудники загружают **партию** файлов поставки (PDF/PNG/JPG/DOCX/XLSX). Система:
1) извлекает текст (**локальная модель** `dots.ocr` как отдельный HTTP-сервис для сканов; парсер для Office);
2) классифицирует документ (декларация/инвойс/PL/коносамент и т.д.);
3) вызывает **локальный** API-сервис `json-filler` (LLM, развёрнутая на сервере) для заполнения целевого JSON (значения, ссылки на OCR-токены/ячейки, bbox);
4) рассчитывает **уверенность поля только на основе OCR** (`token.conf` из `dots.ocr` + проверки формата/якорей);
5) даёт пользователю экран **ревью до валидации** для правки полей с низкой уверенностью;
6) валидирует кросс-согласованность всех документов в партии;
7) формирует финальный отчёт и публикует его в **Архиве поставок**;
8) **Показывает занятость системы**: другие пользователи видят, что сервис обрабатывает документы (очередь/активные задачи/занятость воркеров).

Хранение — **локальные директории** на сервере. Фронтэнд — без «красоты»: REST + простые HTML/JSON-страницы.

---

## 1) Цели и границы
- Приём партий документов, извлечение данных, заполнение унифицированных JSON, ручная правка, валидация и отчёт.
- Минимальная инфраструктура и безопасность (внутренняя сеть, локальные каталоги, без S3).
- Масштабирование в рамках одного сервера (при росте — вынести сервисы в контейнеры).

**Не цели:** сложный UI, облачные сервисы, внешние хранилища.

---

## 2) Технологический стек
- **Backend/API:** Python 3.11+, FastAPI
- **Очереди:** Celery + Redis
- **БД:** PostgreSQL 15+ (jsonb)
- **OCR:** **локально установленная модель** `dots.ocr` (HTTP API), поддержка zh/en/ru, выдаёт `tokens{text,bbox,conf,id}`
- **LLM JSON Filler:** **локальная LLM** за сервисом `json-filler` (HTTP API), возвращает **только** `value` + `token_refs`/`bbox`, **без** confidence
- **Парсинг DOCX/XLSX:** python-docx, openpyxl
- **PDF превью:** PyMuPDF (fitz) → PNG (для подсветки bbox на canvas)
- **Фронтэнд:** простые HTML/JSON страницы (Jinja2/HTMX или чистый REST + примитивные шаблоны)
- **Мониторинг (опц.):** Prometheus + Grafana
- **Деплой:** Docker Compose (по мере необходимости)
- **Онлайн-статусы:** Server-Sent Events (SSE) или поллинг для «система занята/очередь/прогресс»

---

## 3) Локальное хранение (без S3)
```
/srv/supplyhub/
  batches/{batch_id}/
    raw/                       # исходники
    derived/{doc_id}/
      ocr.json                 # ответ dots.ocr
      filled.json              # ответ json-filler + добавленный confidence
    preview/{doc_id}/page_{n}.png
    report/report.json         # финальный отчёт партии
```
FastAPI монтирует `/srv/supplyhub` через `StaticFiles` как `/files` (read-only). Архив и отчёты доступны всем сотрудникам в офисной сети.

---

## 4) Доменные сущности
- **Batch (Партия)** — единица поставки (набор файлов).  
- **Document** — файл внутри партии (определяется тип).  
- **Filled JSON** — унифицированный JSON документа (поля, bbox, ссылки на токены, источники).  
- **Validation Report** — результаты кросс-сверки по партии.

---

## 5) Жизненный цикл и статусы
Поток:
```
NEW → PREPARED → TEXT_READY → CLASSIFIED → FILLED_AUTO → FILLED_REVIEWED → VALIDATED → DONE
                                   \                                           \
                                    \-------------------------(ошибка)----------> FAILED
```
- `PREPARED` — файлы сохранены в `/raw`
- `TEXT_READY` — извлечён текст (OCR/парсер) → `/derived/.../ocr.json`
- `CLASSIFIED` — определён тип документа
- `FILLED_AUTO` — вызван `json-filler`, получен черновой filled.json; рассчитан confidence (см. п.9)
- `FILLED_REVIEWED` — пользователь исправил/подтвердил поля < порога
- `VALIDATED` — отработали правила сверки
- `DONE` — отчёт готов и в архиве

**Видимость занятости:** параллельно система публикует состояние нагрузки: активные задачи, длина очереди, занятость воркеров.

---

## 6) Типы документов и поля (минимум)
### EXPORT_DECLARATION
- `export_declaration_no` (req)
- `export_declaration_date` (req)
- `country_of_origin` (req)
- `destination` (req)
- `name_product` (req)
- `net_weight` (req)
- `gross_weight` (opt)
- `producer` (opt)
- `buyer` (opt)
- `seller` (opt)
- `exporter` (opt)
- `latin_name` (opt)
- `unit_box` (opt)
- `size_product` (opt)
- `packages` (opt)
- `incoterms` (opt)
- `total_price` (opt)

### INVOICE
- `invoice_no` (req)
- `invoice_date` (req)
- `seller` (req)
- `buyer` (req)
- `currency` (req)
- `total_price` (req)
- `incoterms` (opt)
- `items[]` (opt: name, qty, unit, unit_price, amount)

### PACKING_LIST
- `packages` (req)
- `net_weight` (req)
- `gross_weight` (req)
- `items[]` (opt: name/size/qty/boxes)

### BILL_OF_LADING
- `bl_no` (req)
- `vessel` (req)
- `voyage` (opt)
- `shipper` (req)
- `consignee` (req)
- `port_of_loading` (req)
- `port_of_discharge` (req)
- `container_no` (opt)
- `packages` (opt)
- `gross_weight` (opt)

> Схемы расширяемы: `required/optional`, словари меток (zh/en/ru), регулярки форматов.

---

## 7) База данных (PostgreSQL)
**batches**
- `id` uuid PK
- `created_at` timestamptz
- `created_by` text
- `status` text
- `meta` jsonb

**documents**
- `id` uuid PK
- `batch_id` uuid FK
- `filename` text
- `mime` text
- `pages` int
- `doc_type` text (nullable до классификации)
- `status` text
- `ocr_path` text
- `filled_path` text

**filled_fields**
- `id` uuid PK
- `doc_id` uuid FK
- `field_key` text
- `value` text
- `page` int null
- `bbox` jsonb   // [x0,y0,x1,y1]
- `token_refs` jsonb // ["t_…"]
- `confidence` float   // рассчитано из OCR
- `source` text  // ocr|parser|llm|llm+ocr|user
- `version` int
- `latest` bool
- `edited_by` text
- `edited_at` timestamptz

**validations**
- `id` uuid PK
- `batch_id` uuid FK
- `rule_id` text
- `severity` text // ok|warn|error
- `message` text
- `refs` jsonb // [{doc_id, field_key, page, bbox}]

**system_status** (опц. + кэш)
- `ts` timestamptz
- `workers_busy` int
- `workers_total` int
- `queue_depth` int
- `active_batches` int
- `active_docs` int

---

## 8) Очереди (Celery + Redis) и видимость занятости
Задачи:
- `process_batch(batch_id)` → по документам: `ocr_or_parse` → `classify` → `fill_json` → `score_confidence`
- затем: ожидание ревью → `validate_batch` → `render_report`

**Идемпотентность:** проверка/пропуск уже готовых артефактов.

**Публикация занятости:**
- Celery-мониторинг собирает busy/queued раз в N сек;
- API `GET /system/status` отдаёт:
```json
{
  "workers_busy": 2,
  "workers_total": 4,
  "queue_depth": 7,
  "active_batches": 3,
  "active_docs": 12
}
```
- UI (простая страница/поллинг/SSE) показывает баннер «Система занята: X из Y воркеров активны, в очереди: Z».
- В карточке партии: `position_in_queue` (эвристика по незапущенным задачам).

---

## 9) Источник уверенности (ТОЛЬКО dots.ocr) и формула
- Собираем токены по `token_refs`; если их нет, но есть `bbox` → токены в bbox; если ничего → 0.0.
- `ocr_conf = mean(token.conf)`
- `anchor_bonus` (0..0.1): рядом найден якорь для поля (словарь по типу/полю).
- `format_bonus` (+0.1 / −0.15): валидность формата (дата/валюта+число/вес+ед.).
- `table_bonus` (0..0.05): корректная колонка таблицы (если распознана).
```
field_confidence = clamp( ocr_conf * 0.85 + anchor_bonus + format_bonus + table_bonus , 0, 1 )
```
DOCX/XLSX: `ocr_conf := 1.0` (парсинг), но штраф при невалидном формате.  
Порог ревью: `low_conf_threshold = 0.75` (конфиг).

---

## 10) Классификация документа
- Правила и regex по ключевым терминам (zh/en/ru), при споре — лёгкая локальная модель.
- Результат: `doc_type` + `documents.status=CLASSIFIED`.

---

## 11) Контракты локальных сервисов

### 11.1 `dots.ocr` (локальная модель, HTTP API)
`POST /ocr`
```json
{
  "doc_id": "uuid",
  "file_path": "/srv/supplyhub/batches/{batch_id}/raw/file.pdf",
  "langs": ["zh","en","ru"],
  "options": {"layout": true, "tables": true}
}
```
**Response**
```json
{
  "doc_id": "uuid",
  "pages": [{
    "page": 1, "width": 2480, "height": 3508,
    "tokens": [
      {"id":"t_1001","text":"净重","bbox":[x0,y0,x1,y1],"conf":0.92},
      {"id":"t_1002","text":"1021.4","bbox":[...],"conf":0.96},
      {"id":"t_1003","text":"千克","bbox":[...],"conf":0.91}
    ],
    "lines": [...],
    "tables": [{
      "bbox":[...],
      "cells":[{"r":0,"c":0,"text":"商品编号","bbox":[...], "token_ids":["t_…"]}]
    }]
  }]
}
```
> **Обязательны** стабильные `token.id` и `conf` на токенах.

### 11.2 `json-filler` (локальная LLM, HTTP API)
`POST /v1/fill`
```json
{
  "doc_id": "uuid",
  "doc_type": "EXPORT_DECLARATION",
  "schema_version": "1.0.0",
  "doc_text": "<plain or html-like text>",
  "pages": [{
    "page": 1,
    "width": 2480, "height": 3508,
    "tables": [...],
    "lines":  [...]
  }],
  "target_schema": { "fields": { "net_weight": {"type":"string"}, "...":{}}, "required": ["..."] },
  "hints": {
    "anchors": {"net_weight": ["净重","Net Weight"]},
    "normalization": {"date":"YYYY-MM-DD","weight_unit_default":"kg"}
  }
}
```
**Response (без confidence):**
```json
{
  "doc_id": "uuid",
  "doc_type": "EXPORT_DECLARATION",
  "schema_version": "1.0.0",
  "fields": {
    "export_declaration_no": {
      "value": "422020240000042699",
      "token_refs": ["t_210","t_211"],
      "bbox": [1583,169,2088,194],
      "page": 1,
      "source": "llm"
    },
    "net_weight": {
      "value": "1021.4 kg",
      "token_refs": ["t_1002","t_1003"],
      "page": 1,
      "source": "llm"
    }
  },
  "meta": {"hs_code":"0307119000"}
}
```

---

## 12) Backend REST (минимум)
- `POST /batches` → `{batch_id}` — создать партию
- `POST /batches/{id}/upload` → `{saved:[/files/...raw/…]}` — загрузка файлов
- `POST /batches/{id}/process` — запустить пайплайн до `FILLED_AUTO`
- `GET  /batches/{id}/review` — список полей (value, bbox, token_refs, **confidence**, source, required)
- `POST /documents/{doc_id}/fields/{field_key}` — ручная правка `{value, bbox?}` → `source=user, confidence=1.0`
- `POST /batches/{id}/review/complete` — завершить ревью → запуск валидации
- `GET  /batches/{id}/report` — финальный отчёт (json)
- `GET  /archive` — список партий + статусы + ссылки
- `GET  /system/status` — **видимость занятости системы** (busy/queue/активные)
- `GET  /files/...` — статика из `/srv/supplyhub`

---

## 13) Ревью до валидации
- Страница ревью: таблица полей, сортировка по `confidence`, фильтр «< threshold», инлайн-правка.
- Ховер по полю — подсветка bbox на превью (PNG) с учётом масштаба.
- Кнопка «Продолжить» активна, когда все поля ниже порога подтверждены/исправлены.

---

## 14) Валидация партии (примеры правил)
- **Даты:** proforma ≤ invoice ≤ BL; декларация не позже BL.
- **Номера:** invoice_no совпадает между инвойсом и документами, где он указан.
- **Массы:** нетто/брутто согласованы между PL/инвойсом/декларацией (с допусками).
- **Суммы/валюты:** итоговая сумма/валюта согласованы (где применимо).
- **Страны/порты:** происхождение/назначение/порты согласованы.
→ `validations[]` с `ok|warn|error` и `refs` на конкретные поля (doc_id, field_key, page, bbox).

---

## 15) Отчёт и Архив
- `/report/report.json` — итог (сводка правил + матрица полей/документов).
- «Архив поставок» — общая страница/JSON-лист: все партии, статусы, ссылки на отчёты и файлы.
- Доступен всем сотрудникам во внутренней сети.

---

## 16) Безопасность/операционка (минимум)
- Доступ к сайту только из офисной сети.
- `/srv/supplyhub` — раздаётся read-only; запись — сервисом.
- Имена файлов нормализуются (basename).
- Бэкап: nightly `rsync` и дампы БД.
- Логи — структурные JSON; базовые метрики.

---

## 17) Эскизы реализаций

### 17.1 FastAPI (фрагменты)
```python
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os, uuid

BASE_DIR = "/srv/supplyhub"
app = FastAPI()
app.mount("/files", StaticFiles(directory=BASE_DIR), name="files")

def batch_dir(bid): return os.path.join(BASE_DIR, "batches", bid)

@app.post("/batches")
def create_batch():
    bid = str(uuid.uuid4())
    for sub in ("raw","derived","preview","report"):
        os.makedirs(os.path.join(batch_dir(bid), sub), exist_ok=True)
    return {"batch_id": bid}

@app.post("/batches/{bid}/upload")
async def upload(bid: str, files: list[UploadFile] = File(...)):
    raw = os.path.join(batch_dir(bid), "raw")
    if not os.path.isdir(raw): raise HTTPException(404, "batch not found")
    saved = []
    for uf in files:
        fname = os.path.basename(uf.filename)
        dest = os.path.join(raw, fname)
        with open(dest, "wb") as f:
            while chunk := await uf.read(1024*1024):
                f.write(chunk)
        saved.append(f"/files/batches/{bid}/raw/{fname}")
    return {"saved": saved}

@app.get("/system/status")
def system_status():
    # заглушка: реальные цифры берутся из celery/redis
    return {
        "workers_busy": 0,
        "workers_total": 4,
        "queue_depth": 0,
        "active_batches": 0,
        "active_docs": 0
    }
```
### 17.2 Подсчёт confidence (идея)
```python
def score_field(field, ocr_pages, anchors):
    tokens = []
    if field.get("token_refs"):
        idx = {t["id"]: t for p in ocr_pages for t in p["tokens"]}
        tokens = [idx[t] for t in field["token_refs"] if t in idx]
    elif field.get("bbox") and field.get("page"):
        p = next((p for p in ocr_pages if p["page"] == field["page"]), None)
        if p:
            x0,y0,x1,y1 = field["bbox"]
            for t in p["tokens"]:
                tx0,ty0,tx1,ty1 = t["bbox"]
                if not (tx1 < x0 or tx0 > x1 or ty1 < y0 or ty0 > y1):
                    tokens.append(t)
    ocr_conf = sum(t["conf"] for t in tokens)/len(tokens) if tokens else 0.0
    anchor_bonus = 0.0  # проверка ближайших якорей anchors[field_key]
    format_bonus = 0.1  if is_valid_format(field["value"], field_key=field["key"]) else -0.15
    table_bonus  = 0.0
    raw = ocr_conf * 0.85 + anchor_bonus + format_bonus + table_bonus
    return max(0.0, min(1.0, raw))
```
---

## 18) Роли/ответственности сервисов
- **FastAPI (API-шлюз):** загрузка/статусы/ревью/архив/статическая раздача; эндпоинт `/system/status` для видимости занятости.
- **Celery-воркер:** оркестрация пайплайна, вызовы `dots.ocr` и `json-filler`, подсчёт confidence, валидация, отчёт.
- **dots.ocr (локальная модель):** OCR сканов, выдаёт токены с `conf`, таблицы, bbox — **единственный источник уверенности распознавания**.
- **json-filler (локальная LLM):** заполняет поля целевого JSON по типу документа, возвращает `value` + `token_refs/bbox`, **без** confidence.
- **PostgreSQL:** метаданные партий/доков/полей/валидаций/статусов.

---

## 19) Ключевые принципы
- **Уверенность поля = функция OCR** (token.conf, якоря, формат), *не* LLM.
- **Ревью пользователя — до валидации.** Все поля ниже порога должны быть подтверждены/исправлены.
- **Архив поставок — общий** для сотрудников.
- **dots.ocr и json-filler — локальные сервисы/модели**.
- **Видимость занятости**: пользователи видят, что система «занята», длину очереди и активные задачи.
