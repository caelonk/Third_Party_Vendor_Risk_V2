"""User preference tests: theme + the 5-widget dashboard cap."""
from app.models.user import MAX_DASHBOARD_WIDGETS

API = "/api/v1"


def test_default_preferences(api):
    client, _ = api.register("p@example.com")
    prefs = client.get(f"{API}/me/preferences").json()
    assert prefs["theme"] == "system"
    assert prefs["dashboard_layout"] == []


def test_update_theme_and_layout(api):
    client, _ = api.register("q@example.com")
    resp = client.put(
        f"{API}/me/preferences",
        json={
            "theme": "dark",
            "dashboard_layout": [
                {"type": "tier_distribution", "w": 2, "h": 1},
                {"type": "risk_heatmap", "expanded": True},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "dark"
    assert [w["type"] for w in body["dashboard_layout"]] == ["tier_distribution", "risk_heatmap"]


def test_widget_columns_are_saved_and_validated(api):
    client, _ = api.register("cols@example.com")
    url = f"{API}/me/preferences"
    saved = client.put(
        url,
        json={
            "dashboard_layout": [
                {"type": "kev_exposure", "col": 0},
                {"type": "risk_heatmap", "col": 1},
                {"type": "watchlist"},  # saved before columns existed
            ]
        },
    )
    assert saved.status_code == 200
    assert [w["col"] for w in client.get(url).json()["dashboard_layout"]] == [0, 1, None]
    # There are only two columns.
    assert client.put(url, json={"dashboard_layout": [{"type": "x", "col": 2}]}).status_code == 422
    assert client.put(url, json={"dashboard_layout": [{"type": "x", "col": -1}]}).status_code == 422


def test_dashboard_widget_cap_enforced(api):
    client, _ = api.register("r@example.com")
    too_many = [{"type": f"w{i}"} for i in range(MAX_DASHBOARD_WIDGETS + 1)]
    resp = client.put(f"{API}/me/preferences", json={"dashboard_layout": too_many})
    assert resp.status_code == 422
