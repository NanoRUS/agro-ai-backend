# AI-Агроном — backend

FastAPI-backend для диагностики болезней растений по фото.

---

## Быстрый старт (локально)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8080
# Swagger: http://localhost:8080/docs
```

---

## Деплой на Railway (рекомендуется)

Railway автоматически подхватывает `Dockerfile` и `railway.toml`.

### Шаги

1. **Создай проект на Railway**
   ```
   railway login
   railway init   # или через web: railway.app → New Project → Deploy from GitHub
   ```

2. **Добавь PostgreSQL**
   Railway Dashboard → New → Database → Add PostgreSQL
   Railway автоматически проставит `DATABASE_URL` в переменные окружения.

3. **Установи переменные окружения**
   Railway Dashboard → Variables:

   | Переменная | Значение | Обязательно |
   |-----------|---------|------------|
   | `SECRET_KEY` | случайная строка 32+ символа | ✅ |
   | `DEBUG` | `false` | ✅ |
   | `ALLOWED_ORIGINS` | URL фронтенда (напр. `https://agro.vercel.app`) | ✅ |
   | `DATABASE_URL` | заполняется автоматически PostgreSQL плагином | ✅ |

   Генерация SECRET_KEY:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

4. **Deploy**
   ```bash
   railway up
   # или push в GitHub ветку, связанную с Railway
   ```

5. **Проверь**
   ```bash
   curl https://your-app.railway.app/health
   # → {"status":"ok","version":"1.0.0"}

   curl https://your-app.railway.app/health/db
   # → {"status":"ok","db":"connected"}
   ```

### Альтернатива: Render

1. New Web Service → Connect GitHub repo → Docker runtime
2. Set env vars (те же, что Railway)
3. Health Check Path: `/health`

### Альтернатива: VPS (Docker)

```bash
# На сервере
docker build -t agro-api .
docker run -d \
  --name agro-api \
  -p 8080:8080 \
  -e SECRET_KEY=your-secret \
  -e DEBUG=false \
  -e DATABASE_URL=postgresql+asyncpg://... \
  -e ALLOWED_ORIGINS=https://your-frontend.com \
  agro-api
```

---

## Деплой frontend на Vercel

Репозиторий `agro-ai-frontend`.

1. Подключи GitHub repo на [vercel.com](https://vercel.com)
2. Framework: Next.js (автодетект)
3. **Environment Variables → Add:**

   | Переменная | Значение |
   |-----------|---------|
   | `NEXT_PUBLIC_API_URL` | URL Railway backend (напр. `https://agro-api.railway.app`) |

4. Deploy → Vercel даст URL вида `https://agro-ai-xxx.vercel.app`
5. Скопируй этот URL → вставь в Railway `ALLOWED_ORIGINS`

---

## Production checklist

```
[ ] SECRET_KEY установлен (не dev-secret-key)
[ ] DEBUG=false
[ ] DATABASE_URL → PostgreSQL (не SQLite)
[ ] ALLOWED_ORIGINS → домен Vercel
[ ] NEXT_PUBLIC_API_URL → URL Railway
[ ] /health → {"status":"ok"}
[ ] /health/db → {"status":"ok","db":"connected"}
[ ] POST /api/v1/demo/cases/tomato_phytophthora_rain → 200 с топ-кейсом
[ ] Frontend открывается, демо-сценарий работает
```

### Ручная проверка `/analyze`

```bash
curl -X POST https://your-api.railway.app/api/v1/analyze \
  -F 'questionnaire_json={"crop_type":"tomato","questionnaire":{"growing_environment":"open_field","plant_stage":"fruiting","days_since_problem_started":4,"watering_frequency":"every_2_days","soil_moisture":"wet","has_spots":true,"has_dark_spots":true,"had_cold_nights":true,"had_recent_rain":true,"has_fruit_rot":true,"has_stem_darkening":true,"has_white_powder":false,"has_holes_in_leaves":false,"has_webbing":false,"insects_visible":false,"has_yellowing_lower_leaves":false,"has_uniform_yellowing":false,"has_leaf_edge_burn":false,"has_curled_leaves":false,"has_wilting":false,"has_blossom_end_rot":false,"has_slow_growth":false,"had_heat_stress":false,"recently_transplanted":false,"recently_fertilized":false}}'
```

Ожидаемый ответ: `top_issues[0].id == "phytophthora"`, `urgency.level == "critical"`.

---

## API endpoints

| Method | Path | Описание |
|--------|------|---------|
| GET | `/health` | Healthcheck |
| GET | `/health/db` | Healthcheck с проверкой БД |
| POST | `/api/v1/analyze` | Анализ фото + анкета → диагноз |
| GET | `/api/v1/analysis/{id}` | Сохранённый результат |
| POST | `/api/v1/generate-video` | Запустить генерацию видеоразбора |
| GET | `/api/v1/video/{job_id}` | Статус видео-задачи |
| POST | `/api/v1/follow-up` | Повторная диагностика |
| GET | `/api/v1/demo/cases` | Список демо-кейсов |
| GET | `/api/v1/demo/cases/{id}` | Запустить демо-кейс |
| POST | `/api/v1/debug/analyze` | Debug scoring (только DEBUG=true) |
| GET | `/api/v1/debug/analysis/{id}` | Debug анализа (только DEBUG=true) |

Swagger доступен только при `DEBUG=true`: `/docs`

---

## Тестирование и калибровка

```bash
.venv/bin/python -m pytest tests/ -v          # все тесты (66 шт)
.venv/bin/python calibrate.py                  # 15/15 PASS
.venv/bin/python calibrate.py --case tomato_phytophthora_rain   # debug breakdown
.venv/bin/python calibrate.py --export results.json             # JSON экспорт
```

## Где менять правила

```
app/rules/issue_catalog.json    — веса, сигналы, тексты (20 болезней)
app/rules/crops/tomato.json     — overrides и stage_modifiers для томата
app/rules/crops/*.json          — аналогично для других культур
```
