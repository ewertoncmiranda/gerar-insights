# ISS-04: imagem publica no Docker Hub. O .dockerignore deixa de fora .env*,
# env/, .git, venvs e caches; a configuracao chega por variavel de ambiente.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Usuario sem privilegio: o worker nao precisa de root para nada.
RUN useradd --create-home --uid 10001 app
COPY --chown=app:app . .
USER app

CMD ["python", "main.py"]
