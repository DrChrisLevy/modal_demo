# Tiny Task Board

A small FastAPI application with a browser UI and PostgreSQL persistence.
This directory has no Modal dependency. It runs with ordinary Docker Compose.

```bash
docker compose up --build --wait
# Open http://localhost:8000
docker compose exec -T web uv run --frozen pytest -q
docker compose exec -T web uv run --frozen ruff check .
docker compose down
```

The database is a Compose named volume. `docker compose down` keeps it;
`docker compose down --volumes` removes it. The demo database credentials are
local development placeholders. PostgreSQL has no published host port.

The source is mounted at `/app`. Restart `web` after Python changes:

```bash
docker compose restart web
docker compose up --wait
```

Static HTML is read on each request. The uv environment is at `/opt/venv`, outside
the source mount. Dependency changes require `docker compose up --build --wait`.
Tests call the running HTTP application and its actual database; no mocks or
SQLite substitute. Test-created rows are removed afterward.

API: `GET /health`, `GET /api/tasks`, `POST /api/tasks` with `{"title":"..."}`,
and `PATCH /api/tasks/{id}` with `{"done":true}`. Interactive docs: `/docs`.
