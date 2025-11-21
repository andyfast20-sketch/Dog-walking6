import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

import io
import json
import sqlite3

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def app_module():
    module = importlib.import_module("app.app")
    yield module
    importlib.reload(module)


def test_serialize_state_includes_chats_breeds_and_photos(app_module):
    app_module.chat_conversations = {
        "visitor-123": {
            "visitor_id": "visitor-123",
            "ip_address": "203.0.113.10",
            "created_at": datetime(2024, 1, 1, 12, 0, 0),
            "last_message_at": datetime(2024, 1, 1, 12, 5, 0),
            "messages": [
                {
                    "id": 1,
                    "sender": "visitor",
                    "body": "Hello there",
                    "timestamp": datetime(2024, 1, 1, 12, 0, 0).isoformat(),
                    "seen_by_admin": False,
                }
            ],
        }
    }
    app_module.dog_breeds = [{"id": 1, "name": "Border Collie"}]
    app_module.site_photos["home_hero"] = "https://example.com/custom-hero.jpg"
    app_module.meet_greet_enabled = False

    payload = app_module._serialize_state()

    assert "visitor-123" in payload["chat_conversations"]
    serialized_conversation = payload["chat_conversations"]["visitor-123"]
    assert serialized_conversation["messages"][0]["body"] == "Hello there"
    assert payload["dog_breeds"][0]["name"] == "Border Collie"
    assert payload["site_photos"]["home_hero"] == "https://example.com/custom-hero.jpg"
    assert payload["meet_greet_enabled"] is False


def test_load_state_restores_chats_breeds_and_photos(app_module):
    state = app_module._serialize_state()
    state["chat_conversations"] = {
        "visitor-999": {
            "visitor_id": "visitor-999",
            "ip_address": "198.51.100.5",
            "created_at": datetime(2024, 2, 2, 9, 30, 0).isoformat(),
            "last_message_at": datetime(2024, 2, 2, 9, 40, 0).isoformat(),
            "messages": [
                {
                    "id": 42,
                    "sender": "admin",
                    "body": "Thanks for reaching out!",
                    "timestamp": datetime(2024, 2, 2, 9, 35, 0).isoformat(),
                    "seen_by_admin": True,
                }
            ],
        }
    }
    state["next_chat_message_id"] = 43
    state["dog_breeds"] = [{"id": 5, "name": "Vizsla"}]
    state["next_dog_breed_id"] = 6
    state["site_photos"]["home_hero"] = "https://example.com/fresh-hero.jpg"
    state["meet_greet_enabled"] = False

    app_module.meet_greet_enabled = True

    app_module._load_state(state)

    assert "visitor-999" in app_module.chat_conversations
    restored_conversation = app_module.chat_conversations["visitor-999"]
    assert restored_conversation["messages"][0]["body"] == "Thanks for reaching out!"
    assert app_module.dog_breeds[0]["name"] == "Vizsla"
    assert app_module.site_photos["home_hero"] == "https://example.com/fresh-hero.jpg"
    assert app_module.meet_greet_enabled is False


def test_backup_candidates_include_project_root_and_folder(app_module):
    project_root = Path(app_module.app.root_path).parent
    candidates = app_module._backup_directory_candidates()
    assert str(project_root) in candidates
    assert str(project_root / "backups") in candidates


def test_backup_candidates_include_env_directory(tmp_path, monkeypatch, app_module):
    env_path = tmp_path / "nested" / "snapshots.sqlite3"
    monkeypatch.setenv("DOG_WALKING_BACKUP_DB_PATH", str(env_path))

    candidates = app_module._backup_directory_candidates()

    assert str(env_path.parent.resolve()) in candidates


def test_state_backup_includes_history_entries(tmp_path, monkeypatch, app_module):
    db_path = tmp_path / "snapshots.sqlite3"
    monkeypatch.setenv("DOG_WALKING_BACKUP_DB_PATH", str(db_path))

    result = app_module._write_state_backup()

    assert db_path.exists()
    with sqlite3.connect(str(db_path)) as connection:
        row = connection.execute("SELECT payload FROM state_backups ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    data = json.loads(row[0])
    history_rows = data.get("backup_history", [])
    assert history_rows, "snapshot should include history entries"
    history_entry = result["history_entry"]
    assert history_rows[0]["id"] == history_entry["id"]
    assert history_rows[0]["storage_label"] == history_entry["storage_label"]


def test_state_backup_updates_auto_export(tmp_path, monkeypatch, app_module):
    db_path = tmp_path / "snapshots.sqlite3"
    monkeypatch.setenv("DOG_WALKING_BACKUP_DB_PATH", str(db_path))
    monkeypatch.setattr(app_module, "_backup_directory_candidates", lambda: [str(tmp_path)])
    monkeypatch.setattr(app_module, "_cached_export_file_path", None)

    result = app_module._write_state_backup()

    assert result is not None
    export_path = tmp_path / app_module.STATE_EXPORT_FILENAME
    assert export_path.exists(), "auto export file should be refreshed after a snapshot"
    saved_payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert saved_payload.get("backup_history"), "auto export should include history data"


def test_download_route_writes_export_file(tmp_path, monkeypatch, app_module):
    monkeypatch.setattr(app_module, "_backup_directory_candidates", lambda: [str(tmp_path)])
    client = app_module.app.test_client()

    response = client.get("/admin/state/download")

    assert response.status_code == 200
    export_path = tmp_path / app_module.STATE_EXPORT_FILENAME
    assert export_path.exists()
    saved_payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert "chat_conversations" in saved_payload


def test_import_route_restores_from_auto_export(tmp_path, monkeypatch, app_module):
    monkeypatch.setattr(app_module, "_backup_directory_candidates", lambda: [str(tmp_path)])
    export_path = tmp_path / app_module.STATE_EXPORT_FILENAME
    state = app_module._serialize_state()
    state["meet_greet_enabled"] = False
    export_path.write_text(json.dumps(state), encoding="utf-8")
    app_module.meet_greet_enabled = True
    client = app_module.app.test_client()

    response = client.post("/admin/state/import", data={}, content_type="multipart/form-data")

    assert response.status_code == 302
    assert "state_action=imported" in response.headers.get("Location", "")
    assert app_module.meet_greet_enabled is False


def test_import_route_reports_missing_auto_export(tmp_path, monkeypatch, app_module):
    monkeypatch.setattr(app_module, "_backup_directory_candidates", lambda: [str(tmp_path)])
    client = app_module.app.test_client()

    response = client.post("/admin/state/import", data={}, content_type="multipart/form-data")

    assert response.status_code == 302
    assert "state_action=auto_import_missing" in response.headers.get("Location", "")


def test_import_route_accepts_uploaded_file(app_module):
    client = app_module.app.test_client()
    app_module.meet_greet_enabled = True
    uploaded_state = app_module._serialize_state()
    uploaded_state["meet_greet_enabled"] = False

    response = client.post(
        "/admin/state/import",
        data={
            "state_file": (io.BytesIO(json.dumps(uploaded_state).encode("utf-8")), "andy(3).json"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert "state_action=imported" in response.headers.get("Location", "")
    assert app_module.meet_greet_enabled is False


def test_load_data_falls_back_to_auto_export(tmp_path, monkeypatch, app_module):
    monkeypatch.setattr(app_module, "_backup_directory_candidates", lambda: [str(tmp_path)])
    monkeypatch.setattr(app_module, "_cached_export_file_path", None)
    state = app_module._serialize_state()
    state["dog_breeds"] = [{"id": 99, "name": "Pocket Beagle"}]
    export_path = tmp_path / app_module.STATE_EXPORT_FILENAME
    export_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(app_module, "_kv_get", lambda key: None)
    app_module.dog_breeds = []

    assert app_module.load_data() is True
    assert any(breed["name"] == "Pocket Beagle" for breed in app_module.dog_breeds)
