"""An ordinary application: PostgreSQL persistence and a small browser UI."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, field_validator


def database():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


@asynccontextmanager
async def lifespan(app):
    with database() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                title TEXT NOT NULL,
                done BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)
    yield


app = FastAPI(title="Tiny Task Board", lifespan=lifespan)


class NewTask(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def strip_title(cls, title):
        if not title.strip():
            raise ValueError("Please enter a task")
        return title.strip()


class UpdateTask(BaseModel):
    done: bool


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
def health():
    with database() as connection:
        connection.execute("SELECT 1")
    return {"status": "ok", "database": "postgresql"}


@app.get("/api/tasks")
def list_tasks():
    with database() as connection:
        return connection.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()


@app.post("/api/tasks", status_code=201)
def create_task(task: NewTask):
    with database() as connection:
        return connection.execute(
            "INSERT INTO tasks (title) VALUES (%s) RETURNING *", (task.title,)
        ).fetchone()


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, task: UpdateTask):
    with database() as connection:
        row = connection.execute(
            "UPDATE tasks SET done = %s WHERE id = %s RETURNING *", (task.done, task_id)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Task not found")
    return row


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    with database() as connection:
        row = connection.execute(
            "DELETE FROM tasks WHERE id = %s RETURNING id", (task_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Task not found")
    return Response(status_code=204)
