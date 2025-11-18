import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

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


def test_state_backup_includes_history_entries(tmp_path, monkeypatch, app_module):
    monkeypatch.setattr(app_module, "_backup_directory_candidates", lambda: [str(tmp_path)])

    result = app_module._write_state_backup()

    backup_path = tmp_path / app_module.STATE_BACKUP_FILENAME
    assert backup_path.exists()
    with open(backup_path, "r", encoding="utf-8") as backup_file:
        data = json.load(backup_file)

    history_rows = data.get("backup_history", [])
    assert history_rows, "backup file should include history entries"
    history_entry = result["history_entry"]
    assert history_rows[0]["id"] == history_entry["id"]
    assert history_rows[0]["file_path"] == history_entry["file_path"]
