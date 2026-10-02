"""Exercise concurrency and stale results with real PostgreSQL and controlled judgments."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

import app as board


@pytest.fixture
def unsorted_tasks(api, test_database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database)
    monkeypatch.setattr(board.app.state, "jev", None, raising=False)
    created = []

    def create(count):
        with board.database() as connection:
            for index in range(count):
                created.append(
                    connection.execute(
                        "INSERT INTO tasks (title) VALUES (%s) RETURNING id",
                        (f"Concurrency test {index}",),
                    ).fetchone()["id"]
                )
        return created

    with ThreadPoolExecutor(max_workers=4) as pool:
        monkeypatch.setattr(board.app.state, "sorting_pool", pool, raising=False)
        try:
            yield create
        finally:
            with board.database() as connection:
                connection.execute("DELETE FROM tasks WHERE id = ANY(%s)", (created,))


def test_parallel_sorting_preserves_concurrent_task_edits(api, unsorted_tasks, monkeypatch):
    ids = unsorted_tasks(8)
    labels = api.get("/api/labels").json()
    release, started = Event(), Event()
    lock = Lock()
    active = peak = calls = 0

    def classify(*_):
        nonlocal active, peak, calls
        with lock:
            calls += 1
            active += 1
            peak = max(peak, active)
            if active == 4:
                started.set()
        try:
            assert release.wait(5)
            return labels[0]["id"], {"status": "sorted"}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(board, "sort_task", classify)
    with ThreadPoolExecutor(max_workers=1) as caller:
        result = caller.submit(board.sort_unsorted, labels)
        try:
            assert started.wait(5), "Expected four simultaneous classifications"
            moved = api.patch(f"/api/tasks/{ids[0]}", json={"label_id": labels[1]["id"]}).json()
            completed = api.patch(f"/api/tasks/{ids[1]}", json={"done": True}).json()
            assert api.delete(f"/api/tasks/{ids[2]}").status_code == 204
            # Even an explicit move back to Unsorted must beat a pending answer.
            manual = api.patch(f"/api/tasks/{ids[3]}", json={"label_id": None}).json()
        finally:
            release.set()
        result.result(timeout=5)

    tasks = {task["id"]: task for task in api.get("/api/tasks").json()}
    assert calls == 8 and peak == 4
    assert tasks[ids[0]] == moved
    assert tasks[ids[1]] == completed
    assert ids[2] not in tasks
    assert tasks[ids[3]] == manual
    assert all(tasks[task_id]["label_id"] == labels[0]["id"] for task_id in ids[4:])


def test_changed_labels_discard_pending_classification(api, unsorted_tasks, monkeypatch):
    task_id = unsorted_tasks(1)[0]
    labels = api.get("/api/labels").json()
    started, release = Event(), Event()

    def classify(*_):
        started.set()
        assert release.wait(5)
        return labels[0]["id"], {"status": "sorted"}

    monkeypatch.setattr(board, "sort_task", classify)
    with ThreadPoolExecutor(max_workers=1) as caller:
        result = caller.submit(board.sort_unsorted, labels)
        try:
            assert started.wait(5)
            with board.database() as connection:
                connection.execute(
                    "UPDATE labels SET description = %s WHERE id = %s",
                    ("Changed during classification", labels[0]["id"]),
                )
        finally:
            release.set()
        try:
            result.result(timeout=5)
            task = next(task for task in api.get("/api/tasks").json() if task["id"] == task_id)
            assert task["label_id"] is None
        finally:
            with board.database() as connection:
                connection.execute(
                    "UPDATE labels SET description = %s WHERE id = %s",
                    (labels[0]["description"], labels[0]["id"]),
                )


def test_unavailable_sorting_still_saves_label_edits(api, unsorted_tasks, monkeypatch):
    task_id = unsorted_tasks(1)[0]
    labels = api.get("/api/labels").json()
    changed = [{**labels[0], "description": "Updated category meaning"}, *labels[1:]]
    monkeypatch.setattr(board, "sort_task", lambda *_: (None, {"status": "unavailable"}))
    try:
        saved = board.save_labels(board.LabelList(labels=changed))
        assert saved == changed
        task = next(task for task in api.get("/api/tasks").json() if task["id"] == task_id)
        assert task["label_id"] is None and task["classification"] == {"status": "unsorted"}
    finally:
        board.save_labels(board.LabelList(labels=labels))


def test_unchanged_or_reordered_labels_do_not_resort(api, unsorted_tasks, monkeypatch):
    unsorted_tasks(1)
    labels = api.get("/api/labels").json()

    def unexpected(*_):
        pytest.fail("Unchanged label meanings should not re-sort tasks")

    monkeypatch.setattr(board, "sort_task", unexpected)
    try:
        board.save_labels(board.LabelList(labels=labels))
        board.save_labels(board.LabelList(labels=list(reversed(labels))))
    finally:
        board.save_labels(board.LabelList(labels=labels))
