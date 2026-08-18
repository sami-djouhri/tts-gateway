FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
RUN chmod -R a+rX /app/app

RUN useradd -r -u 999 appuser
USER appuser

EXPOSE 8146
CMD ["python", "-m", "app"]
