# The bot only talks to the backend over HTTP, so it needs none of the
# backend's dependencies or databases. Built from the project root:
#     docker compose --profile bot build bot
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY bot/requirements.txt bot/requirements.txt
RUN pip install --no-cache-dir -r bot/requirements.txt

COPY bot/ bot/

CMD ["python", "-m", "bot"]
