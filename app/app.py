import json
import os
import queue
import sqlite3
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)

app = Flask(__name__)


PRIMARY_NAV_CONFIG = [
    {"key": "home", "label": "Home", "endpoint": "index", "url_kwargs": {}},
    {
        "key": "bookings",
        "label": "Bookings",
        "endpoint": "bookings_page",
        "url_kwargs": {},
    },
    {
        "key": "about",
        "label": "About",
        "endpoint": "hello_world_page",
        "url_kwargs": {"page_id": 1},
    },
    {
        "key": "services",
        "label": "Services",
        "endpoint": "hello_world_page",
        "url_kwargs": {"page_id": 2},
    },
    {
        "key": "prices",
        "label": "Prices",
        "endpoint": "hello_world_page",
        "url_kwargs": {"page_id": 3},
    },
    {
        "key": "contact",
        "label": "Contact",
        "endpoint": "hello_world_page",
        "url_kwargs": {"page_id": 4},
    },
]

BOOKING_SERVICE_TYPES = {
    "walk": {"label": "Dog Walking"},
    "meet": {"label": "Meet & Greet"},
}

BOOKING_SERVICE_TYPE_OPTIONS = [
    ("walk", BOOKING_SERVICE_TYPES["walk"]["label"]),
    ("meet", BOOKING_SERVICE_TYPES["meet"]["label"]),
]

PAGE_DEFINITIONS = {
    1: {
        "id": 1,
        "nav_key": "about",
        "eyebrow": "Our story",
        "title": "Who we are",
        "lede": "Happy Trails Dog Walking is a concierge-style service inspired by the dogs who tugged us down these streets more than a decade ago.",
        "highlight": "Neighbors trust us with their best friends because we blend attentive care with seamless tech.",
        "hero_image": "https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&w=900&q=80",
        "metrics": [
            {"label": "Years caring for Leeds pups", "value": "12+"},
            {"label": "Monthly walks delivered", "value": "320"},
            {"label": "Handlers on our roster", "value": "8"},
        ],
        "sections": [
            {
                "title": "Our promise",
                "body": "Safety-first adventures, thoughtful pacing, and photo updates every walk.",
                "bullets": [
                    "GPS tracking with live arrival estimates",
                    "Solo walks for anxious pups",
                    "Flexible meet-and-greet scheduling",
                ],
            },
            {
                "title": "Meet the crew",
                "body": "Handlers are certified in canine first aid, background checked, and mentored for three months before heading out solo.",
                "bullets": [
                    "Monthly continuing education",
                    "Neighborhood specialists",
                    "Emergency support line",
                ],
            },
        ],
    },
    2: {
        "id": 2,
        "nav_key": "services",
        "eyebrow": "What we do",
        "title": "Tailored walking services",
        "lede": "From quick relief breaks to half-day adventures, every outing is curated for your pup's personality and energy level.",
        "highlight": "Pick a foundation service and layer on training refreshers, trail runs, or cuddle cooldowns.",
        "hero_image": "https://images.unsplash.com/photo-1518378188025-22bd89516ee2?auto=format&fit=crop&w=900&q=80",
        "sections": [
            {
                "title": "Daily essentials",
                "body": "Perfect for consistent routines and midday wiggles.",
                "bullets": [
                    "20-minute refresh walks",
                    "45-minute neighborhood tours",
                    "Weekend warrior playdates",
                ],
            },
            {
                "title": "Specialty add-ons",
                "body": "Customize each visit with enrichment and concierge touches.",
                "bullets": [
                    "Training reinforcement",
                    "Puppy socialization field trips",
                    "Medication and meal support",
                ],
            },
        ],
    },
    3: {
        "id": 3,
        "nav_key": "prices",
        "eyebrow": "Investment",
        "title": "Transparent pricing",
        "lede": "Premium care, clear rates, and no surprise fees. Bundle sessions or pay-as-you-go with digital receipts every Friday.",
        "highlight": "Members save up to 15% with recurring walk packs and concierge perks.",
        "hero_image": "https://images.unsplash.com/photo-1507149833265-60c372daea22?auto=format&fit=crop&w=900&q=80",
        "sections": [
            {
                "title": "Core walk menu",
                "body": "Choose the cadence that matches your schedule.",
                "bullets": [
                    "Express (20 min) — $28",
                    "Signature (45 min) — $42",
                    "Adventure hour — $58",
                ],
            },
            {
                "title": "Membership perks",
                "body": "Bundle more, save more, and unlock concierge extras.",
                "bullets": [
                    "5-walk pack: save 5%",
                    "10-walk pack: save 10%",
                    "Unlimited month: includes free pup taxi",
                ],
            },
        ],
    },
    4: {
        "id": 4,
        "nav_key": "contact",
        "eyebrow": "Let's talk",
        "title": "Get in touch",
        "lede": "Prefer a personal hello? Reach us the way that works for you and we'll respond within the hour.",
        "highlight": "Dedicated concierge monitors calls, texts, and chat Monday–Saturday, 7am–9pm.",
        "hero_image": "https://images.unsplash.com/photo-1507146426996-ef05306b995a?auto=format&fit=crop&w=900&q=80",
        "sections": [
            {
                "title": "Direct contact",
                "body": "We're real humans excited to help schedule walks and answer questions.",
                "bullets": [
                    "Call: (555) 012-4455",
                    "Text: (555) 014-7788",
                    "Email: concierge@happytrails.dog",
                ],
            },
            {
                "title": "Visit us",
                "body": "Stop by the studio to say hi and pick up pup merch.",
                "bullets": [
                    "143 Riverwalk Ave, Suite 3",
                    "Weekdays 10am–6pm",
                    "Parking validated for clients",
                ],
            },
        ],
    },
}


def _build_site_photo_defaults():
    defaults = {
        "home_hero": {
            "label": "Homepage hero photo",
            "description": "Large image shown in the hero on the homepage.",
            "default_url": "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?auto=format&fit=crop&w=900&q=80",
            "group": "homepage",
        },
        "home_profile": {
            "label": "Homepage profile photo",
            "description": "Portrait used in the concierge walker spotlight on the homepage.",
            "default_url": "https://files.catbox.moe/986gie.jpg",
            "group": "homepage",
        },
        "bookings_hero": {
            "label": "Bookings hero photo",
            "description": "Image displayed beside the bookings hero content.",
            "default_url": "https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&w=1000&q=80",
            "group": "bookings",
        },
    }
    for page in PAGE_DEFINITIONS.values():
        defaults[f"page_{page['id']}_hero"] = {
            "label": f"{page['title']} hero photo",
            "description": "Large featured photo at the top of this page.",
            "default_url": page["hero_image"],
            "group": "info_pages",
            "page_id": page["id"],
            "page_title": page["title"],
        }
    return defaults


SITE_PHOTO_GROUP_LABELS = {
    "homepage": "Homepage",
    "bookings": "Bookings",
    "info_pages": "Story pages",
}
SITE_PHOTO_GROUP_ORDER = ["homepage", "bookings", "info_pages"]
SITE_PHOTO_DEFAULTS = _build_site_photo_defaults()


def _initial_site_photo_state():
    state = {}
    for key, meta in SITE_PHOTO_DEFAULTS.items():
        state[key] = meta["default_url"]
    return state


site_photos = _initial_site_photo_state()


def _build_primary_nav(active_key: str):
    nav_items = []
    for item in PRIMARY_NAV_CONFIG:
        nav_items.append(
            {
                "label": item["label"],
                "href": url_for(item["endpoint"], **item["url_kwargs"]),
                "is_active": item["key"] == active_key,
            }
        )
    return nav_items


submissions = []
next_submission_id = 1
STATUS_OPTIONS = ["New", "In Process", "Finished"]
visitor_stats = {}
blocked_ips = set()
chat_conversations = {}
next_chat_message_id = 1
chat_stream_subscribers = []
chat_subscribers_lock = threading.Lock()
appointment_slots = []
next_slot_id = 1
dog_breeds = []
next_dog_breed_id = 1
breed_ai_suggestions = None
meet_greet_enabled = True
backup_history = []
next_backup_history_id = 1

ADMIN_VIEWS = {
    "menu",
    "autopilot",
    "status",
    "backups",
    "coverage",
    "credentials",
    "breeds",
    "photos",
    "enquiries",
    "appointments",
    "visitors",
    "chat",
}
BOOKING_WORKFLOW_STATUSES = ["New", "In Progress", "Dealt With"]
DEFAULT_TIME_CHOICES = [
    "08:00",
    "09:00",
    "10:00",
    "11:00",
    "13:00",
    "14:00",
    "15:00",
    "16:00",
]


IGNORED_USER_AGENT_KEYWORDS = ["vercel-screenshot"]

AUTOPILOT_MODEL_NAME = "deepseek-chat"
DEFAULT_COVERAGE_AREAS = [
    {
        "id": 1,
        "name": "Parkside & Cathedral Quarter",
        "description": "Leafy boulevards, museum blocks, and riverside dog runs.",
        "travel_fee": 0,
    },
    {
        "id": 2,
        "name": "Meadow Lane + Riverside",
        "description": "Wide paths with plenty of shade and calm waterfront strolls.",
        "travel_fee": 0,
    },
    {
        "id": 3,
        "name": "Southbank & Market Streets",
        "description": "Cobbled lanes, coffee stops, and pocket parks every few blocks.",
        "travel_fee": 0,
    },
]
DEFAULT_CERTIFICATES = [
    {
        "id": 1,
        "title": "Level 3 Professional Dog Walker",
        "issuer": "National Association of Pet Care",
        "year": "2024",
        "description": "Advanced canine body-language training, emergency planning, and ethical handling standards.",
        "image_url": "https://images.unsplash.com/photo-1525253086316-d0c936c814f8?auto=format&fit=crop&w=600&q=80",
        "link_url": "https://www.napps.org.uk/",
    },
    {
        "id": 2,
        "title": "Canine First Aid & CPR",
        "issuer": "PetSaver Institute",
        "year": "2023",
        "description": "Annual recertification covering trail emergencies, paw triage, and on-lead incident management.",
        "image_url": "https://images.unsplash.com/photo-1507149833265-60c372daea22?auto=format&fit=crop&w=600&q=80",
        "link_url": "https://petsaver.co.uk/",
    },
    {
        "id": 3,
        "title": "Fear Free Dog Handling",
        "issuer": "Fear Free Pets",
        "year": "2022",
        "description": "Techniques to reduce stress, create decompression breaks, and build trust with sensitive pups.",
        "image_url": "https://images.unsplash.com/photo-1517423440428-a5a00ad493e8?auto=format&fit=crop&w=600&q=80",
        "link_url": "https://fearfreepets.com/",
    },
]
BUSINESS_BOX_DEFAULT = (
    "Happy Trails Dog Walking is a turnkey business-in-a-box that provides daily dog walks, "
    "vacation pet sitting, and concierge-style updates for busy pet parents in town. We focus "
    "on reliable scheduling, GPS-tracked adventures, photo journals, and easy online booking. "
    "Let visitors know how we onboard pets, what areas we cover, pricing cues (premium yet "
    "friendly), and how to move from a chat to a booked meet-and-greet."
)
business_in_a_box = BUSINESS_BOX_DEFAULT
coverage_areas = [dict(area) for area in DEFAULT_COVERAGE_AREAS]
for area in coverage_areas:
    area.setdefault("travel_fee", None)
next_coverage_area_id = len(coverage_areas) + 1
team_certificates = [dict(certificate) for certificate in DEFAULT_CERTIFICATES]
next_certificate_id = len(team_certificates) + 1
autopilot_enabled = False
autopilot_status = {
    "state": "off",
    "last_run": None,
    "last_error": None,
    "last_reply_preview": None,
    "last_visitor_id": None,
}
auto_save_enabled = False
auto_save_last_run: Optional[datetime] = None
SERVICE_NOTICE_DEFAULT_TEXT = "Website under construction - Do not place any bookings."
site_service_notice = {"enabled": False, "message": SERVICE_NOTICE_DEFAULT_TEXT}
STATE_BACKUP_DB_FILENAME = "state_backups.sqlite3"
STATE_EXPORT_FILENAME = "latest_admin_export.json"
_cached_backup_db_path: Optional[str] = None
_cached_export_file_path: Optional[str] = None


def _backup_directory_candidates():
    """Return a list of writeable directories we can attempt for backups."""

    directories = []
    project_root = os.path.abspath(os.path.join(app.root_path, os.pardir))
    preferred = [
        app.instance_path,
        os.path.join(project_root, "backups"),
        project_root,
        app.root_path,
        os.getcwd(),
        os.environ.get("STATE_BACKUP_DIR"),
        os.path.join(tempfile.gettempdir(), "dog_walking_admin"),
    ]
    for directory in preferred:
        if directory and directory not in directories:
            directories.append(directory)
    return directories


def _state_export_file_path() -> str:
    """Return a writeable path for the JSON export file."""

    global _cached_export_file_path
    if _cached_export_file_path:
        directory = os.path.dirname(_cached_export_file_path)
        if directory and os.path.isdir(directory):
            return _cached_export_file_path
        _cached_export_file_path = None

    for directory in _backup_directory_candidates():
        if not directory:
            continue
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            continue
        if os.access(directory, os.W_OK):
            _cached_export_file_path = os.path.join(directory, STATE_EXPORT_FILENAME)
            return _cached_export_file_path

    fallback_directory = tempfile.gettempdir()
    _cached_export_file_path = os.path.join(fallback_directory, STATE_EXPORT_FILENAME)
    return _cached_export_file_path


def _state_backup_db_path() -> str:
    """Return a writeable path for the sqlite backup database."""

    override = os.environ.get("DOG_WALKING_BACKUP_DB_PATH")
    if override:
        return os.path.abspath(override)

    global _cached_backup_db_path
    if _cached_backup_db_path:
        directory = os.path.dirname(_cached_backup_db_path)
        if not directory or os.path.exists(directory):
            return _cached_backup_db_path
        _cached_backup_db_path = None

    # Prefer any existing database file, even if it lives in a legacy directory.
    for directory in _backup_directory_candidates():
        if not directory:
            continue
        candidate_path = os.path.join(directory, STATE_BACKUP_DB_FILENAME)
        if os.path.isfile(candidate_path):
            _cached_backup_db_path = candidate_path
            return candidate_path

    # Fall back to the first directory where we can create and write the file.
    for directory in _backup_directory_candidates():
        if not directory:
            continue
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            continue
        candidate_path = os.path.join(directory, STATE_BACKUP_DB_FILENAME)
        try:
            with open(candidate_path, "a", encoding="utf-8"):
                pass
        except OSError:
            continue
        _cached_backup_db_path = candidate_path
        return candidate_path

    fallback_directory = tempfile.gettempdir()
    try:
        os.makedirs(fallback_directory, exist_ok=True)
    except OSError:
        pass
    _cached_backup_db_path = os.path.join(fallback_directory, STATE_BACKUP_DB_FILENAME)
    return _cached_backup_db_path


def _ensure_backup_db_initialized():
    path = _state_backup_db_path()
    directory = os.path.dirname(path)
    if directory:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS state_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                saved_at TEXT NOT NULL,
                source TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )


def _fetch_backup_row(storage_id: Optional[int] = None):
    _ensure_backup_db_initialized()
    path = _state_backup_db_path()
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        if storage_id is None:
            return connection.execute(
                "SELECT id, saved_at, source, payload FROM state_backups ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return connection.execute(
            "SELECT id, saved_at, source, payload FROM state_backups WHERE id = ?",
            (storage_id,),
        ).fetchone()


def _count_backup_rows() -> int:
    _ensure_backup_db_initialized()
    path = _state_backup_db_path()
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT COUNT(*) FROM state_backups").fetchone()[0]


def _delete_backup_row(storage_id: Optional[int]):
    if storage_id is None:
        return
    _ensure_backup_db_initialized()
    path = _state_backup_db_path()
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM state_backups WHERE id = ?", (storage_id,))


def _describe_backup_source(source: Optional[str]) -> str:
    if source == "auto":
        return "Auto save"
    if source == "manual":
        return "Manual save"
    if source:
        return source.replace("_", " ").title()
    return "Manual save"


def _format_backup_history_timestamp(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%b %d, %Y %H:%M UTC")
    return str(value)


def _record_backup_history(
    storage_label: str,
    source: str,
    saved_at_value,
    *,
    storage_id: Optional[int] = None,
    storage_type: str = "database",
) -> dict:
    global backup_history, next_backup_history_id

    timestamp = _parse_datetime(saved_at_value) or datetime.utcnow()
    entry = {
        "id": next_backup_history_id,
        "storage_label": storage_label,
        "storage_id": storage_id,
        "storage_type": storage_type,
        "saved_at": timestamp,
        "source": source or "manual",
        "legacy_path": None,
    }
    backup_history.insert(0, entry)
    next_backup_history_id += 1
    return entry


def _serialize_backup_history_entry(entry: dict) -> dict:
    return {
        "id": entry.get("id"),
        "storage_label": entry.get("storage_label"),
        "storage_id": entry.get("storage_id"),
        "storage_type": entry.get("storage_type"),
        "legacy_path": entry.get("legacy_path"),
        "saved_at": _serialize_datetime(entry.get("saved_at")),
        "source": entry.get("source"),
    }


def _present_backup_history_entry(entry: dict, include_urls: bool = False) -> dict:
    if not entry:
        return {}
    payload = {
        "id": entry.get("id"),
        "storage_label": entry.get("storage_label"),
        "storage_type": entry.get("storage_type"),
        "legacy_path": entry.get("legacy_path"),
        "saved_at": _serialize_datetime(entry.get("saved_at")),
        "saved_at_label": _format_backup_history_timestamp(entry.get("saved_at")),
        "source": entry.get("source"),
        "source_label": _describe_backup_source(entry.get("source")),
    }
    if include_urls and entry.get("id") is not None:
        payload["load_url"] = url_for("load_backup_history_entry", entry_id=entry["id"])
        payload["delete_url"] = url_for("delete_backup_history_entry", entry_id=entry["id"])
    return payload


def _get_backup_history_entry(entry_id: int):
    return next((entry for entry in backup_history if entry.get("id") == entry_id), None)


def _remove_backup_history_entry(entry_id: int):
    global backup_history

    entry = _get_backup_history_entry(entry_id)
    if not entry:
        return None
    backup_history = [item for item in backup_history if item.get("id") != entry_id]
    return entry


def _write_state_backup(source: str = "manual") -> Optional[dict]:
    """Persist the serialized state to the managed database."""

    state_payload = _serialize_state()
    try:
        _ensure_backup_db_initialized()
        path = _state_backup_db_path()
        with sqlite3.connect(path) as connection:
            cursor = connection.execute(
                "INSERT INTO state_backups (saved_at, source, payload) VALUES (?, ?, ?)",
                (state_payload.get("saved_at"), source or "manual", "{}"),
            )
            storage_id = cursor.lastrowid
            storage_label = f"Snapshot #{storage_id} (database)"
            history_entry = _record_backup_history(
                storage_label,
                source,
                state_payload.get("saved_at"),
                storage_id=storage_id,
                storage_type="database",
            )
            state_payload_with_history = dict(state_payload)
            state_payload_with_history["backup_history"] = [
                _serialize_backup_history_entry(entry) for entry in backup_history
            ]
            state_payload_with_history["next_backup_history_id"] = next_backup_history_id
            payload_text = json.dumps(state_payload_with_history, indent=2)
            connection.execute(
                "UPDATE state_backups SET payload = ? WHERE id = ?",
                (payload_text, storage_id),
            )
    except sqlite3.Error:
        return None

    return {"history_entry": history_entry, "storage_id": storage_id}


def _serialize_datetime(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_photo_url(key: str) -> str:
    meta = SITE_PHOTO_DEFAULTS.get(key)
    if not meta:
        return ""
    current = site_photos.get(key)
    return current or meta["default_url"]


def _site_photo_rows():
    rows = []
    for key, meta in SITE_PHOTO_DEFAULTS.items():
        current = _get_photo_url(key) or meta["default_url"]
        default_url = meta["default_url"]
        group_key = meta.get("group", "site")
        try:
            group_order = SITE_PHOTO_GROUP_ORDER.index(group_key)
        except ValueError:
            group_order = len(SITE_PHOTO_GROUP_ORDER)
        rows.append(
            {
                "key": key,
                "label": meta["label"],
                "description": meta.get("description"),
                "url": current,
                "default_url": default_url,
                "is_default": current == default_url,
                "group_key": group_key,
                "group_label": SITE_PHOTO_GROUP_LABELS.get(group_key, "Site-wide"),
                "group_order": group_order,
                "page_id": meta.get("page_id"),
                "page_title": meta.get("page_title"),
            }
        )
    rows.sort(key=lambda row: (row["group_order"], row["label"].lower()))
    return rows


def _group_photo_rows(rows):
    groups = []
    current_key = None
    for row in rows:
        if row["group_key"] != current_key:
            groups.append({"key": row["group_key"], "label": row["group_label"], "photos": []})
            current_key = row["group_key"]
        groups[-1]["photos"].append(row)
    return groups


def _service_notice_state():
    message = (site_service_notice.get("message") or SERVICE_NOTICE_DEFAULT_TEXT).strip()
    if not message:
        message = SERVICE_NOTICE_DEFAULT_TEXT
    return {"enabled": bool(site_service_notice.get("enabled")), "message": message}


def _meet_greet_setting() -> bool:
    return bool(meet_greet_enabled)


def _next_id_from_rows(rows, key: str = "id") -> int:
    max_value = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_value = row.get(key)
        try:
            numeric_value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if numeric_value > max_value:
            max_value = numeric_value
    return max_value + 1


def _parse_price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text_value = str(value).strip()
    if not text_value:
        return None
    normalized = text_value.replace("$", "").replace(",", "")
    try:
        return float(normalized)
    except (TypeError, ValueError):
        return None


def _format_price_label(value) -> str:
    amount = _parse_price(value)
    if amount is None:
        return ""
    formatted = f"£{amount:,.2f}"
    if formatted.endswith(".00"):
        formatted = formatted[:-3]
    return formatted


def _service_label(value: Optional[str]) -> str:
    service_key = value if value in BOOKING_SERVICE_TYPES else "walk"
    return BOOKING_SERVICE_TYPES.get(service_key, BOOKING_SERVICE_TYPES["walk"])["label"]


def _serialize_state() -> dict:
    visitor_rows = {}
    for ip_address, visitor in visitor_stats.items():
        data = dict(visitor)
        data["first_visit"] = _serialize_datetime(data.get("first_visit"))
        data["last_visit"] = _serialize_datetime(data.get("last_visit"))
        visitor_rows[ip_address] = data
    conversation_rows = {}
    for visitor_id, conversation in chat_conversations.items():
        data = {
            "visitor_id": visitor_id,
            "ip_address": conversation.get("ip_address"),
            "created_at": _serialize_datetime(conversation.get("created_at")),
            "last_message_at": _serialize_datetime(conversation.get("last_message_at")),
            "messages": [dict(message) for message in conversation.get("messages", [])],
        }
        conversation_rows[visitor_id] = data
    slot_rows = []
    for slot in appointment_slots:
        slot_rows.append(
            {
                "id": slot.get("id"),
                "start": _serialize_datetime(slot.get("start")),
                "is_booked": bool(slot.get("is_booked", False)),
                "workflow_status": slot.get("workflow_status"),
                "visitor_name": slot.get("visitor_name"),
                "visitor_email": slot.get("visitor_email"),
                "visitor_dog_breed": slot.get("visitor_dog_breed"),
                "visitor_service_area_id": slot.get("visitor_service_area_id"),
                "visitor_service_area_name": slot.get("visitor_service_area_name"),
                "visitor_travel_fee": slot.get("visitor_travel_fee"),
                "booked_at": _serialize_datetime(slot.get("booked_at")),
                "price": slot.get("price"),
                "service_type": slot.get("service_type", "walk"),
            }
        )
    state = {
        "version": 1,
        "saved_at": datetime.utcnow().isoformat(),
        "submissions": [dict(submission) for submission in submissions],
        "next_submission_id": next_submission_id,
        "visitor_stats": visitor_rows,
        "blocked_ips": list(blocked_ips),
        "chat_conversations": conversation_rows,
        "next_chat_message_id": next_chat_message_id,
        "appointment_slots": slot_rows,
        "next_slot_id": next_slot_id,
        "dog_breeds": [dict(breed) for breed in dog_breeds],
        "next_dog_breed_id": next_dog_breed_id,
        "coverage_areas": [dict(area) for area in coverage_areas],
        "next_coverage_area_id": next_coverage_area_id,
        "certificates": [dict(certificate) for certificate in team_certificates],
        "next_certificate_id": next_certificate_id,
        "breed_ai_suggestions": breed_ai_suggestions,
        "business_in_a_box": business_in_a_box,
        "autopilot_enabled": autopilot_enabled,
        "autopilot_status": dict(autopilot_status),
        "site_photos": dict(site_photos),
        "service_notice": dict(site_service_notice),
        "meet_greet_enabled": _meet_greet_setting(),
        "auto_save_enabled": auto_save_enabled,
        "auto_save_last_run": _serialize_datetime(auto_save_last_run),
        "backup_history": [_serialize_backup_history_entry(entry) for entry in backup_history],
        "next_backup_history_id": next_backup_history_id,
    }
    return state


def _load_state(state: dict):
    global submissions, next_submission_id, visitor_stats, blocked_ips
    global chat_conversations, next_chat_message_id, appointment_slots
    global next_slot_id, dog_breeds, next_dog_breed_id
    global business_in_a_box, autopilot_enabled, autopilot_status, breed_ai_suggestions
    global coverage_areas, next_coverage_area_id, team_certificates, next_certificate_id
    global site_photos, site_service_notice, meet_greet_enabled
    global auto_save_enabled, auto_save_last_run
    global backup_history, next_backup_history_id

    submissions = [dict(row) for row in state.get("submissions", []) if isinstance(row, dict)]
    next_submission_id = _coerce_int(state.get("next_submission_id"), _next_id_from_rows(submissions))

    visitor_rows = {}
    for ip_address, payload in (state.get("visitor_stats") or {}).items():
        if not isinstance(payload, dict):
            continue
        data = dict(payload)
        data["first_visit"] = _parse_datetime(data.get("first_visit")) or datetime.utcnow()
        data["last_visit"] = _parse_datetime(data.get("last_visit")) or data["first_visit"]
        visitor_rows[ip_address] = data
    visitor_stats = visitor_rows

    blocked_ips = set(state.get("blocked_ips") or [])

    conversation_rows = {}
    for visitor_id, conversation in (state.get("chat_conversations") or {}).items():
        if not isinstance(conversation, dict):
            continue
        data = {
            "visitor_id": visitor_id,
            "ip_address": conversation.get("ip_address"),
            "created_at": _parse_datetime(conversation.get("created_at")) or datetime.utcnow(),
            "last_message_at": _parse_datetime(conversation.get("last_message_at")),
            "messages": [dict(message) for message in conversation.get("messages", []) if isinstance(message, dict)],
        }
        conversation_rows[visitor_id] = data
    chat_conversations = conversation_rows

    all_messages = []
    for conversation in chat_conversations.values():
        all_messages.extend(conversation.get("messages", []))
    next_chat_message_id = _coerce_int(state.get("next_chat_message_id"), _next_id_from_rows(all_messages))

    slots = []
    for payload in state.get("appointment_slots", []):
        if not isinstance(payload, dict):
            continue
        start = _parse_datetime(payload.get("start"))
        if not start:
            continue
        slot = {
            "id": _coerce_int(payload.get("id"), _next_id_from_rows(slots)),
            "start": start,
            "is_booked": bool(payload.get("is_booked", False)),
            "workflow_status": payload.get("workflow_status", ""),
            "visitor_name": payload.get("visitor_name"),
            "visitor_email": payload.get("visitor_email"),
            "visitor_dog_breed": payload.get("visitor_dog_breed"),
            "visitor_service_area_id": payload.get("visitor_service_area_id"),
            "visitor_service_area_name": payload.get("visitor_service_area_name"),
            "visitor_travel_fee": _parse_price(payload.get("visitor_travel_fee")),
            "booked_at": _parse_datetime(payload.get("booked_at")),
            "price": _parse_price(payload.get("price")),
            "service_type": payload.get("service_type", "walk"),
        }
        slots.append(slot)
    appointment_slots = sorted(slots, key=lambda slot: slot["start"])
    next_slot_id = _coerce_int(state.get("next_slot_id"), _next_id_from_rows(appointment_slots))

    dog_breeds = [dict(breed) for breed in state.get("dog_breeds", []) if isinstance(breed, dict)]
    next_dog_breed_id = _coerce_int(state.get("next_dog_breed_id"), _next_id_from_rows(dog_breeds))

    coverage_payload = state.get("coverage_areas") or []
    parsed_coverage = []
    for area in coverage_payload:
        if not isinstance(area, dict):
            continue
        data = dict(area)
        data["travel_fee"] = _parse_price(data.get("travel_fee"))
        parsed_coverage.append(data)
    coverage_areas = parsed_coverage or [dict(area) for area in DEFAULT_COVERAGE_AREAS]
    for area in coverage_areas:
        area.setdefault("travel_fee", None)
    next_coverage_area_id = _coerce_int(
        state.get("next_coverage_area_id"),
        _next_id_from_rows(coverage_areas),
    )

    certificate_payload = state.get("certificates") or []
    team_certificates = [dict(row) for row in certificate_payload if isinstance(row, dict)]
    if not team_certificates:
        team_certificates = [dict(certificate) for certificate in DEFAULT_CERTIFICATES]
    next_certificate_id = _coerce_int(
        state.get("next_certificate_id"),
        _next_id_from_rows(team_certificates),
    )

    loaded_breed_ai = state.get("breed_ai_suggestions")
    breed_ai_suggestions = loaded_breed_ai if isinstance(loaded_breed_ai, dict) else None

    business_in_a_box = state.get("business_in_a_box") or BUSINESS_BOX_DEFAULT
    autopilot_enabled = bool(state.get("autopilot_enabled", False))
    loaded_status = state.get("autopilot_status")
    if isinstance(loaded_status, dict):
        autopilot_status = {
            "state": loaded_status.get("state", autopilot_status.get("state", "off")),
            "last_run": loaded_status.get("last_run"),
            "last_error": loaded_status.get("last_error"),
            "last_reply_preview": loaded_status.get("last_reply_preview"),
            "last_visitor_id": loaded_status.get("last_visitor_id"),
        }

    site_photos = _initial_site_photo_state()
    loaded_photos = state.get("site_photos")
    if isinstance(loaded_photos, dict):
        for key, value in loaded_photos.items():
            if key in site_photos and isinstance(value, str) and value.strip():
                site_photos[key] = value.strip()

    loaded_notice = state.get("service_notice")
    if isinstance(loaded_notice, dict):
        message = (loaded_notice.get("message") or SERVICE_NOTICE_DEFAULT_TEXT).strip()
        if not message:
            message = SERVICE_NOTICE_DEFAULT_TEXT
        site_service_notice = {
            "enabled": bool(loaded_notice.get("enabled", False)),
            "message": message,
        }
    else:
        site_service_notice = {"enabled": False, "message": SERVICE_NOTICE_DEFAULT_TEXT}
    meet_greet_enabled = bool(state.get("meet_greet_enabled", True))
    auto_save_enabled = bool(state.get("auto_save_enabled", False))
    auto_save_last_run = _parse_datetime(state.get("auto_save_last_run"))

    history_entries = []
    for payload in state.get("backup_history", []):
        if not isinstance(payload, dict):
            continue
        storage_label = payload.get("storage_label")
        if not storage_label:
            # Backwards compatibility with file-based backups
            storage_label = payload.get("file_path") or payload.get("primary_path") or "Legacy snapshot"
        storage_type = payload.get("storage_type")
        if not storage_type:
            storage_type = "file" if payload.get("file_path") else "database"
        entry = {
            "id": _coerce_int(payload.get("id"), _next_id_from_rows(history_entries)),
            "storage_label": storage_label,
            "storage_id": payload.get("storage_id"),
            "storage_type": storage_type,
            "saved_at": _parse_datetime(payload.get("saved_at")) or datetime.utcnow(),
            "source": payload.get("source") or "manual",
            "legacy_path": payload.get("legacy_path")
            or payload.get("file_path")
            or payload.get("primary_path"),
        }
        history_entries.append(entry)
    history_entries.sort(key=lambda item: item.get("saved_at"), reverse=True)
    backup_history = history_entries
    max_existing_id = max((entry.get("id", 0) or 0) for entry in backup_history) if backup_history else 0
    next_backup_history_id = _coerce_int(
        state.get("next_backup_history_id"),
        max_existing_id + 1,
    )


def _get_state_backup_metadata() -> dict:
    row = _fetch_backup_row()
    database_path = _state_backup_db_path()
    metadata = {
        "exists": row is not None,
        "filename": STATE_BACKUP_DB_FILENAME,
        "database_path": database_path,
        "directory": os.path.dirname(database_path) if database_path else "",
        "total_snapshots": _count_backup_rows(),
        "export_path": _state_export_file_path(),
        "export_filename": STATE_EXPORT_FILENAME,
    }
    if not row:
        return metadata
    metadata["saved_at"] = row["saved_at"]
    metadata["latest_snapshot_id"] = row["id"]
    try:
        payload = json.loads(row["payload"])
        metadata["counts"] = {
            "submissions": len(payload.get("submissions", [])),
            "appointments": len(payload.get("appointment_slots", [])),
            "visitors": len((payload.get("visitor_stats") or {})),
            "chats": len((payload.get("chat_conversations") or {})),
            "dog_breeds": len(payload.get("dog_breeds", [])),
            "site_photos": len((payload.get("site_photos") or {})),
            "coverage_areas": len(payload.get("coverage_areas", [])),
            "certificates": len(payload.get("certificates", [])),
        }
    except (ValueError, json.JSONDecodeError):
        metadata["error"] = "Latest snapshot could not be read"
    return metadata


def _load_state_from_database(storage_id: Optional[int] = None) -> bool:
    row = _fetch_backup_row(storage_id)
    if not row:
        return False
    try:
        payload = json.loads(row["payload"])
    except (TypeError, json.JSONDecodeError):
        return False
    _load_state(payload)
    return True


def _get_submission(submission_id: int):
    return next((submission for submission in submissions if submission["id"] == submission_id), None)


def _get_slot(slot_id: int):
    return next((slot for slot in appointment_slots if slot["id"] == slot_id), None)


def _get_breed(breed_id: int):
    return next((breed for breed in dog_breeds if breed["id"] == breed_id), None)


def _normalize_breed_name(name: str) -> str:
    return " ".join(name.split())


def _breed_name_exists(name: str) -> bool:
    return any(breed["name"].lower() == name.lower() for breed in dog_breeds)


def _sorted_breeds():
    return sorted(dog_breeds, key=lambda breed: breed["name"].lower())


def _get_coverage_area(area_id: int):
    return next((area for area in coverage_areas if area["id"] == area_id), None)


def _sorted_coverage_areas():
    sorted_areas = sorted(coverage_areas, key=lambda area: area["name"].lower())
    for area in sorted_areas:
        area.setdefault("travel_fee", None)
    return sorted_areas


def _get_certificate(certificate_id: int):
    return next((row for row in team_certificates if row.get("id") == certificate_id), None)


def _sorted_certificates():
    def _sort_key(certificate: dict):
        year = certificate.get("year") or ""
        return (year, certificate.get("title") or "")

    return sorted(team_certificates, key=_sort_key, reverse=True)


def _serialize_slot(slot: dict):
    date_label = slot["start"].strftime("%a %d %b")
    long_date_label = slot["start"].strftime("%A %d %B")
    time_label = slot["start"].strftime("%I:%M %p").lstrip("0")
    service_type = slot.get("service_type") or "walk"
    service_label = _service_label(service_type)
    price_amount = _parse_price(slot.get("price"))
    price_label = _format_price_label(price_amount)
    friendly_label = f"{service_label} · {long_date_label} at {time_label}"
    if price_label:
        friendly_label = f"{friendly_label} ({price_label})"
    visitor_area_name = slot.get("visitor_service_area_name") or ""
    visitor_travel_fee = _parse_price(slot.get("visitor_travel_fee"))
    visitor_travel_fee_label = _format_price_label(visitor_travel_fee)
    return {
        "id": slot["id"],
        "start_iso": slot["start"].isoformat(),
        "date_label": date_label,
        "long_date_label": long_date_label,
        "time_label": time_label,
        "friendly_label": friendly_label,
        "is_booked": slot.get("is_booked", False),
        "workflow_status": slot.get("workflow_status", ""),
        "visitor_name": slot.get("visitor_name") or "",
        "visitor_email": slot.get("visitor_email") or "",
        "visitor_dog_breed": slot.get("visitor_dog_breed") or "",
        "visitor_service_area": visitor_area_name,
        "visitor_service_area_id": slot.get("visitor_service_area_id"),
        "visitor_travel_fee": visitor_travel_fee,
        "visitor_travel_fee_label": visitor_travel_fee_label,
        "service_type": service_type,
        "service_label": service_label,
        "price": price_amount,
        "price_label": price_label,
    }


def _sorted_slots():
    return sorted(appointment_slots, key=lambda slot: slot["start"])


def _get_client_ip() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded_for or request.remote_addr or "Unknown"


def _get_location_from_headers() -> str:
    # These headers are commonly used by reverse proxies/CDNs to expose location data.
    city = request.headers.get("X-AppEngine-City")
    country = request.headers.get("CF-IPCountry")
    region = request.headers.get("X-AppEngine-Region")
    if city or region or country:
        location_parts = [part for part in [city, region, country] if part]
        return ", ".join(location_parts)
    # Fall back to the Accept-Language header as a best-effort signal.
    return request.headers.get("Accept-Language", "Unknown")


def _should_ignore_user_agent(user_agent: str) -> bool:
    if not user_agent:
        return False
    ua = user_agent.lower()
    return any(keyword in ua for keyword in IGNORED_USER_AGENT_KEYWORDS)


def _get_deepseek_api_key() -> Optional[str]:
    return os.environ.get("DEEPSEEK_API_KEY")


def _build_autopilot_messages(conversation: dict):
    global business_in_a_box
    history = conversation.get("messages", [])
    trimmed_history = history[-12:]
    system_prompt = (
        "You are Autopilot, a professional concierge for a dog walking and pet-care service. "
        "Respond with warmth, actionable next steps, and remind visitors they can book a meet-"
        "and-greet or slot from the site. Keep replies under 4 short paragraphs. You must follow "
        "the business-in-a-box brief below for every factual detail, especially pricing, service "
        "areas, onboarding steps, and offers—never invent information that is not in the brief. "
        "If the brief does not include an answer (such as a price that was not provided), clearly "
        "state that you'll connect them with a human instead of guessing. Reference the brief in "
        "your replies so visitors know you are following it."
        f"\n\nBusiness-in-a-box brief:\n{business_in_a_box.strip()}"
    )
    messages = [{"role": "system", "content": system_prompt}]
    for message in trimmed_history:
        sender = message.get("sender", "visitor")
        role = "assistant" if sender != "visitor" else "user"
        body = message.get("body", "")
        if not body:
            continue
        messages.append({"role": role, "content": body})
    return messages


def _call_deepseek_chat_completion(messages):
    api_key = _get_deepseek_api_key()
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY environment variable")
    payload = json.dumps(
        {
            "model": AUTOPILOT_MODEL_NAME,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": 600,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8") if exc.fp else exc.reason
        raise RuntimeError(f"DeepSeek error {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network failures
        raise RuntimeError(f"DeepSeek network error: {exc.reason}") from exc
    payload = json.loads(raw_body)
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("DeepSeek response did not include choices")
    content = choices[0].get("message", {}).get("content", "")
    return content.strip()


def _run_autopilot_if_needed(visitor_id: str):
    global autopilot_status
    if not autopilot_enabled or not visitor_id:
        return
    conversation = _get_conversation(visitor_id)
    if not conversation or not conversation.get("messages"):
        return
    autopilot_status.update(
        {
            "state": "responding",
            "last_run": datetime.utcnow().isoformat(),
            "last_error": None,
            "last_reply_preview": None,
            "last_visitor_id": visitor_id,
        }
    )
    try:
        messages = _build_autopilot_messages(conversation)
        reply = _call_deepseek_chat_completion(messages)
    except Exception as exc:  # pylint: disable=broad-except
        autopilot_status.update({"state": "error", "last_error": str(exc)})
        return
    if not reply:
        autopilot_status.update({"state": "no_reply", "last_reply_preview": None})
        return
    autopilot_status.update({"state": "answered", "last_reply_preview": reply[:200].strip()})
    _add_chat_message("admin", reply, visitor_id, trigger_autopilot=False)


def _record_visit(ip_address: str):
    user_agent = request.headers.get("User-Agent", "Unknown")
    if _should_ignore_user_agent(user_agent):
        return False
    visitor = visitor_stats.setdefault(
        ip_address,
        {
            "visits": 0,
            "first_visit": datetime.utcnow(),
            "last_visit": datetime.utcnow(),
            "location": "Unknown",
            "user_agent": "Unknown",
            "accept_language": "Unknown",
        },
    )
    visitor["visits"] += 1
    visitor["last_visit"] = datetime.utcnow()
    visitor["location"] = _get_location_from_headers() or visitor["location"]
    visitor["user_agent"] = user_agent or visitor["user_agent"]
    visitor["accept_language"] = request.headers.get("Accept-Language", visitor["accept_language"])
    return True


def _get_conversation(visitor_id: str, create: bool = False, ip_address: Optional[str] = None):
    if not visitor_id:
        return None
    if create:
        conversation = chat_conversations.setdefault(
            visitor_id,
            {
                "visitor_id": visitor_id,
                "ip_address": ip_address or _get_client_ip(),
                "created_at": datetime.utcnow(),
                "last_message_at": None,
                "messages": [],
            },
        )
        if ip_address:
            conversation["ip_address"] = ip_address
        return conversation
    return chat_conversations.get(visitor_id)


def _serialize_conversation(visitor_id: str):
    conversation = chat_conversations.get(visitor_id)
    if not conversation:
        return None
    unread = any(
        message["sender"] == "visitor" and not message.get("seen_by_admin", False)
        for message in conversation["messages"]
    )
    return {
        "visitor_id": visitor_id,
        "ip_address": conversation.get("ip_address", "Unknown"),
        "created_at": conversation.get("created_at", datetime.utcnow()).isoformat(),
        "unread": unread,
        "message_count": len(conversation["messages"]),
    }


def _get_conversation_messages(visitor_id: str):
    conversation = _get_conversation(visitor_id)
    if not conversation:
        return []
    return conversation["messages"]


def _all_messages():
    messages = []
    for conversation in chat_conversations.values():
        messages.extend(conversation["messages"])
    return sorted(messages, key=lambda msg: msg["id"])


def _pending_conversation_count() -> int:
    return sum(
        1
        for conversation in chat_conversations.values()
        if any(
            message["sender"] == "visitor" and not message.get("seen_by_admin", False)
            for message in conversation["messages"]
        )
    )


def _mark_conversation_as_read(visitor_id: Optional[str] = None):
    targets = []
    if visitor_id:
        conversation = chat_conversations.get(visitor_id)
        if conversation:
            targets.append(conversation)
    else:
        targets.extend(chat_conversations.values())
    for conversation in targets:
        for message in conversation["messages"]:
            if message["sender"] == "visitor":
                message["seen_by_admin"] = True


def _add_chat_message(
    sender: str,
    body: str,
    visitor_id: str,
    ip_address: Optional[str] = None,
    trigger_autopilot: bool = True,
):
    global next_chat_message_id
    visitor_id = visitor_id or _get_client_ip()
    conversation = _get_conversation(visitor_id, create=True, ip_address=ip_address)
    message = {
        "id": next_chat_message_id,
        "sender": sender,
        "body": body,
        "timestamp": datetime.utcnow().isoformat(),
        "seen_by_admin": sender != "visitor",
        "visitor_id": visitor_id,
        "visitor_ip": conversation.get("ip_address", "Unknown"),
    }
    conversation["messages"].append(message)
    conversation["last_message_at"] = datetime.utcnow()
    next_chat_message_id += 1
    _broadcast_chat_update({"type": "message", "message": message})
    if trigger_autopilot and sender == "visitor":
        _run_autopilot_if_needed(visitor_id)
    return message


def _delete_conversation(visitor_id: str) -> bool:
    conversation = chat_conversations.pop(visitor_id, None)
    if not conversation:
        return False
    _broadcast_chat_update({"type": "conversation_deleted", "visitor_id": visitor_id})
    return True


def _filter_payload_for_subscriber(subscriber: dict, payload: dict):
    role = subscriber["role"]
    visitor_id = subscriber.get("visitor_id")
    payload_type = payload.get("type")
    if payload_type == "message":
        message = payload.get("message")
        if not message:
            return None
        if role == "admin" or not visitor_id:
            return payload
        if message.get("visitor_id") == visitor_id:
            return payload
        return None
    if payload_type == "conversation_deleted":
        if role == "admin" or payload.get("visitor_id") == visitor_id:
            return payload
        return None
    return payload


def _broadcast_chat_update(payload):
    with chat_subscribers_lock:
        subscribers = list(chat_stream_subscribers)
    for subscriber in subscribers:
        filtered = _filter_payload_for_subscriber(subscriber, payload)
        if filtered is None:
            continue
        subscriber["queue"].put(filtered)


def _format_sse_payload(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _chat_event_stream(role: str, visitor_id: Optional[str] = None):
    subscriber_queue: queue.Queue = queue.Queue()
    subscriber = {"queue": subscriber_queue, "role": role, "visitor_id": visitor_id}
    with chat_subscribers_lock:
        chat_stream_subscribers.append(subscriber)

    def stream():
        try:
            if role == "admin":
                history_payload = {
                    "type": "history",
                    "messages": _all_messages(),
                    "conversations": [
                        data for data in (_serialize_conversation(cid) for cid in chat_conversations)
                        if data is not None
                    ],
                }
            else:
                history_payload = {
                    "type": "history",
                    "visitor_id": visitor_id,
                    "messages": _get_conversation_messages(visitor_id),
                }
            yield _format_sse_payload(history_payload)
            while True:
                try:
                    payload = subscriber_queue.get(timeout=25)
                except queue.Empty:
                    payload = {"type": "ping"}
                yield _format_sse_payload(payload)
        finally:
            with chat_subscribers_lock:
                chat_stream_subscribers[:] = [
                    existing
                    for existing in chat_stream_subscribers
                    if existing.get("queue") is not subscriber_queue
                ]

    return stream_with_context(stream())


@app.before_request
def track_visitors_and_block():
    if request.endpoint == "static":
        return
    ip_address = _get_client_ip()
    _record_visit(ip_address)
    if ip_address in blocked_ips and not request.path.startswith("/admin"):
        return (
            render_template("blocked.html", home_url=url_for("index")),
            403,
        )


@app.route("/", methods=["GET", "POST"])
def index():
    global next_submission_id

    if request.method == "POST":
        submission = {
            "id": next_submission_id,
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "message": request.form.get("message", "").strip(),
            "status": STATUS_OPTIONS[0],
        }
        submissions.append(submission)
        next_submission_id += 1
        return redirect(url_for("index", submitted=1))

    page_links = [
        {"label": "About Happy Trails", "href": url_for("hello_world_page", page_id=1)},
        {"label": "Our Services", "href": url_for("hello_world_page", page_id=2)},
        {"label": "Pricing Guide", "href": url_for("hello_world_page", page_id=3)},
        {"label": "Contact Options", "href": url_for("hello_world_page", page_id=4)},
        {"label": "Admin Page", "href": url_for("admin_page")},
    ]
    submission_success = request.args.get("submitted") == "1"
    slot_rows = [
        serialized
        for serialized in (_serialize_slot(slot) for slot in _sorted_slots())
        if serialized.get("service_type") == "walk"
    ]
    return render_template(
        "index.html",
        page_links=page_links,
        form_action=url_for("index"),
        submission_success=submission_success,
        booking_slots=slot_rows,
        dog_breeds=_sorted_breeds(),
        current_year=datetime.utcnow().year,
        primary_nav=_build_primary_nav("home"),
        coverage_areas=_sorted_coverage_areas(),
        format_price_label=_format_price_label,
        home_hero_image=_get_photo_url("home_hero"),
        home_profile_image=_get_photo_url("home_profile"),
        service_notice=_service_notice_state(),
        meet_greet_enabled=_meet_greet_setting(),
    )


@app.route("/bookings", methods=["GET"])
def bookings_page():
    slot_rows = [_serialize_slot(slot) for slot in _sorted_slots()]
    meet_slots = [slot for slot in slot_rows if slot.get("service_type") == "meet"]

    return render_template(
        "bookings.html",
        primary_nav=_build_primary_nav("bookings"),
        home_booking_url=f"{url_for('index')}#booking",
        meet_slots=meet_slots,
        dog_breeds=_sorted_breeds(),
        coverage_areas=_sorted_coverage_areas(),
        format_price_label=_format_price_label,
        datetime=datetime,
        bookings_hero_image=_get_photo_url("bookings_hero"),
        service_notice=_service_notice_state(),
        meet_greet_enabled=_meet_greet_setting(),
    )


@app.route("/page/<int:page_id>", methods=["GET"])
def hello_world_page(page_id: int):
    page = PAGE_DEFINITIONS.get(page_id)
    if not page:
        abort(404)
    page_data = dict(page)
    page_data["hero_image"] = _get_photo_url(f"page_{page_id}_hero")
    certificates = _sorted_certificates() if page.get("nav_key") == "about" else []
    return render_template(
        "info_page.html",
        page=page_data,
        home_url=url_for("index"),
        primary_nav=_build_primary_nav(page["nav_key"]),
        certificates=certificates,
        service_notice=_service_notice_state(),
    )


@app.route("/admin")
def admin_page():
    requested_view = (request.args.get("view") or "menu").strip().lower()
    active_view = requested_view if requested_view in ADMIN_VIEWS else "menu"
    visitor_rows = sorted(
        visitor_stats.items(),
        key=lambda item: item[1]["last_visit"],
        reverse=True,
    )
    conversation_rows = [
        data for data in (_serialize_conversation(cid) for cid in chat_conversations)
        if data is not None
    ]
    chat_waiting_count = _pending_conversation_count()
    slot_rows = [_serialize_slot(slot) for slot in _sorted_slots()]
    available_slots = [slot for slot in slot_rows if not slot["is_booked"]]
    booked_slots = [slot for slot in slot_rows if slot["is_booked"]]
    new_enquiry_count = sum(1 for submission in submissions if (submission.get("status") or "New") == "New")
    has_new_bookings = any((slot.get("workflow_status") or "New") == "New" for slot in booked_slots)
    site_photo_rows = _site_photo_rows()
    site_photo_groups = _group_photo_rows(site_photo_rows)
    custom_photo_count = sum(1 for row in site_photo_rows if not row["is_default"])
    state_action = request.args.get("state_action", "")
    state_messages = {
        "saved": "Settings saved to backup file.",
        "loaded": "Backup loaded successfully.",
        "save_failed": "Unable to save backup file.",
        "load_failed": "Backup file could not be loaded.",
        "missing": "No backup file was found to load.",
        "imported": "Uploaded backup applied successfully.",
        "import_failed": "Uploaded backup could not be processed.",
        "import_missing": "Please choose a backup file before uploading.",
        "import_invalid": "Uploaded file was not recognized as a valid backup.",
        "auto_import_missing": "No saved download was found to restore automatically.",
        "auto_import_failed": "Automatic restore failed. Please upload the JSON file manually.",
        "history_loaded": "Backup loaded from history.",
        "history_missing": "That backup entry was not found.",
        "history_load_failed": "Unable to load the selected history backup.",
        "history_deleted": "History entry deleted.",
    }
    state_backup_message = state_messages.get(state_action)
    error_actions = {
        "save_failed",
        "load_failed",
        "missing",
        "import_failed",
        "import_invalid",
        "import_missing",
        "auto_import_missing",
        "auto_import_failed",
        "history_load_failed",
        "history_missing",
    }
    state_backup_is_error = state_action in error_actions
    return render_template(
        "admin.html",
        home_url=url_for("index"),
        submissions=submissions,
        status_options=STATUS_OPTIONS,
        visitors=visitor_rows,
        blocked_ips=blocked_ips,
        chat_unread=chat_waiting_count > 0,
        chat_waiting_count=chat_waiting_count,
        chat_conversations=conversation_rows,
        chat_has_conversations=bool(conversation_rows),
        available_slots=available_slots,
        booked_slots=booked_slots,
        booking_status_options=BOOKING_WORKFLOW_STATUSES,
        booking_service_type_options=BOOKING_SERVICE_TYPE_OPTIONS,
        time_choices=DEFAULT_TIME_CHOICES,
        today=datetime.utcnow().strftime("%Y-%m-%d"),
        autopilot_enabled=autopilot_enabled,
        autopilot_status=autopilot_status,
        business_in_a_box=business_in_a_box,
        autopilot_model=AUTOPILOT_MODEL_NAME,
        autopilot_api_key_missing=_get_deepseek_api_key() is None,
        dog_breeds=_sorted_breeds(),
        breed_ai_suggestions=breed_ai_suggestions,
        new_enquiry_count=new_enquiry_count,
        has_new_bookings=has_new_bookings,
        visitor_count=len(visitor_rows),
        state_backup_metadata=_get_state_backup_metadata(),
        state_backup_message=state_backup_message,
        state_backup_is_error=state_backup_is_error,
        active_view=active_view,
        coverage_areas=_sorted_coverage_areas(),
        certificates=_sorted_certificates(),
        site_photo_groups=site_photo_groups,
        site_photo_total=len(site_photo_rows),
        site_photo_custom_count=custom_photo_count,
        service_notice=_service_notice_state(),
        meet_greet_enabled=_meet_greet_setting(),
        auto_save_enabled=auto_save_enabled,
        auto_save_last_run=auto_save_last_run,
        backup_history_rows=[_present_backup_history_entry(entry) for entry in backup_history],
    )


@app.route("/admin/site-photos", methods=["POST"])
def update_site_photo():
    global site_photos

    key = (request.form.get("photo_key") or "").strip()
    if key not in SITE_PHOTO_DEFAULTS:
        return redirect(url_for("admin_page", view="photos"))
    if request.form.get("reset"):
        site_photos[key] = SITE_PHOTO_DEFAULTS[key]["default_url"]
    else:
        url_value = (request.form.get("photo_url") or "").strip()
        site_photos[key] = url_value or SITE_PHOTO_DEFAULTS[key]["default_url"]
    return redirect(url_for("admin_page", view="photos"))


@app.route("/admin/state/save", methods=["POST"])
def save_admin_state():
    result = _write_state_backup(source="manual")
    if not result:
        return redirect(url_for("admin_page", state_action="save_failed", view="backups"))
    return redirect(url_for("admin_page", state_action="saved", view="backups"))


@app.route("/admin/state/auto-save/toggle", methods=["POST"])
def toggle_auto_save_setting():
    global auto_save_enabled

    auto_save_enabled = request.form.get("enabled") == "1"
    return redirect(url_for("admin_page", view="backups"))


@app.route("/admin/state/auto-save/run", methods=["POST"])
def run_auto_save():
    global auto_save_enabled, auto_save_last_run

    if not auto_save_enabled:
        return jsonify({"saved": False, "reason": "disabled"}), 400
    result = _write_state_backup(source="auto")
    if not result:
        return jsonify({"saved": False, "reason": "write_failed"}), 500
    history_entry = result.get("history_entry")
    if history_entry and isinstance(history_entry.get("saved_at"), datetime):
        auto_save_last_run = history_entry["saved_at"]
    else:
        auto_save_last_run = datetime.utcnow()
    payload = {"saved": True, "saved_at": auto_save_last_run.isoformat()}
    if history_entry:
        payload["history_entry"] = _present_backup_history_entry(history_entry, include_urls=True)
    return jsonify(payload)


@app.route("/admin/state/history/<int:entry_id>/load", methods=["POST"])
def load_backup_history_entry(entry_id: int):
    entry = _get_backup_history_entry(entry_id)
    if not entry:
        return redirect(url_for("admin_page", state_action="history_missing", view="backups"))
    storage_id = entry.get("storage_id")
    if storage_id:
        if not _load_state_from_database(storage_id):
            return redirect(url_for("admin_page", state_action="history_load_failed", view="backups"))
        return redirect(url_for("admin_page", state_action="history_loaded", view="backups"))
    legacy_path = entry.get("legacy_path")
    if not legacy_path or not os.path.exists(legacy_path):
        return redirect(url_for("admin_page", state_action="history_missing", view="backups"))
    try:
        with open(legacy_path, "r", encoding="utf-8") as backup_file:
            data = json.load(backup_file)
    except (OSError, json.JSONDecodeError):
        return redirect(url_for("admin_page", state_action="history_load_failed", view="backups"))
    _load_state(data)
    return redirect(url_for("admin_page", state_action="history_loaded", view="backups"))


@app.route("/admin/state/history/<int:entry_id>/delete", methods=["POST"])
def delete_backup_history_entry(entry_id: int):
    entry = _remove_backup_history_entry(entry_id)
    if not entry:
        return redirect(url_for("admin_page", state_action="history_missing", view="backups"))
    storage_id = entry.get("storage_id")
    if storage_id:
        _delete_backup_row(storage_id)
    legacy_path = entry.get("legacy_path")
    if legacy_path and os.path.exists(legacy_path):
        try:
            os.remove(legacy_path)
        except OSError:
            pass
    return redirect(url_for("admin_page", state_action="history_deleted", view="backups"))


@app.route("/admin/state/load", methods=["POST"])
def load_admin_state():
    row = _fetch_backup_row()
    if not row:
        return redirect(url_for("admin_page", state_action="missing", view="backups"))
    if not _load_state_from_database(row["id"]):
        return redirect(url_for("admin_page", state_action="load_failed", view="backups"))
    return redirect(url_for("admin_page", state_action="loaded", view="backups"))


@app.route("/admin/state/download", methods=["GET"])
def download_admin_state():
    """Provide the current in-memory state as a downloadable JSON file."""

    payload = json.dumps(_serialize_state(), indent=2)
    export_path = _state_export_file_path()
    try:
        with open(export_path, "w", encoding="utf-8") as export_file:
            export_file.write(payload)
    except OSError:
        app.logger.warning("Unable to write admin export to %s", export_path)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"dog-walking-admin-{timestamp}.json"
    headers = {
        "Content-Disposition": f"attachment; filename={filename}",
        "Cache-Control": "no-store",
    }
    return Response(payload, mimetype="application/json", headers=headers)


@app.route("/admin/state/import", methods=["POST"])
def import_admin_state():
    """Allow admins to upload a JSON backup and restore it immediately."""

    uploaded = request.files.get("state_file")
    raw_bytes = None
    if uploaded and uploaded.filename:
        try:
            raw_bytes = uploaded.read()
        except OSError:
            return redirect(url_for("admin_page", state_action="import_failed", view="backups"))
    else:
        export_path = _state_export_file_path()
        if not os.path.exists(export_path):
            return redirect(url_for("admin_page", state_action="auto_import_missing", view="backups"))
        try:
            with open(export_path, "rb") as export_file:
                raw_bytes = export_file.read()
        except OSError:
            return redirect(url_for("admin_page", state_action="auto_import_failed", view="backups"))
    if raw_bytes is None:
        return redirect(url_for("admin_page", state_action="import_failed", view="backups"))
    try:
        payload = raw_bytes.decode("utf-8")
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return redirect(url_for("admin_page", state_action="import_invalid", view="backups"))
    if not isinstance(data, dict):
        return redirect(url_for("admin_page", state_action="import_invalid", view="backups"))
    try:
        _load_state(data)
    except Exception:  # pragma: no cover - defensive; _load_state validates content
        return redirect(url_for("admin_page", state_action="import_failed", view="backups"))
    return redirect(url_for("admin_page", state_action="imported", view="backups"))


@app.route("/admin/autopilot", methods=["POST"])
def toggle_autopilot():
    global autopilot_enabled, autopilot_status
    enabled_value = request.form.get("enabled", "0")
    autopilot_enabled = enabled_value == "1"
    autopilot_status.update(
        {
            "state": "on" if autopilot_enabled else "off",
            "last_error": None if autopilot_enabled else autopilot_status.get("last_error"),
        }
    )
    return redirect(url_for("admin_page"))


@app.route("/admin/service-notice", methods=["POST"])
def update_service_notice():
    global site_service_notice

    enabled_value = request.form.get("enabled", "0")
    message_value = (request.form.get("message") or SERVICE_NOTICE_DEFAULT_TEXT).strip()
    if not message_value:
        message_value = SERVICE_NOTICE_DEFAULT_TEXT
    site_service_notice = {"enabled": enabled_value == "1", "message": message_value}
    return redirect(url_for("admin_page", view="status"))


@app.route("/admin/meet-greet", methods=["POST"])
def update_meet_greet_setting():
    global meet_greet_enabled

    enabled_value = request.form.get("enabled", "0")
    meet_greet_enabled = enabled_value == "1"
    return redirect(url_for("admin_page", view="status"))


@app.route("/admin/business-profile", methods=["POST"])
def update_business_profile():
    global business_in_a_box
    description = (request.form.get("business_box") or "").strip()
    business_in_a_box = description or BUSINESS_BOX_DEFAULT
    return redirect(url_for("admin_page"))


@app.route("/admin/dog-breeds", methods=["POST"])
def add_dog_breed():
    global next_dog_breed_id
    name = (request.form.get("breed_name") or "").strip()
    normalized = _normalize_breed_name(name)
    if normalized and not _breed_name_exists(normalized):
        dog_breeds.append({"id": next_dog_breed_id, "name": normalized})
        next_dog_breed_id += 1
    return redirect(url_for("admin_page", view="breeds"))


@app.route("/admin/coverage-areas", methods=["POST"])
def save_coverage_area():
    global coverage_areas, next_coverage_area_id
    area_id_value = request.form.get("area_id")
    name = (request.form.get("area_name") or "").strip()
    description = (request.form.get("area_description") or "").strip()
    travel_fee = _parse_price(request.form.get("area_travel_fee"))
    if not name:
        return redirect(url_for("admin_page", view="coverage"))
    if area_id_value:
        area = _get_coverage_area(_coerce_int(area_id_value, 0))
        if area:
            area["name"] = name
            area["description"] = description
            area["travel_fee"] = travel_fee
    else:
        coverage_areas.append(
            {
                "id": next_coverage_area_id,
                "name": name,
                "description": description,
                "travel_fee": travel_fee,
            }
        )
        next_coverage_area_id += 1
    return redirect(url_for("admin_page", view="coverage"))


@app.route("/admin/coverage-areas/<int:area_id>/delete", methods=["POST"])
def delete_coverage_area(area_id: int):
    global coverage_areas
    coverage_areas = [area for area in coverage_areas if area.get("id") != area_id]
    return redirect(url_for("admin_page", view="coverage"))


@app.route("/admin/dog-breeds/<int:breed_id>/delete", methods=["POST"])
def delete_dog_breed(breed_id: int):
    global dog_breeds
    dog_breeds = [breed for breed in dog_breeds if breed["id"] != breed_id]
    return redirect(url_for("admin_page", view="breeds"))


@app.route("/admin/certificates", methods=["POST"])
def save_certificate():
    global team_certificates, next_certificate_id
    certificate_id_value = request.form.get("certificate_id")
    title = (request.form.get("certificate_title") or "").strip()
    issuer = (request.form.get("certificate_issuer") or "").strip()
    year = (request.form.get("certificate_year") or "").strip()
    description = (request.form.get("certificate_description") or "").strip()
    image_url = (request.form.get("certificate_image_url") or "").strip()
    link_url = (request.form.get("certificate_link_url") or "").strip()
    if not title:
        return redirect(url_for("admin_page", view="credentials"))
    if certificate_id_value:
        certificate = _get_certificate(_coerce_int(certificate_id_value, 0))
        if certificate:
            certificate.update(
                {
                    "title": title,
                    "issuer": issuer,
                    "year": year,
                    "description": description,
                    "image_url": image_url,
                    "link_url": link_url,
                }
            )
    else:
        team_certificates.append(
            {
                "id": next_certificate_id,
                "title": title,
                "issuer": issuer,
                "year": year,
                "description": description,
                "image_url": image_url,
                "link_url": link_url,
            }
        )
        next_certificate_id += 1
    return redirect(url_for("admin_page", view="credentials"))


@app.route("/admin/certificates/<int:certificate_id>/delete", methods=["POST"])
def delete_certificate(certificate_id: int):
    global team_certificates
    team_certificates = [row for row in team_certificates if row.get("id") != certificate_id]
    return redirect(url_for("admin_page", view="credentials"))


def _extract_json_object(payload: str):
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        start = payload.find("{")
        end = payload.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(payload[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise ValueError("Unable to parse JSON from DeepSeek response")


@app.route("/admin/dog-breeds/ai", methods=["POST"])
def request_breed_ai():
    global breed_ai_suggestions
    prompt = (request.form.get("breed_prompt") or "").strip()
    if not prompt:
        breed_ai_suggestions = None
        return redirect(url_for("admin_page", view="breeds"))
    breed_ai_suggestions = {
        "prompt": prompt,
        "add": [],
        "remove": [],
        "error": None,
    }
    existing_list = ", ".join(breed["name"] for breed in _sorted_breeds()) or "none"
    system_message = (
        "You help a dog walking service curate a list of breeds. Respond ONLY with JSON "
        "matching this schema: {\"add\": [<breed>...], \"remove\": [<breed>...]}."
        " Breeds must be well-known, single-line names in Title Case. Never duplicate entries. "
        "Use \"add\" for breeds that match the request and \"remove\" for breeds that should be "
        "taken off the list."
    )
    user_message = (
        "Existing breeds: "
        f"{existing_list}\nInstruction: {prompt}\nReturn JSON only without commentary."
    )
    try:
        reply = _call_deepseek_chat_completion(
            [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ]
        )
        data = _extract_json_object(reply)
    except Exception as exc:  # pylint: disable=broad-except
        breed_ai_suggestions["error"] = str(exc)
        return redirect(url_for("admin_page", view="breeds"))
    add_items = []
    remove_items = []
    for key, target in (("add", add_items), ("remove", remove_items)):
        for value in data.get(key, []):
            value_str = _normalize_breed_name(str(value))
            if value_str and value_str not in target:
                target.append(value_str)
    breed_ai_suggestions.update({"add": add_items, "remove": remove_items})
    return redirect(url_for("admin_page", view="breeds"))


@app.route("/admin/dog-breeds/ai/apply", methods=["POST"])
def apply_breed_ai_suggestions():
    global breed_ai_suggestions, dog_breeds, next_dog_breed_id
    action = (request.form.get("action") or "").strip()
    selected = []
    for raw_name in request.form.getlist("breed"):
        normalized = _normalize_breed_name(raw_name)
        if normalized:
            selected.append(normalized)
    if not selected or action not in {"add", "remove"}:
        return redirect(url_for("admin_page", view="breeds"))
    if action == "add":
        for name in selected:
            if not _breed_name_exists(name):
                dog_breeds.append({"id": next_dog_breed_id, "name": name})
                next_dog_breed_id += 1
    elif action == "remove":
        target_names = {name.lower() for name in selected}
        dog_breeds = [breed for breed in dog_breeds if breed["name"].lower() not in target_names]
    if breed_ai_suggestions:
        if action == "add":
            breed_ai_suggestions["add"] = [
                name for name in breed_ai_suggestions.get("add", []) if name not in selected
            ]
        else:
            breed_ai_suggestions["remove"] = [
                name for name in breed_ai_suggestions.get("remove", []) if name not in selected
            ]
        if not breed_ai_suggestions["add"] and not breed_ai_suggestions["remove"]:
            breed_ai_suggestions = None
    return redirect(url_for("admin_page", view="breeds"))


@app.route("/admin/dog-breeds/ai/clear", methods=["POST"])
def clear_breed_ai_suggestions():
    global breed_ai_suggestions
    breed_ai_suggestions = None
    return redirect(url_for("admin_page", view="breeds"))


@app.route("/admin/slots", methods=["POST"])
def create_appointment_slot():
    global next_slot_id
    appointments_url = url_for("admin_page", view="appointments")
    date_value = (request.form.get("date") or "").strip()
    time_value = (request.form.get("time") or "").strip()
    price_input = (request.form.get("price") or "").strip()
    service_type = (request.form.get("service_type") or "walk").strip()
    if service_type not in BOOKING_SERVICE_TYPES:
        service_type = "walk"
    if not date_value or not time_value:
        return redirect(appointments_url)
    price_amount = _parse_price(price_input)
    if price_amount is None:
        return redirect(appointments_url)
    try:
        start = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
    except ValueError:
        return redirect(appointments_url)
    slot = {
        "id": next_slot_id,
        "start": start,
        "is_booked": False,
        "workflow_status": "",
        "visitor_name": None,
        "visitor_email": None,
        "visitor_dog_breed": None,
        "price": price_amount,
        "service_type": service_type,
    }
    appointment_slots.append(slot)
    appointment_slots.sort(key=lambda entry: entry["start"])
    next_slot_id += 1
    return redirect(appointments_url)


@app.route("/admin/slots/<int:slot_id>/status", methods=["POST"])
def update_slot_status(slot_id: int):
    slot = _get_slot(slot_id)
    if slot is None or not slot.get("is_booked"):
        abort(404)
    status = (request.form.get("status") or BOOKING_WORKFLOW_STATUSES[0]).strip()
    if status not in BOOKING_WORKFLOW_STATUSES:
        status = BOOKING_WORKFLOW_STATUSES[0]
    slot["workflow_status"] = status
    return redirect(url_for("admin_page", view="appointments"))


@app.route("/admin/slots/<int:slot_id>", methods=["POST"])
def update_appointment_slot(slot_id: int):
    slot = _get_slot(slot_id)
    if slot is None:
        abort(404)
    appointments_url = url_for("admin_page", view="appointments")
    date_value = (request.form.get("date") or "").strip()
    time_value = (request.form.get("time") or "").strip()
    price_input = (request.form.get("price") or "").strip()
    service_type = (request.form.get("service_type") or slot.get("service_type") or "walk").strip()
    if service_type not in BOOKING_SERVICE_TYPES:
        service_type = "walk"
    if not date_value or not time_value:
        return redirect(appointments_url)
    try:
        start = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
    except ValueError:
        return redirect(appointments_url)
    price_amount = None
    if price_input:
        price_amount = _parse_price(price_input)
        if price_amount is None:
            return redirect(appointments_url)
    slot.update({"start": start, "service_type": service_type, "price": price_amount})
    appointment_slots.sort(key=lambda entry: entry["start"])
    return redirect(appointments_url)


@app.route("/admin/slots/<int:slot_id>/delete", methods=["POST"])
def delete_appointment_slot(slot_id: int):
    global appointment_slots
    slot = _get_slot(slot_id)
    if slot is None:
        abort(404)
    appointment_slots = [entry for entry in appointment_slots if entry["id"] != slot_id]
    return redirect(url_for("admin_page", view="appointments"))


@app.route("/bookings/slots/<int:slot_id>", methods=["POST"])
def book_appointment_slot(slot_id: int):
    slot = _get_slot(slot_id)
    if slot is None:
        return jsonify({"error": "Slot not found"}), 404
    if slot.get("is_booked"):
        return jsonify({"error": "This slot has already been booked"}), 400
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or request.form.get("name") or "").strip()
    email = (payload.get("email") or request.form.get("email") or "").strip()
    breed_id_value = (payload.get("breed_id") or request.form.get("breed_id") or "").strip()
    coverage_area_id_value = (
        payload.get("coverage_area_id") or request.form.get("coverage_area_id") or ""
    ).strip()
    breed = None
    coverage_area = None
    if breed_id_value:
        try:
            breed_id = int(breed_id_value)
        except (TypeError, ValueError):
            breed_id = None
        if breed_id is not None:
            breed = _get_breed(breed_id)
    if coverage_area_id_value:
        try:
            coverage_area_id = int(coverage_area_id_value)
        except (TypeError, ValueError):
            coverage_area_id = None
        if coverage_area_id is not None:
            coverage_area = _get_coverage_area(coverage_area_id)
    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400
    if not breed:
        return jsonify({"error": "Please select your dog's breed"}), 400
    if not coverage_area:
        return jsonify({"error": "Please select your service area"}), 400
    travel_fee = _parse_price(coverage_area.get("travel_fee"))
    slot.update(
        {
            "is_booked": True,
            "visitor_name": name,
            "visitor_email": email,
            "visitor_dog_breed": breed["name"],
            "visitor_service_area_id": coverage_area["id"],
            "visitor_service_area_name": coverage_area.get("name"),
            "visitor_travel_fee": travel_fee,
            "workflow_status": BOOKING_WORKFLOW_STATUSES[0],
            "booked_at": datetime.utcnow(),
        }
    )
    serialized_slot = _serialize_slot(slot)
    return jsonify({"slot": serialized_slot})


@app.route("/admin/submissions/<int:submission_id>/edit", methods=["GET", "POST"])
def edit_submission(submission_id: int):
    submission = _get_submission(submission_id)
    if submission is None:
        abort(404)

    if request.method == "POST":
        submission.update(
            {
                "name": request.form.get("name", "").strip(),
                "email": request.form.get("email", "").strip(),
                "phone": request.form.get("phone", "").strip(),
                "message": request.form.get("message", "").strip(),
                "status": request.form.get("status", STATUS_OPTIONS[0]).strip()
                if request.form.get("status", STATUS_OPTIONS[0]).strip() in STATUS_OPTIONS
                else STATUS_OPTIONS[0],
            }
        )
        return redirect(url_for("admin_page"))

    submission.setdefault("status", STATUS_OPTIONS[0])
    return render_template(
        "edit_submission.html",
        submission=submission,
        home_url=url_for("index"),
        admin_url=url_for("admin_page"),
        status_options=STATUS_OPTIONS,
    )


@app.route("/admin/submissions/<int:submission_id>/status", methods=["POST"])
def update_submission_status(submission_id: int):
    submission = _get_submission(submission_id)
    if submission is None:
        abort(404)

    status = request.form.get("status", STATUS_OPTIONS[0]).strip()
    if status not in STATUS_OPTIONS:
        status = STATUS_OPTIONS[0]

    submission["status"] = status
    return redirect(url_for("admin_page"))


@app.route("/admin/submissions/<int:submission_id>/delete", methods=["POST"])
def delete_submission(submission_id: int):
    submission = _get_submission(submission_id)
    if submission is None:
        abort(404)

    submissions.remove(submission)
    return redirect(url_for("admin_page"))


@app.route("/admin/visitors/<path:ip_address>/block", methods=["POST"])
def block_visitor(ip_address: str):
    blocked_ips.add(ip_address)
    return redirect(url_for("admin_page"))


@app.route("/admin/visitors/<path:ip_address>/unblock", methods=["POST"])
def unblock_visitor(ip_address: str):
    blocked_ips.discard(ip_address)
    return redirect(url_for("admin_page"))


@app.route("/chat/messages", methods=["GET", "POST"])
def chat_messages_endpoint():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        sender = data.get("sender", "visitor").strip().lower()
        body = (data.get("body") or "").strip()
        visitor_id = (data.get("visitor_id") or "").strip()
        if sender not in {"visitor", "admin"} or not body:
            return jsonify({"error": "Invalid message"}), 400
        if sender == "admin" and not visitor_id:
            return jsonify({"error": "visitor_id is required"}), 400
        if sender == "visitor" and not visitor_id:
            visitor_id = request.headers.get("X-Visitor-Id", "").strip()
        if sender == "visitor" and not visitor_id:
            visitor_id = _get_client_ip()
        if not visitor_id:
            return jsonify({"error": "Unable to determine visitor"}), 400
        ip_address = _get_client_ip() if sender == "visitor" else None
        message = _add_chat_message(sender, body, visitor_id, ip_address=ip_address)
        return jsonify(message), 201

    after_id_raw = request.args.get("after", "0")
    try:
        after_id = int(after_id_raw)
    except ValueError:
        after_id = 0
    role = request.args.get("role", "visitor").strip().lower()
    visitor_id = (request.args.get("visitor_id", "") or "").strip()
    if role != "admin" and not visitor_id:
        visitor_id = request.headers.get("X-Visitor-Id", "").strip()
    if role != "admin" and not visitor_id:
        visitor_id = _get_client_ip()
    if role == "admin" and visitor_id:
        base_messages = _get_conversation_messages(visitor_id)
    elif role == "admin":
        base_messages = _all_messages()
    else:
        base_messages = _get_conversation_messages(visitor_id)
    messages_to_send = [message for message in base_messages if message["id"] > after_id]
    payload = {"messages": messages_to_send}
    if role == "admin":
        payload["conversations"] = [
            data for data in (_serialize_conversation(cid) for cid in chat_conversations)
            if data is not None
        ]
    else:
        payload["visitor_id"] = visitor_id
    return jsonify(payload)


@app.route("/admin/chat/read", methods=["POST"])
def mark_chat_as_read():
    data = request.get_json(silent=True) or {}
    visitor_id = (data.get("visitor_id") or request.form.get("visitor_id") or "").strip()
    _mark_conversation_as_read(visitor_id or None)
    return ("", 204)


@app.route("/admin/chat/<path:visitor_id>/delete", methods=["POST"])
def delete_chat_conversation(visitor_id: str):
    if not visitor_id:
        abort(404)
    _delete_conversation(visitor_id)
    return ("", 204)


@app.route("/chat/stream")
def chat_stream():
    role = request.args.get("role", "visitor").strip().lower()
    visitor_id = (request.args.get("visitor_id") or "").strip()
    if role != "admin" and not visitor_id:
        visitor_id = request.headers.get("X-Visitor-Id", "").strip()
    if role != "admin" and not visitor_id:
        visitor_id = _get_client_ip()
    response = Response(_chat_event_stream(role=role, visitor_id=visitor_id), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    app.run(debug=True)
