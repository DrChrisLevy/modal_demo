from __future__ import annotations

import pytest


def test_frontend_and_static_assets_are_served(api_client) -> None:
    response = api_client.get("/")
    assert response.status_code == 200
    assert "Fieldwork" in response.text
    assert 'id="analyze-form"' in response.text
    for path, content_type in (("/static/app.js", "javascript"), ("/static/style.css", "text/css")):
        asset = api_client.get(path)
        assert asset.status_code == 200
        assert content_type in asset.headers["content-type"]


@pytest.mark.model
@pytest.mark.xdist_group(name="text")
def test_library_lists_persisted_assets(api_client, positive_text: str) -> None:
    created = api_client.post(
        "/v1/assets/text", json={"text": positive_text, "title": "Library test"}
    )
    assert created.status_code == 200
    response = api_client.get("/v1/assets?limit=100")
    assert response.status_code == 200
    asset = next(item for item in response.json() if item["id"] == created.json()["id"])
    assert asset["title"] == "Library test"
    assert asset["analysis"]["embedding"]["dimensions"] == 384
    assert api_client.get(f"/v1/assets/{asset['id']}").json() == asset


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_library_rejects_invalid_limits(api_client, limit: int) -> None:
    assert api_client.get(f"/v1/assets?limit={limit}").status_code == 422
