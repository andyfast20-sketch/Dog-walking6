import importlib


def test_admin_page_handles_missing_last_visit():
    module = importlib.import_module("app.app")
    module.visitor_stats = {
        "203.0.113.10": {
            "first_visit": "2024-06-01T10:00:00",
            "last_visit": "not-a-date",
            "visits": 3,
            "location": "Unknown",
            "user_agent": "pytest",
            "accept_language": "en-US",
        }
    }

    client = module.app.test_client()

    response = client.get("/admin")

    assert response.status_code == 200
    assert b"Admin" in response.data
    module.visitor_stats = {}


def test_admin_page_skips_invalid_visitors():
    module = importlib.import_module("app.app")
    module.visitor_stats = {
        "198.51.100.1": "totally-not-a-dict",
        "198.51.100.2": None,
    }

    client = module.app.test_client()

    response = client.get("/admin")

    assert response.status_code == 200
    assert b"Admin" in response.data


def test_admin_page_handles_malformed_conversations():
    module = importlib.import_module("app.app")
    module.chat_conversations = {
        "abc123": {
            "visitor_id": "abc123",
            "ip_address": "203.0.113.55",
            "created_at": "not-a-date",
            "messages": "totally-not-a-list",
        }
    }

    client = module.app.test_client()

    response = client.get("/admin")

    assert response.status_code == 200
    assert b"Admin" in response.data
    module.chat_conversations = {}

