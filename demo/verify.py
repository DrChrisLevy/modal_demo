"""Independent HTTPS checks for the sample app. The runner never imports this."""

import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def check(url, *, filters=False):
    def request(path, body=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(
            url.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=30) as response:
            return json.load(response)

    assert request("/health") == {"status": "ok", "database": "postgresql"}
    with urlopen(url, timeout=30) as response:
        assert "Tiny Task Board" in response.read().decode()
    suffix = uuid4().hex[:8]
    opened = request("/api/tasks", {"title": f"Review the demo — {suffix}"})
    done = request("/api/tasks", {"title": f"Run on a fresh VM — {suffix}"})
    done = request(f"/api/tasks/{done['id']}", {"done": True}, "PATCH")
    tasks = request("/api/tasks")
    assert opened in tasks and done in tasks and done["done"]
    result = {
        "https": True,
        "database": "postgresql",
        "create_list_complete": True,
        "task_ids": [opened["id"], done["id"]],
    }
    if filters:
        assert opened in request("/api/tasks?status=open")
        assert done not in request("/api/tasks?status=open")
        assert done in request("/api/tasks?status=done")
        assert opened not in request("/api/tasks?status=done")
        assert opened in request("/api/tasks?status=all")
        request(f"/api/tasks/{opened['id']}", {"done": True}, "PATCH")
        assert opened["id"] not in {task["id"] for task in request("/api/tasks?status=open")}
        try:
            request("/api/tasks?status=invalid")
        except HTTPError as error:
            assert error.code == 422
        else:
            raise AssertionError("Invalid status was accepted")
        result["filters"] = True
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--filters", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.url, filters=args.filters), indent=2))
