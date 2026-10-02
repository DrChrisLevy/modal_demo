"""Exercise real HTTP, PostgreSQL, and Jev without touching the preview board."""

import os
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def api(tmp_path_factory):
    if not os.getenv("TYPESAFE_API_KEY"):
        pytest.fail(
            "The integration suite requires TYPESAFE_API_KEY; no live Jev tests are skipped."
        )
    original = os.environ["DATABASE_URL"]
    name = f"task_board_test_{uuid4().hex}"
    with psycopg.connect(original, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log_path = tmp_path_factory.mktemp("api") / "server.log"
    process = None
    try:
        with log_path.open("w+") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                env={**os.environ, "DATABASE_URL": make_conninfo(original, dbname=name)},
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        if client.get("/health").is_success:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    pytest.fail(f"Test API did not start:\n{log_path.read_text()}")
                yield client
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        with psycopg.connect(original, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def task_factory(api):
    created = []

    def create(title):
        response = api.post("/api/tasks", json={"title": title})
        assert response.status_code == 201, response.text
        task = response.json()
        created.append(task["id"])
        return task

    yield create
    for task_id in created:
        api.delete(f"/api/tasks/{task_id}")
