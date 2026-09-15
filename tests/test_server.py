import pytest
from fastapi.testclient import TestClient
from backend.server import app


def test_api_status():
    client = TestClient(app)
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "mode" in data
    assert "telemetry" in data


def test_api_set_mode():
    client = TestClient(app)
    response = client.post("/api/mode", json={"mode": "simulator", "condition": "tachycardia"})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "simulator"
    assert data["condition"] == "tachycardia"


def test_api_set_filter():
    client = TestClient(app)
    response = client.post("/api/filter", json={"filter_mode": "diagnostic", "notch_enabled": True})
    assert response.status_code == 200
    data = response.json()
    assert data["filter_mode"] == "diagnostic"
    assert data["notch_enabled"] is True


def test_api_recording_flow():
    client = TestClient(app)
    res_start = client.post("/api/record/start")
    assert res_start.status_code == 200

    res_stop = client.post("/api/record/stop")
    assert res_stop.status_code == 200
    assert "duration_sec" in res_stop.json()

    res_export = client.get("/api/record/export?format=csv")
    assert res_export.status_code == 200
    assert "text/csv" in res_export.headers.get("content-type", "")
