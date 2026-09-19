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


def test_task_status_filters(api, title):
    open_task = api.post("/api/tasks", json={"title": title + "-open"}).json()
    done_task = api.post("/api/tasks", json={"title": title + "-done"}).json()
    api.patch(f"/api/tasks/{done_task['id']}", json={"done": True})

    assert open_task in api.get("/api/tasks?status=open").json()
    assert done_task not in api.get("/api/tasks?status=open").json()
    assert done_task | {"done": True} in api.get("/api/tasks?status=done").json()
    assert open_task not in api.get("/api/tasks?status=done").json()


def test_completed_task_disappears_from_open_filter(api, title):
    task = api.post("/api/tasks", json={"title": title}).json()
    assert task in api.get("/api/tasks?status=open").json()

    response = api.patch(f"/api/tasks/{task['id']}", json={"done": True})

    assert response.status_code == 200
    assert task["id"] not in {
        item["id"] for item in api.get("/api/tasks?status=open").json()
    }


def test_reject_invalid_task_status(api):
    assert api.get("/api/tasks?status=blocked").status_code == 422


@pytest.mark.parametrize("invalid", ["", "   ", "x" * 201])
def test_reject_invalid_title(api, invalid):
    assert api.post("/api/tasks", json={"title": invalid}).status_code == 422


def test_missing_task(api):
    assert api.patch("/api/tasks/2147483647", json={"done": True}).status_code == 404


def test_sql_characters_are_data(api, title):
    title += "'); DROP TABLE tasks; --"
    response = api.post("/api/tasks", json={"title": title})
    assert response.status_code == 201 and response.json()["title"] == title
    assert api.get("/health").status_code == 200
