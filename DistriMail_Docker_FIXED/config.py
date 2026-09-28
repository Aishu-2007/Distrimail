import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATABASE_PATH = os.path.join(BASE_DIR, "database", "email.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

SECRET_KEY = os.environ.get("DISTRI_SECRET_KEY", "distrimail-dev-secret-change-me")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "email_queue"

MAX_FILE_SIZE = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "png", "jpg", "jpeg"}
SPAM_WORDS = ["lottery", "winner", "free money", "click here", "urgent prize"]

# Real outgoing email settings. Use a Gmail App Password, not your normal password.
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "true").lower() == "true"
