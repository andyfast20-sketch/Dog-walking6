import json
import queue
import threading
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


def _get_submission(submission_id: int):
    return next((submission for submission in submissions if submission["id"] == submission_id), None)


def _get_slot(slot_id: int):
    return next((slot for slot in appointment_slots if slot["id"] == slot_id), None)


def _serialize_slot(slot: dict):
    date_label = slot["start"].strftime("%a %d %b")
    long_date_label = slot["start"].strftime("%A %d %B")
    time_label = slot["start"].strftime("%I:%M %p").lstrip("0")
    return {
        "id": slot["id"],
        "start_iso": slot["start"].isoformat(),
        "date_label": date_label,
        "long_date_label": long_date_label,
        "time_label": time_label,
        "friendly_label": f"{long_date_label} at {time_label}",
        "is_booked": slot.get("is_booked", False),
        "workflow_status": slot.get("workflow_status", ""),
        "visitor_name": slot.get("visitor_name") or "",
        "visitor_email": slot.get("visitor_email") or "",
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


def _add_chat_message(sender: str, body: str, visitor_id: str, ip_address: Optional[str] = None):
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
        {"label": "Page 1", "href": url_for("hello_world_page", page_id=1)},
        {"label": "Page 2", "href": url_for("hello_world_page", page_id=2)},
        {"label": "Page 3", "href": url_for("hello_world_page", page_id=3)},
        {"label": "Page 4", "href": url_for("hello_world_page", page_id=4)},
        {"label": "Admin Page", "href": url_for("admin_page")},
    ]
    submission_success = request.args.get("submitted") == "1"
    slot_rows = [_serialize_slot(slot) for slot in _sorted_slots()]
    return render_template(
        "index.html",
        page_links=page_links,
        form_action=url_for("index"),
        submission_success=submission_success,
        booking_slots=slot_rows,
    )


@app.route("/page/<int:page_id>", methods=["GET"])
def hello_world_page(page_id: int):
    if page_id not in range(1, 5):
        abort(404)
    if page_id == 1:
        return render_template(
            "page1.html",
            home_url=url_for("index"),
            contact_url=url_for("index"),
        )
    return render_template("hello_world.html", home_url=url_for("index"))


@app.route("/admin")
def admin_page():
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
        time_choices=DEFAULT_TIME_CHOICES,
        today=datetime.utcnow().strftime("%Y-%m-%d"),
    )


@app.route("/admin/slots", methods=["POST"])
def create_appointment_slot():
    global next_slot_id
    date_value = (request.form.get("date") or "").strip()
    time_value = (request.form.get("time") or "").strip()
    if not date_value or not time_value:
        return redirect(url_for("admin_page"))
    try:
        start = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
    except ValueError:
        return redirect(url_for("admin_page"))
    slot = {
        "id": next_slot_id,
        "start": start,
        "is_booked": False,
        "workflow_status": "",
        "visitor_name": None,
        "visitor_email": None,
    }
    appointment_slots.append(slot)
    appointment_slots.sort(key=lambda entry: entry["start"])
    next_slot_id += 1
    return redirect(url_for("admin_page"))


@app.route("/admin/slots/<int:slot_id>/status", methods=["POST"])
def update_slot_status(slot_id: int):
    slot = _get_slot(slot_id)
    if slot is None or not slot.get("is_booked"):
        abort(404)
    status = (request.form.get("status") or BOOKING_WORKFLOW_STATUSES[0]).strip()
    if status not in BOOKING_WORKFLOW_STATUSES:
        status = BOOKING_WORKFLOW_STATUSES[0]
    slot["workflow_status"] = status
    return redirect(url_for("admin_page"))


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
    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400
    slot.update(
        {
            "is_booked": True,
            "visitor_name": name,
            "visitor_email": email,
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
