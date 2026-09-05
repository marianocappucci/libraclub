# syntax=docker/dockerfile:1

# Stage aparte para el frontend (React+Vite), mismo patrón que el resto de la
# familia: node no hace falta en la imagen final, sólo el resultado del build.
FROM node:22-slim AS frontend-build
WORKDIR /frontend
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build
# 🔴 `npm run build` devuelve 0 aunque `tsc -b` haya fallado y no haya escrito
# nada. Sin esta línea la imagen se construye igual y sirve un 404 donde iba la
# SPA — un deploy verde que no desplegó nada.
RUN test -f dist/index.html || { echo "ERROR: el build del frontend no dejo dist/index.html"; exit 1; }

FROM python:3.12-slim

# F1 (2026-09-05): las dependencias de terceros salen de `uv.lock`, no de la
# resolucion de pip del dia del build. Dos builds del mismo commit dan la misma
# imagen. El binario viene de la imagen oficial, pineada por version; el venv
# vive FUERA de /app porque el compose de dev monta ./:/app encima y lo taparia.
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

# Huso horario del ecosistema: UTC-3 fijo, sin horario de verano.
ENV TZ=America/Argentina/Buenos_Aires \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# `postgresql-client` trae `pg_dump` y `pg_restore`, que es lo que corre
# `libracore.respaldo`. Sin ellos la pantalla de Backup falla con un mensaje
# explícito —no en silencio—, pero falla.
#
# 🔴 Va en la etapa FINAL y no en la del frontend: un paquete instalado en un
# stage que se descarta se ve igual de bien leyendo el Dockerfile y no está en
# la imagen.
#
# 🔴 El cliente va CLAVADO en la major del servidor (`postgres:16`), no ">= la
# del servidor". Vale para `pg_dump`, que puede dumpear de un servidor más
# viejo; `pg_restore` al revés NO: el 17 abre la sesión con
# `SET transaction_timeout = 0`, un parámetro que el 16 no conoce, y como el
# restore corre con `--single-transaction` **aborta entero**. Si algún día sube
# la imagen del sidecar en `docker-compose.yml`, sube este número en el mismo
# movimiento. Son un par, no dos decisiones.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl git ca-certificates gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

# Que el binario esté, y que sea el 16. Lo segundo importa tanto como lo
# primero: un `pg_restore` de otra major se instala sin quejarse y falla recién
# el día que alguien restaura.
RUN pg_restore --version | grep -q ' 16\.' \
 || { echo "ERROR: pg_restore no es 16.x -> $(pg_restore --version)"; exit 1; }

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN uv sync --frozen --no-dev --no-editable

COPY alembic.ini ./
COPY migrations ./migrations

# Horneado FUERA de /app a propósito: el docker-compose de dev monta `./:/app`
# entero para el reload de Python, y eso taparía cualquier build copiado
# adentro. `app/asgi.py` mira primero acá.
COPY --from=frontend-build /frontend/dist /opt/frontend-dist

# `data/` es el punto de montaje del volumen donde caen los ZIP de backup. Se
# crea en la imagen para que nazca con el dueño correcto: Docker le copia el
# propietario al volumen la primera vez, y si no existiera quedaría de root y el
# proceso —que corre sin privilegios— no podría escribirlo.
RUN mkdir -p /app/data \
 && useradd -m -u 10001 libraclub && chown -R libraclub /app
USER libraclub

EXPOSE 8000

# El healthcheck consulta la base: `/salud` hace un `SELECT 1` antes de
# contestar, así que si PostgreSQL no responde el contenedor no se reporta sano.
# Falla cerrado a propósito.
#
# 🔴 **Mira el CUERPO, no el código HTTP, y eso no es prolijidad.** Con
# `curl -fsS` el chequeo **no podía fallar**: `-f` sólo reacciona a un código
# >= 400, y este backend sirve la SPA con un catch-all, así que cualquier ruta
# devuelve `200 text/html` mientras uvicorn sirva estáticos. Medido el
# 2026-08-25 en los contenedores vivos: `curl -fsS` contra una ruta inventada
# daba **exit 0** en los cinco de estos dos productos.
#
# `json.load` sobre el `index.html` revienta, que es exactamente lo que se
# busca; `isinstance(..., dict)` y no una clave concreta porque el cuerpo
# difiere entre productos. Es la misma forma que ya usan los seis composes de
# la familia y el generador de instancias de LibraCore.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python3", "-c", "import json,urllib.request; assert isinstance(json.load(urllib.request.urlopen('http://localhost:8000/salud', timeout=3)), dict)"]

CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
