Use uv and preserve both lockfiles. Keep runner/ independent of the sample app:
no application imports, database setup, project-specific dependencies or tests.
The app owns those through example/Dockerfile and example/compose.yaml.

Run `uv run --frozen ruff check .` for Python lint. App tests require the running
Compose stack and use real HTTP and PostgreSQL; see example/README.md.

The demo.sh defaults target personal Modal workspace drchrislevy/main. Remote
runs clone published Git commits; they do not upload local uncommitted changes.
Always collect artifacts and terminate VMs. Keep generated run logs in artifacts/.
