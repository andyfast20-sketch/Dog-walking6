from datetime import datetime

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)


submissions = []
next_submission_id = 1
STATUS_OPTIONS = ["New", "In Process", "Finished"]
visitor_stats = {}
blocked_ips = set()
chat_messages = []
next_chat_message_id = 1


IGNORED_USER_AGENT_KEYWORDS = ["vercel-screenshot"]


def _get_submission(submission_id: int):
    return next((submission for submission in submissions if submission["id"] == submission_id), None)


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


def _add_chat_message(sender: str, body: str):
    global next_chat_message_id
    message = {
        "id": next_chat_message_id,
        "sender": sender,
        "body": body,
        "timestamp": datetime.utcnow().isoformat(),
        "seen_by_admin": sender != "visitor",
    }
    chat_messages.append(message)
    next_chat_message_id += 1
    return message


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
    return render_template(
        "index.html",
        page_links=page_links,
        form_action=url_for("index"),
        submission_success=submission_success,
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
    has_unread_chat = any(
        message["sender"] == "visitor" and not message.get("seen_by_admin", False)
        for message in chat_messages
    )
    return render_template(
        "admin.html",
        home_url=url_for("index"),
        submissions=submissions,
        status_options=STATUS_OPTIONS,
        visitors=visitor_rows,
        blocked_ips=blocked_ips,
        chat_unread=has_unread_chat,
    )


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
        if sender not in {"visitor", "admin"} or not body:
            return jsonify({"error": "Invalid message"}), 400
        message = _add_chat_message(sender, body)
        return jsonify(message), 201

    after_id_raw = request.args.get("after", "0")
    try:
        after_id = int(after_id_raw)
    except ValueError:
        after_id = 0
    messages_to_send = [message for message in chat_messages if message["id"] > after_id]
    return jsonify({"messages": messages_to_send})


@app.route("/admin/chat/read", methods=["POST"])
def mark_chat_as_read():
    for message in chat_messages:
        if message["sender"] == "visitor":
            message["seen_by_admin"] = True
    return ("", 204)


if __name__ == "__main__":
    app.run(debug=True)
