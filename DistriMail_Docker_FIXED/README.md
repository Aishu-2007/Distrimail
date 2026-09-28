# DistriMail - Docker + Real Email

A beginner-friendly distributed email website using Flask, SQLite, Redis, Docker, Python workers, and Gmail SMTP.

## What is used
- VS Code
- Docker Desktop
- Flask
- SQLite
- Redis (Docker container)
- Python worker containers
- Gmail SMTP for real email delivery
- HTML/CSS/JavaScript

## Not used
- React / Angular / Vue
- Node.js
- MongoDB
- Celery / Kafka / Kubernetes
- Socket.IO / WebSockets / browser notifications
- Memurai or a locally installed Redis

## Folder structure
```text
DistriMail_Docker/
├── app.py
├── worker.py
├── database.py
├── config.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── templates/
├── static/
├── database/
└── uploads/
```

## Requirements
Only install:
1. Docker Desktop for Windows
2. VS Code

You do NOT need Python, Redis, or Memurai installed on Windows because they run in Docker.

## Step 1: Open in VS Code
Extract the ZIP and open the `DistriMail_Docker` folder in VS Code.

## Step 2: Create .env
Copy `.env.example` to a new file named `.env`.

Example:
```env
SMTP_EMAIL=yourgmail@gmail.com
SMTP_PASSWORD=your_16_character_app_password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USE_SSL=true
DISTRI_SECRET_KEY=change-this-secret-key
```

For Gmail, enable 2-Step Verification and create a Google App Password. Never use or share your normal Gmail password.

## Step 3: Start everything
Open the VS Code terminal in the project folder and run:

```powershell
docker compose up --build --scale worker=3
```

This starts:
- 1 Flask web container
- 1 Redis container
- 3 worker containers

Keep the terminal open.

Open the website:

`http://localhost:5000`

## Step 4: Send a real email
Register/login with the Gmail address configured in `.env`.

Go to Compose and enter a real recipient such as:
```text
To: friend@gmail.com
Subject: Test from DistriMail
Message: Hello from my distributed email project.
```

The message goes:
```text
Browser
  -> Flask
  -> SQLite
  -> Redis queue
  -> Worker 1/2/3
  -> Gmail SMTP
  -> Real recipient mailbox
```

The recipient does NOT need a DistriMail account for real SMTP delivery.

## Step 5: See the containers
In another VS Code terminal:
```powershell
docker compose ps
```

You should see the app, Redis, and worker containers.

To see logs:
```powershell
docker compose logs -f app
```

Worker logs:
```powershell
docker compose logs -f worker
```

Redis logs:
```powershell
docker compose logs -f redis
```

## Step 6: Stop
Press `Ctrl+C` in the terminal running compose, or run:
```powershell
docker compose down
```

The named volumes keep the SQLite database, uploads, and Redis data.

To completely reset the project data:
```powershell
docker compose down -v
```
WARNING: this deletes the Docker volumes containing project data.

## Common problems

### Docker command not found
Install Docker Desktop and restart VS Code.

### Docker Desktop is not running
Open Docker Desktop and wait until it says Docker is running.

### Gmail authentication failed
Check `.env`. Use a Google App Password, not your normal Gmail password.

### Port 5000 already in use
Stop the application using port 5000, or change the left side of the compose mapping from `5000:5000` to `5001:5000`, then open `http://localhost:5001`.

### Redis is not running
You do not need to install Redis on Windows. Run:
```powershell
docker compose up --build --scale worker=3
```
Redis is started automatically as the `redis` container.

## Viva explanation
DistriMail is a Flask-based distributed email service. The Flask application accepts an email and stores it in SQLite, then places a job in a Redis queue. Multiple worker containers consume jobs from the queue and send real emails using Gmail SMTP. Docker packages the application, Redis, and workers so the complete system can be started consistently with one command.

## If email shows FAILED
Run in a second terminal:

    docker compose logs -f worker

The worker prints the exact SMTP error. For Gmail, use a Google App Password, not the normal Gmail password.
Use:

    SMTP_EMAIL=yourgmail@gmail.com
    SMTP_PASSWORD=your16characterapppassword
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=465
    SMTP_USE_SSL=true

After changing `.env`:

    docker compose down
    docker compose up --build --scale worker=3

Test with 3 workers first. Only scale to 50 after one email sends successfully.
