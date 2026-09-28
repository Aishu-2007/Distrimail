import json
import mimetypes
import os
import smtplib
import socket
import time
import ssl
from email.message import EmailMessage

import redis

import database
from config import (
    QUEUE_NAME, REDIS_URL, SMTP_EMAIL, SMTP_HOST, SMTP_PASSWORD,
    SMTP_PORT, SMTP_USE_SSL, SPAM_WORDS, UPLOAD_FOLDER
)

WORKER_NAME = os.environ.get("WORKER_NAME", socket.gethostname() + "-" + str(os.getpid()))
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def is_spam(subject, body):
    text = (subject + " " + body).lower()
    return any(word in text for word in SPAM_WORDS)


def send_real_email(email_id):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        raise RuntimeError("SMTP_EMAIL/SMTP_PASSWORD missing. Create .env and set a Gmail App Password.")
    if SMTP_HOST == "smtp.gmail.com" and SMTP_PORT not in (465, 587):
        raise RuntimeError("For Gmail use SMTP_PORT=465 with SMTP_USE_SSL=true, or port 587 with SMTP_USE_SSL=false.")

    email = database.get_email(email_id)
    if not email:
        raise RuntimeError("Email record not found")

    message = EmailMessage()
    message["From"] = SMTP_EMAIL
    message["To"] = email["receiver_email"]
    message["Subject"] = email["subject"]
    message.set_content(email["body"].replace("[[SIMULATE_FAILURE]]\n", ""))

    for attachment in database.get_attachments(email_id):
        path = os.path.join(UPLOAD_FOLDER, attachment["filepath"])
        if not os.path.exists(path):
            raise RuntimeError(f"Attachment not found: {attachment['filename']}")
        content_type, _ = mimetypes.guess_type(path)
        if content_type:
            maintype, subtype = content_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        with open(path, "rb") as file:
            message.add_attachment(
                file.read(), maintype=maintype, subtype=subtype,
                filename=attachment["filename"]
            )

    # Gmail: use either SSL/465 or STARTTLS/587.
    # The authenticated Gmail account must match SMTP_EMAIL, and SMTP_PASSWORD
    # must be a Google App Password when 2-Step Verification is enabled.
    if SMTP_USE_SSL:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30, context=context) as server:
            server.ehlo()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(message)


def process_email(email_id):
    email = database.get_email(email_id)
    if not email:
        print("Email not found:", email_id)
        return

    database.update_email_processing(email_id, WORKER_NAME)
    print(f"Processing Email ID: {email_id} -> {email['receiver_email']}")

    try:
        time.sleep(1)
        if "[[SIMULATE_FAILURE]]" in email["body"]:
            raise RuntimeError("Demo failure requested by the sender.")

        # Internal DistriMail delivery: if the recipient has a DistriMail account,
        # deliver directly to that user's inbox. Gmail SMTP is only needed for
        # recipients who are outside DistriMail.
        if email["receiver_id"] is not None:
            folder = "SPAM" if is_spam(email["subject"], email["body"]) else "INBOX"
            database.mark_email_sent(email_id, folder)
            database.worker_processed(WORKER_NAME)
            print(f"Email ID: {email_id} delivered internally to {email['receiver_email']}", flush=True)
            return

        # External recipient: send through the configured SMTP provider.
        send_real_email(email_id)
        folder = "SPAM" if is_spam(email["subject"], email["body"]) else "INBOX"
        database.mark_email_sent(email_id, folder)
        database.worker_processed(WORKER_NAME)
        print(f"Email ID: {email_id} delivered to {email['receiver_email']}")

    except smtplib.SMTPAuthenticationError as error:
        database.mark_email_retry(email_id)
        retry_count = database.get_retry_count(email_id)
        message = (
            "Gmail authentication failed. Check SMTP_EMAIL and use a Google App Password "
            "in SMTP_PASSWORD (not your normal Gmail password). "
            f"SMTP response: {error.smtp_code} {error.smtp_error!r}"
        )
        if retry_count >= 3:
            database.mark_email_failed(email_id)
            database.worker_failed(WORKER_NAME)
            print(f"Email ID: {email_id} FAILED after 3 attempts: {message}", flush=True)
        else:
            print(f"Email ID: {email_id} failed: {message}. Retry {retry_count}/3", flush=True)
            time.sleep(1)
            redis_client.rpush(QUEUE_NAME, json.dumps({"email_id": email_id}))
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, OSError) as error:
        database.mark_email_retry(email_id)
        retry_count = database.get_retry_count(email_id)
        message = f"SMTP connection error: {error}"
        if retry_count >= 3:
            database.mark_email_failed(email_id)
            database.worker_failed(WORKER_NAME)
            print(f"Email ID: {email_id} FAILED after 3 attempts: {message}", flush=True)
        else:
            print(f"Email ID: {email_id} failed: {message}. Retry {retry_count}/3", flush=True)
            time.sleep(1)
            redis_client.rpush(QUEUE_NAME, json.dumps({"email_id": email_id}))
    except Exception as error:
        database.mark_email_retry(email_id)
        retry_count = database.get_retry_count(email_id)
        if retry_count >= 3:
            database.mark_email_failed(email_id)
            database.worker_failed(WORKER_NAME)
            print(f"Email ID: {email_id} FAILED after 3 attempts: {type(error).__name__}: {error}", flush=True)
        else:
            print(f"Email ID: {email_id} failed: {type(error).__name__}: {error}. Retry {retry_count}/3", flush=True)
            time.sleep(1)
            redis_client.rpush(QUEUE_NAME, json.dumps({"email_id": email_id}))


def main():
    database.init_db()
    database.register_worker(WORKER_NAME)
    try:
        redis_client.ping()
    except redis.RedisError:
        print("Redis container is not reachable. Start Docker Compose first.")
        return

    print(f"Worker started: {WORKER_NAME}")
    print("Waiting for email jobs...")
    last_heartbeat = 0

    while True:
        try:
            if time.time() - last_heartbeat > 3:
                database.heartbeat_worker(WORKER_NAME)
                last_heartbeat = time.time()
            result = redis_client.blpop(QUEUE_NAME, timeout=3)
            if not result:
                continue
            _, job_text = result
            email_id = json.loads(job_text).get("email_id")
            if email_id:
                print(f"Received Email ID: {email_id}")
                process_email(email_id)
        except KeyboardInterrupt:
            print(f"Worker stopped: {WORKER_NAME}")
            break
        except Exception as error:
            print("Worker error:", error)
            time.sleep(2)


if __name__ == "__main__":
    main()
