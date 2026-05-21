"""Route-level tests for the Flask app. Run: pytest tests/test_routes.py"""
import pytest
from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_save_config_missing_key_returns_400(client):
    r = client.post('/save-config', json={})
    assert r.status_code == 400
    assert r.get_json()["success"] is False


def test_save_config_non_string_returns_400(client):
    r = client.post('/save-config', json={"memory_path": 123})
    assert r.status_code == 400


def test_save_config_no_body_returns_400(client):
    r = client.post('/save-config', data="not json", content_type="application/json")
    assert r.status_code == 400


def test_save_config_path_outside_home_returns_400(client):
    r = client.post('/save-config', json={"memory_path": "/etc/passwd"})
    assert r.status_code == 400
