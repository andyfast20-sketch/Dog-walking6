from flask import Flask, abort, render_template, url_for

app = Flask(__name__)


@app.route("/")
def index():
    page_links = [
        {"label": "Page 1", "href": url_for("hello_world_page", page_id=1)},
        {"label": "Page 2", "href": url_for("hello_world_page", page_id=2)},
        {"label": "Page 3", "href": url_for("hello_world_page", page_id=3)},
        {"label": "Page 4", "href": url_for("hello_world_page", page_id=4)},
        {"label": "Admin Page", "href": url_for("admin_page")},
    ]
    return render_template("index.html", page_links=page_links)


@app.route("/page/<int:page_id>")
def hello_world_page(page_id: int):
    if page_id not in range(1, 5):
        abort(404)
    return render_template("hello_world.html", home_url=url_for("index"))


@app.route("/admin")
def admin_page():
    return render_template("admin.html", home_url=url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
