import json
import os
import re
import uuid

import redis
from flask import (
    Flask, flash, jsonify, redirect, render_template,
    request, send_from_directory, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import database
from config import (
    ALLOWED_EXTENSIONS, MAX_FILE_SIZE, QUEUE_NAME, REDIS_URL,
    SECRET_KEY, SPAM_WORDS, UPLOAD_FOLDER
)

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


os.makedirs(UPLOAD_FOLDER, exist_ok=True)
database.init_db()

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def logged_in():
    return "user_id" in session

def current_user():
    if not logged_in():
        return None
    return database.get_user_by_id(session["user_id"])

def valid_email(email):
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email or "") is not None

@app.context_processor
def inject_common():
    user = current_user()
    inbox_count = 0
    if user:
        inbox_count = len([
            row for row in database.get_inbox(user["id"]) if not row["is_read"]
        ])
    return {"current_user": user, "inbox_count": inbox_count}

@app.route("/")
def home():
    return redirect(url_for("inbox" if logged_in() else "login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if logged_in():
        return redirect(url_for("inbox"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = database.get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "danger")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        return redirect(url_for("inbox"))

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if logged_in():
        return redirect(url_for("inbox"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not name or not email or not password or not confirm:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if not valid_email(email):
            flash("Please enter a valid email address.", "danger")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("register.html")

        if password != confirm:
            flash("Password and confirm password must match.", "danger")
            return render_template("register.html")

        if database.get_user_by_email(email):
            flash("Email already registered.", "danger")
            return render_template("register.html")

        password_hash = generate_password_hash(password)
        database.create_user(name, email, password_hash)
        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def login_required(route_function):
    from functools import wraps

    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("login"))
        return route_function(*args, **kwargs)
    return wrapper

@app.route("/inbox")
@login_required
def inbox():
    user_id = session["user_id"]
    open_id = request.args.get("open", type=int)
    selected = None
    attachments = []

    if open_id:
        selected = database.get_email(open_id)
        if selected and selected["receiver_id"] == user_id:
            database.mark_email_read(open_id, user_id, True)
            selected = database.get_email(open_id)
            attachments = database.get_attachments(open_id)
        else:
            selected = None

    return render_template(
        "inbox.html",
        emails=database.get_inbox(user_id),
        selected=selected,
        attachments=attachments
    )

@app.route("/email/<int:email_id>/read/<int:value>")
@login_required
def toggle_read(email_id, value):
    database.mark_email_read(email_id, session["user_id"], value == 1)
    return redirect(request.referrer or url_for("inbox"))

@app.route("/email/<int:email_id>/trash")
@login_required
def move_to_trash(email_id):
    database.set_folder(email_id, session["user_id"], "TRASH")
    return redirect(request.referrer or url_for("inbox"))

@app.route("/trash")
@login_required
def trash():
    return render_template("trash.html", emails=database.get_folder(session["user_id"], "TRASH"))

@app.route("/trash/<int:email_id>/restore")
@login_required
def restore_email(email_id):
    database.set_folder(email_id, session["user_id"], "INBOX")
    return redirect(url_for("trash"))

@app.route("/trash/<int:email_id>/delete")
@login_required
def permanent_delete(email_id):
    database.delete_email_permanently(email_id, session["user_id"])
    return redirect(url_for("trash"))

@app.route("/spam")
@login_required
def spam():
    return render_template("spam.html", emails=database.get_folder(session["user_id"], "SPAM"))

@app.route("/spam/<int:email_id>/inbox")
@login_required
def move_spam_to_inbox(email_id):
    database.set_folder(email_id, session["user_id"], "INBOX")
    return redirect(url_for("spam"))

@app.route("/sent")
@login_required
def sent():
    return render_template("sent.html", emails=database.get_sent(session["user_id"]))

@app.route("/compose", methods=["GET", "POST"])
@login_required
def compose():
    if request.method == "POST":
        receiver_email = request.form.get("to", "").strip().lower()
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        simulate_failure = request.form.get("simulate_failure") == "on"

        if not valid_email(receiver_email):
            flash("Please enter a valid recipient email.", "danger")
            return render_template("compose.html")

        if not subject:
            flash("Subject cannot be empty.", "danger")
            return render_template("compose.html")

        if not body:
            flash("Message cannot be empty.", "danger")
            return render_template("compose.html")

        receiver = database.get_user_by_email(receiver_email)
        receiver_id = receiver["id"] if receiver else None
        receiver_name = receiver["name"] if receiver else receiver_email

        # This marker is only for the local demo retry test.
        if simulate_failure:
            body = "[[SIMULATE_FAILURE]]\n" + body

        email_id = database.create_email(
            session["user_id"], receiver_id, receiver_email, receiver_name, subject, body
        )

        file = request.files.get("attachment")
        if file and file.filename:
            if not allowed_file(file.filename):
                database.delete_email_permanently(email_id, session["user_id"])
                flash("Unsupported attachment type.", "danger")
                return render_template("compose.html")

            original_name = secure_filename(file.filename)
            if not original_name:
                database.delete_email_permanently(email_id, session["user_id"])
                flash("Invalid attachment filename.", "danger")
                return render_template("compose.html")

            stored_name = str(uuid.uuid4()) + "_" + original_name
            file.save(os.path.join(UPLOAD_FOLDER, stored_name))
            database.add_attachment(email_id, original_name, stored_name)

        try:
            redis_client.rpush(QUEUE_NAME, json.dumps({"email_id": email_id}))
        except redis.RedisError:
            database.mark_email_failed(email_id)
            flash("Redis is not running. Email could not be queued.", "danger")
            return render_template("compose.html")

        flash("Email queued successfully! A background worker will process it.", "success")
        return redirect(url_for("sent"))

    return render_template("compose.html")

@app.route("/attachment/<int:attachment_id>")
@login_required
def download_attachment(attachment_id):
    connection = database.get_connection()
    row = connection.execute("""
        SELECT a.*, e.sender_id, e.receiver_id
        FROM attachments a
        JOIN emails e ON e.id = a.email_id
        WHERE a.id = ?
    """, (attachment_id,)).fetchone()
    connection.close()

    if not row or session["user_id"] not in (row["sender_id"], row["receiver_id"]):
        flash("Attachment not found.", "danger")
        return redirect(url_for("inbox"))

    return send_from_directory(
        UPLOAD_FOLDER, row["filepath"], as_attachment=True,
        download_name=row["filename"]
    )

@app.route("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()
    results = database.search_emails(session["user_id"], query) if query else []
    return render_template("search.html", results=results, query=query)

@app.route("/admin")
def admin():
    stats = database.get_stats()
    workers = database.get_workers()
    recent_jobs = database.get_recent_jobs()
    try:
        queue_size = redis_client.llen(QUEUE_NAME)
    except redis.RedisError:
        queue_size = -1

    # A worker is considered offline if it has not sent a heartbeat for 10 seconds.
    from datetime import datetime, timezone
    fresh_workers = []
    for worker in workers:
        status = worker["status"]
        if worker["last_seen"]:
            try:
                last = datetime.strptime(worker["last_seen"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last).total_seconds()
                if age > 10:
                    status = "OFFLINE"
            except ValueError:
                status = "OFFLINE"
        else:
            status = "OFFLINE"

        item = dict(worker)
        item["display_status"] = status
        fresh_workers.append(item)

    return render_template(
        "admin.html",
        stats=stats,
        workers=fresh_workers,
        recent_jobs=recent_jobs,
        queue_size=queue_size
    )

@app.errorhandler(413)
def too_large(_error):
    flash("File size is too large. Maximum allowed size is 5 MB.", "danger")
    return redirect(url_for("compose"))

if __name__ == "__main__":
    try:
        redis_client.ping()
        print("Redis connection: OK")
    except redis.RedisError:
        print("WARNING: Redis container is not reachable. Start Docker Compose before sending emails.")

    print("DistriMail running at http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
