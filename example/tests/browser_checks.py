"""Browser regression checks against a running app.

Run: uv run --with playwright python tests/browser_checks.py
Install Chromium first: uv run --with playwright playwright install --with-deps chromium
"""

import os
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(base_url=os.getenv("APP_URL", "http://localhost:8000"))
    title = f"browser-{uuid4().hex}"
    task_id = None
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto("/")
        expect(page.locator("#load-state")).to_be_hidden()
        page.get_by_label("New task", exact=True).fill(title)
        page.locator("#add-form button").click()
        row = page.locator("li").filter(has_text=title)
        expect(row).to_be_visible()
        task_id = next(
            task["id"] for task in page.request.get("/api/tasks").json() if task["title"] == title
        )
        row.get_by_role("checkbox").check()
        expect(row).to_have_class("done")
        row.get_by_role("checkbox").uncheck()
        expect(row).not_to_have_class("done")
        for width in [375, 1280]:
            page.set_viewport_size({"width": width, "height": 850})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        row.get_by_role("button").click()
        expect(page.get_by_role("button", name="Keep task")).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.locator("#delete-dialog")).not_to_be_visible()
        expect(row.get_by_role("button")).to_be_focused()
        row.get_by_role("button").click()
        page.get_by_role("button", name="Keep task").click()
        expect(row).to_be_visible()
        row.get_by_role("button").click()
        endpoint = f"**/api/tasks/{task_id}"
        page.route(endpoint, lambda route: route.fulfill(status=500, body="failure"))
        page.locator("#confirm-delete").click()
        expect(page.locator("#delete-error")).to_contain_text("try again")
        expect(row).to_be_visible()
        page.unroute(endpoint)
        page.locator("#confirm-delete").click()
        expect(row).to_have_count(0)
        expect(page.locator("#delete-dialog")).not_to_be_visible()
        page.reload()
        expect(page.locator("#load-state")).to_be_hidden()
        expect(row).to_have_count(0)
        page.route("**/api/tasks", lambda route: route.fulfill(status=500, body="failure"))
        page.reload()
        expect(page.locator("#load-error")).to_be_visible()
        page.unroute("**/api/tasks")
        page.get_by_role("button", name="Try again").click()
        expect(page.locator("#load-error")).to_be_hidden()
        expect(page.locator("#load-state")).to_be_hidden()
        page.route("**/api/tasks", lambda route: route.fulfill(json=[]))
        page.reload()
        expect(page.locator("#empty")).to_be_visible()
        assert not errors, errors
        print(
            "Browser checks passed: create, complete, reopen, cancel, delete, errors, empty, layout"
        )
    finally:
        if task_id is not None:
            page.request.delete(f"/api/tasks/{task_id}")
        browser.close()
