# Task board checks

With the Compose app running, run the real HTTP/PostgreSQL integration tests and lint:

```sh
docker compose exec -T web uv run --frozen pytest -q
docker compose exec -T web uv run --frozen ruff check .
```

From `example/`, run the optional Chromium regression checks on the host:

```sh
uv run --with playwright playwright install --with-deps chromium
uv run --with playwright python tests/browser_checks.py
```

Set `APP_URL` if the app is not at `http://localhost:8000`. Browser checks create a
uniquely named task and clean it up. They cover creation, completion/reopening,
confirmation cancellation and focus, deletion failure/retry and persistence,
loading failure/retry, empty state, and mobile/desktop overflow. Playwright is an
optional test tool, not an application dependency.

Deletion uses `DELETE /api/tasks/{id}`: 204 with an empty body on success, 404 with
`{"detail":"Task not found"}` if already deleted or missing, and 422 for invalid IDs.
