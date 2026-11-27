# Hauseigenes Basisbild (docker/basis-image, ZIELBILD 46 B3): python:3.13-slim mit der
# Upgrade-Schicht, jede Nacht frisch gebaut. Ein Bau mit --pull holt den Stand der Nacht.
FROM 127.0.0.1:5000/homelab/python:3.13

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
