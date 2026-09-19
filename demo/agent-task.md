You are working inside a fresh Modal VM Sandbox on a private demo repository.
The repository is /workspace/repo. A new branch has already been checked out for
you. The ordinary Docker Compose project is in example/. It is already running;
the app is at http://localhost:8000 and PostgreSQL is a real Compose service.

Add task filtering to the Tiny Task Board:
- GET /api/tasks accepts status=all|open|done, defaulting to all. An invalid
  status returns HTTP 422. Filter in the SQL query, with safe parameters.
- Add accessible All, Open, and Done buttons to the page. Clearly indicate the
  selected filter, preserve it when adding/completing tasks, and show a useful
  empty state for the current view. Keep the existing plain HTML/JS style.
- Add focused HTTP integration tests that use real PostgreSQL, including invalid
  status and a completed task disappearing from the open list.
- Update example/README.md to describe the feature and a curl example.

First inspect the app and call its real HTTP endpoints. Run its baseline tests.
Change only example/app.py, example/static/index.html, example/README.md and
example/tests/ files. Do not modify existing tests to weaken assertions.
Do not change runner/, demo/, dependency files, Dockerfile, or compose.yaml.
There are no subagents needed. Do not inspect credentials or print environment
variables. Do not read anything outside the repository except the provided
/artifacts destination. Use the configured git and gh authentication as-is.

Restart the application as needed and run:
  cd /workspace/repo/example
  docker compose restart web
  docker compose up --wait
  docker compose exec -T web uv run --frozen pytest -q
  docker compose exec -T web uv run --frozen ruff check .
Also exercise the new feature against the real HTTP API yourself.

Commit your changes on the current branch and push only that branch to origin.
Open ONE draft pull request against main using gh pr create --draft. Write its
body to /artifacts/pr-body.md and use --body-file. Describe the concrete behavior
change in a short paragraph plus the verification you actually performed.
Write the resulting PR URL alone to /artifacts/pr-url.txt. Do not merge the PR,
modify main, change repository settings, or touch other repositories.
Finally summarize the change and the tests you actually ran.
