FROM python:3.12-slim

# Keeps Python from writing .pyc files
# Keeps stdout/stderr unbuffered so logs appear immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy deps first — Docker caches this layer until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source after deps are installed
COPY bot/ bot/

# Run as non-root — good practice, avoids running as UID 0 inside the container
RUN adduser --disabled-password --gecos "" botuser
USER botuser

CMD ["python", "-m", "bot.main"]
