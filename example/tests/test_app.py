"""Integration tests against real HTTP, a private PostgreSQL database, and Jev."""

import pytest


def test_health_and_page(api):
    assert api.get("/health").json() == {"status": "ok", "database": "postgresql"}
    page = api.get("/")
    assert page.status_code == 200 and "Tiny Task Board" in page.text
    for asset in ("app.js", "style.css"):
        assert api.get(f"/static/{asset}").status_code == 200


def test_create_read_complete_and_reopen(api, task_factory):
    task = task_factory("  Prepare the slides for the team meeting  ")
    assert task["title"] == "Prepare the slides for the team meeting"
    assert task["done"] is False
    assert task in api.get("/api/tasks").json()
    for done in (True, False):
        updated = api.patch(f"/api/tasks/{task['id']}", json={"done": done})
        assert updated.status_code == 200 and updated.json()["done"] is done
        assert updated.json() in api.get("/api/tasks").json()


@pytest.mark.parametrize("invalid", ["", "   ", "x" * 201])
def test_reject_invalid_title(api, invalid):
    assert api.post("/api/tasks", json={"title": invalid}).status_code == 422


def test_missing_task(api):
    assert api.patch("/api/tasks/2147483647", json={"done": True}).status_code == 404
    assert api.post("/api/tasks/2147483647/sort").status_code == 404
    assert api.delete("/api/tasks/2147483647").status_code == 404


def test_sql_and_html_characters_are_data(api, task_factory):
    text = "<script>alert(1)</script> '); DROP TABLE tasks; --"
    task = task_factory(text)
    assert task["title"] == text
    assert task in api.get("/api/tasks").json()
    assert api.get("/health").status_code == 200


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Prepare the quarterly report for my manager", "Work"),
        ("Vacuum the living room and clean the kitchen", "Home"),
        ("Study chapter three of my Spanish textbook", "Learning"),
        ("Pick up milk and bread from the supermarket", "Errands"),
    ],
)
def test_real_jev_sorts_tasks(api, task_factory, title, expected):
    labels = {label["id"]: label["name"] for label in api.get("/api/labels").json()}
    task = task_factory(title)
    assert labels.get(task["label_id"]) == expected, task
    result = task["classification"]
    assert result["status"] == "sorted"
    assert result["model"].startswith("jev-")
    assert 0 <= result["confidence"] <= 1
    assert sum(result["probabilities"].values()) == pytest.approx(1, abs=0.01)
    assert result["duration_ms"] >= 0


def test_manual_move_and_resort(api, task_factory):
    labels = {label["name"]: label["id"] for label in api.get("/api/labels").json()}
    task = task_factory("Buy milk at the grocery store")
    path = f"/api/tasks/{task['id']}"
    moved = api.patch(path, json={"label_id": labels["Work"]}).json()
    assert moved["label_id"] == labels["Work"]
    assert moved["classification"] == {"status": "manual"}
    assert api.patch(path, json={"label_id": 2147483647}).status_code == 422
    assert api.patch(path, json={}).status_code == 422
    assert api.patch(path, json={"label_id": None}).json()["label_id"] is None
    sorted_again = api.post(path + "/sort").json()
    assert sorted_again["label_id"] == labels["Errands"]
    assert sorted_again["classification"]["status"] == "sorted"


def test_editable_labels_drive_jev_and_deletion_preserves_tasks(api, task_factory):
    original = api.get("/api/labels").json()
    custom = {
        "name": "Gardening",
        "description": "Growing plants, watering flowers, and tending a garden.",
    }
    added = api.put("/api/labels", json={"labels": [*original, custom]})
    assert added.status_code == 200
    garden = added.json()[-1]
    try:
        task = task_factory("Water the rose bushes in the garden")
        assert task["label_id"] == garden["id"], task
        renamed = {**garden, "name": "Garden", "description": "Gardening, flowers, and plant care."}
        assert api.put("/api/labels", json={"labels": [*original, renamed]}).status_code == 200
        assert (
            next(item for item in api.get("/api/tasks").json() if item["id"] == task["id"])[
                "label_id"
            ]
            == garden["id"]
        )
        assert api.put("/api/labels", json={"labels": original}).status_code == 200
        retained = next(item for item in api.get("/api/tasks").json() if item["id"] == task["id"])
        assert retained["label_id"] is None and retained["title"] == task["title"]
    finally:
        api.put("/api/labels", json={"labels": original})


@pytest.mark.parametrize(
    "labels",
    [
        [],
        [{"name": " ", "description": "Stuff"}],
        [{"name": "Work", "description": " "}],
        [{"name": "Unsorted", "description": "Reserved"}],
        [{"name": "Work", "description": "A"}, {"name": "work", "description": "B"}],
        [{"name": "x" * 33, "description": "Too long"}],
        [{"name": str(index), "description": "Too many labels"} for index in range(9)],
    ],
)
def test_label_validation_is_atomic(api, labels):
    before = api.get("/api/labels").json()
    assert api.put("/api/labels", json={"labels": labels}).status_code == 422
    assert api.get("/api/labels").json() == before


def test_unknown_label_id_is_rejected(api):
    before = api.get("/api/labels").json()
    labels = [{**before[0], "id": 2147483647}, *before[1:]]
    assert api.put("/api/labels", json={"labels": labels}).status_code == 409
    assert api.get("/api/labels").json() == before


def test_delete_task(api, task_factory):
    task = task_factory("Pick up the dry cleaning")
    assert api.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert all(item["id"] != task["id"] for item in api.get("/api/tasks").json())
