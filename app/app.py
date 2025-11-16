from flask import Flask, abort, redirect, render_template, request, url_for

app = Flask(__name__)


submissions = []
next_submission_id = 1
STATUS_OPTIONS = ["New", "In Process", "Finished"]


def _get_submission(submission_id: int):
    return next((submission for submission in submissions if submission["id"] == submission_id), None)


@app.route("/", methods=["GET", "POST"])
def index():
    global next_submission_id

    if request.method == "POST":
        status = request.form.get("status", STATUS_OPTIONS[0]).strip()
        if status not in STATUS_OPTIONS:
            status = STATUS_OPTIONS[0]

        submission = {
            "id": next_submission_id,
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "message": request.form.get("message", "").strip(),
            "status": status,
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
        status_options=STATUS_OPTIONS,
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
    return render_template("admin.html", home_url=url_for("index"), submissions=submissions)


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


@app.route("/admin/submissions/<int:submission_id>/delete", methods=["POST"])
def delete_submission(submission_id: int):
    submission = _get_submission(submission_id)
    if submission is None:
        abort(404)

    submissions.remove(submission)
    return redirect(url_for("admin_page"))


if __name__ == "__main__":
    app.run(debug=True)
