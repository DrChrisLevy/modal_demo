"""Integration tests: real HTTP to the running app and its real PostgreSQL."""

import os
from uuid import uuid4

import httpx
import psycopg
import pytest


@pytest.fixture
def api():
    with httpx.Client(base_url=os.getenv("APP_URL", "http://localhost:8000")) as client:
        yield client


@pytest.fixture
def title():
    prefix = f"test-{uuid4().hex}"
    yield prefix
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("DELETE FROM tasks WHERE title LIKE %s", (prefix + "%",))


def test_health_and_page(api):
    assert api.get("/health").json() == {"status": "ok", "database": "postgresql"}
    page = api.get("/")
    assert page.status_code == 200 and "Tiny Task Board" in page.text


def test_create_read_complete_and_reopen(api, title):
    response = api.post("/api/tasks", json={"title": title})
    assert response.status_code == 201
    task = response.json()
    assert task["title"] == title and task["done"] is False
    assert task in api.get("/api/tasks").json()
    for done in [True, False]:
        updated = api.patch(f"/api/tasks/{task['id']}", json={"done": done})
        assert updated.status_code == 200 and updated.json()["done"] is done
        assert updated.json() in api.get("/api/tasks").json()


@pytest.mark.parametrize("invalid", ["", "   ", "x" * 201])
def test_reject_invalid_title(api, invalid):
    assert api.post("/api/tasks", json={"title": invalid}).status_code == 422


def test_missing_task(api):
    assert api.patch("/api/tasks/2147483647", json={"done": True}).status_code == 404


@pytest.mark.parametrize("done", [False, True])
def test_delete_task(api, title, done):
    task = api.post("/api/tasks", json={"title": title}).json()
    other = api.post("/api/tasks", json={"title": title + " keep"}).json()
    path = f"/api/tasks/{task['id']}"
    if done:
        assert api.patch(path, json={"done": True}).status_code == 200

    response = api.delete(path)
    assert response.status_code == 204
    assert response.content == b""
    remaining = api.get("/api/tasks").json()
    assert all(item["id"] != task["id"] for item in remaining)
    assert other in remaining
    assert api.delete(path).status_code == 404
    assert api.patch(path, json={"done": True}).status_code == 404


def test_delete_missing_task(api):
    response = api.delete("/api/tasks/2147483647")
    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}


def test_sql_characters_are_data(api, title):
    title += "'); DROP TABLE tasks; --"
    response = api.post("/api/tasks", json={"title": title})
    assert response.status_code == 201 and response.json()["title"] == title
    assert api.get("/health").status_code == 200
