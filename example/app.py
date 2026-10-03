"""A small task board: PostgreSQL persistence and Jev-powered sorting."""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator, model_validator
from typesafe_sdk import RetryPolicy, TypeSafeClient

from sorting import sort_task

ROOT = Path(__file__).parent
STARTER_LABELS = [
    ("Work", "Professional tasks, meetings, projects, and work communications."),
    ("Home", "Household chores, repairs, family plans, and things to do at home."),
    ("Learning", "Reading, studying, practicing skills, and taking courses."),
    ("Errands", "Shopping, pickups, drop-offs, and appointments outside the home."),
]


def database():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


@asynccontextmanager
async def lifespan(app):
    with database() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                position INTEGER NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                title TEXT NOT NULL,
                done BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)
        connection.execute("""
            ALTER TABLE tasks
                ADD COLUMN IF NOT EXISTS label_id INTEGER REFERENCES labels ON DELETE SET NULL,
                ADD COLUMN IF NOT EXISTS classification JSONB NOT NULL
                    DEFAULT '{"status":"unsorted"}'
        """)
        if not connection.execute("SELECT 1 FROM labels LIMIT 1").fetchone():
            for position, (name, description) in enumerate(STARTER_LABELS):
                connection.execute(
                    "INSERT INTO labels (name, description, position) VALUES (%s, %s, %s)",
                    (name, description, position),
                )
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    app.state.jev = (
        TypeSafeClient(
            api_key=api_key, model="jev-latest", timeout=10, retry=RetryPolicy(max_retries=1)
        )
        if api_key
        else None
    )
    app.state.sorting_pool = ThreadPoolExecutor(max_workers=4)
    try:
        yield
    finally:
        app.state.sorting_pool.shutdown(wait=True)
        if app.state.jev is not None:
            app.state.jev.close()


app = FastAPI(title="Tiny Task Board", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class NewTask(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, title):
        return title.strip() if isinstance(title, str) else title


class UpdateTask(BaseModel):
    done: bool | None = None
    label_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def has_change(self):
        if self.done is None and "label_id" not in self.model_fields_set:
            raise ValueError("Choose a task status or label to update")
        return self


class Label(BaseModel):
    id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1, max_length=240)

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class LabelList(BaseModel):
    labels: list[Label] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_labels(self):
        names = [label.name.casefold() for label in self.labels]
        ids = [label.id for label in self.labels if label.id is not None]
        if len(set(names)) != len(names) or "unsorted" in names:
            raise ValueError("Use unique label names; Unsorted is reserved")
        if len(set(ids)) != len(ids):
            raise ValueError("Each label may only appear once")
        return self


def read_labels(connection):
    return connection.execute("SELECT * FROM labels ORDER BY position, id").fetchall()


def classify(title):
    with database() as connection:
        labels = read_labels(connection)
    return sort_task(title, labels, app.state.jev)


def existing_label(connection, label_id):
    if label_id is not None:
        # A label may have been removed while Jev was answering.
        return connection.execute(
            "SELECT id FROM labels WHERE id = %s FOR KEY SHARE", (label_id,)
        ).fetchone()
    return None


def sort_unsorted(labels):
    with database() as connection:
        tasks = connection.execute(
            "SELECT id, title, xmin::text AS version FROM tasks WHERE label_id IS NULL AND NOT done"
        ).fetchall()

    def sort_and_apply(task):
        label_id, classification = sort_task(task["title"], labels, app.state.jev)
        if classification["status"] == "unavailable":
            return
        with database() as connection:
            # Hold locks only while applying a result, never during the API call.
            connection.execute("LOCK TABLE labels IN SHARE MODE")
            if read_labels(connection) != labels:
                return  # Another save changed the categories used for this answer.
            connection.execute(
                "UPDATE tasks SET label_id = %s, classification = %s "
                "WHERE id = %s AND label_id IS NULL AND NOT done AND xmin::text = %s",
                (label_id, Jsonb(classification), task["id"], task["version"]),
            )

    # The shared pool bounds re-sorting across simultaneous label saves, too.
    list(app.state.sorting_pool.map(sort_and_apply, tasks))


@app.get("/")
def index():
    html = (ROOT / "static" / "index.html").read_text()
    for asset in ("app.js", "style.css"):
        version = hashlib.sha256((ROOT / "static" / asset).read_bytes()).hexdigest()[:16]
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={version}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/health")
def health():
    with database() as connection:
        connection.execute("SELECT 1")
    return {"status": "ok", "database": "postgresql"}


@app.get("/api/labels")
def list_labels():
    with database() as connection:
        return read_labels(connection)


@app.put("/api/labels")
def save_labels(payload: LabelList):
    with database() as connection:
        connection.execute("LOCK TABLE labels IN SHARE ROW EXCLUSIVE MODE")
        current = {row["id"]: row for row in read_labels(connection)}
        retained = {label.id for label in payload.labels if label.id is not None}
        if not retained <= current.keys():
            raise HTTPException(409, "Labels changed in another window. Reopen the editor.")
        changed = any(
            label.id is None
            or (label.name, label.description)
            != (current[label.id]["name"], current[label.id]["description"])
            for label in payload.labels
        )
        for position, label in enumerate(payload.labels):
            if label.id is None:
                connection.execute(
                    "INSERT INTO labels (name, description, position) VALUES (%s, %s, %s)",
                    (label.name, label.description, position),
                )
            else:
                connection.execute(
                    "UPDATE labels SET name = %s, description = %s, position = %s WHERE id = %s",
                    (label.name, label.description, position, label.id),
                )
        for removed in current.keys() - retained:
            connection.execute("DELETE FROM labels WHERE id = %s", (removed,))
        labels = read_labels(connection)
    if changed:
        sort_unsorted(labels)
    return labels


@app.get("/api/tasks")
def list_tasks():
    with database() as connection:
        return connection.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()


@app.post("/api/tasks", status_code=201)
def create_task(task: NewTask):
    label_id, classification = classify(task.title)
    with database() as connection:
        label = existing_label(connection, label_id)
        return connection.execute(
            "INSERT INTO tasks (title, label_id, classification) VALUES (%s, %s, %s) RETURNING *",
            (task.title, label["id"] if label else None, Jsonb(classification)),
        ).fetchone()


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, task: UpdateTask):
    with database() as connection:
        if task.label_id is not None and not existing_label(connection, task.label_id):
            raise HTTPException(422, "Choose an existing label")
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = %s FOR UPDATE", (task_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Task not found")
        if task.done is not None:
            row["done"] = task.done
        if "label_id" in task.model_fields_set:
            row["label_id"] = task.label_id
            row["classification"] = {"status": "manual"}
        return connection.execute(
            "UPDATE tasks SET done = %s, label_id = %s, classification = %s "
            "WHERE id = %s RETURNING *",
            (row["done"], row["label_id"], Jsonb(row["classification"]), task_id),
        ).fetchone()


@app.post("/api/tasks/{task_id}/sort")
def retry_sort(task_id: int):
    with database() as connection:
        task = connection.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
    if task is None:
        raise HTTPException(404, "Task not found")
    label_id, classification = classify(task["title"])
    with database() as connection:
        label = existing_label(connection, label_id)
        row = connection.execute(
            "UPDATE tasks SET label_id = %s, classification = %s WHERE id = %s RETURNING *",
            (label["id"] if label else None, Jsonb(classification), task_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Task not found")
    return row


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    with database() as connection:
        if not connection.execute(
            "DELETE FROM tasks WHERE id = %s RETURNING id", (task_id,)
        ).fetchone():
            raise HTTPException(404, "Task not found")
