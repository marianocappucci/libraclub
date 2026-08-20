# LibraClub

Vertical de **complejos deportivos** de la familia Libra: canchas de pádel,
fútbol, tenis y cualquier otro espacio reservable por franja horaria.

La promesa: **más ocupación y menos coordinación manual, con la reserva
integrada a la caja y a la factura argentina** — que es exactamente lo que
ningún competidor del mercado argentino de reservas hace hoy.

## Estado

**F1 en construcción.** Canchas, tarifas, calendario, reservas, bloqueos y
reservas fijas recurrentes. Sin portal público, sin cobro online y sin buffet
todavía — ver [ROADMAP.md](ROADMAP.md).

Nació el 2026-08-20 como **inversión de producto**, sin piloto comprometido.
El grupo de cinco complejos de pádel que motivó el análisis descartó las
reservas de su compra de ContaLibra; queda como upsell natural cuando esa
instalación esté operando.

## Documentación

- [ROADMAP.md](ROADMAP.md) — dirección estratégica y fases.
- [TASKS.md](TASKS.md) — trabajo concreto vigente.
- [ARCHITECTURE.md](ARCHITECTURE.md) — arquitectura actual.
- [CONVENTIONS.md](CONVENTIONS.md) — estándares del código.
- [DECISIONS.md](DECISIONS.md) — decisiones y motivos.
- [CHANGELOG.md](CHANGELOG.md) — releases publicados.

## Stack

FastAPI + SQLAlchemy 2 + Alembic sobre **PostgreSQL 16**, y React 19 +
TypeScript + Vite + Tailwind + `libra-ui` en el frontend. El build de la SPA se
hornea en la imagen y lo sirve el mismo proceso FastAPI, en el mismo origen que
la API.

Motores de la familia: `libraauth` (sesión y usuarios) y `libracore` (backup,
y más adelante PDF, MercadoPago y ARCA). De `libragenda` se consume su **lógica
de dominio pura** — recurrencia y política de recordatorios — pero **no su
persistencia**; el motivo está en `DECISIONS.md` ADR-004.

## Desarrollo

```bash
cp .env.example .env      # y completar
docker compose up --build
```

La API queda en `http://localhost:8099`. Para el frontend con recarga:

```bash
cd frontend && npm ci && npm run dev
```

## Despliegue de una instancia `dev`

El checkout vive en `/root/<producto>` del VPS y **se actualiza con `git pull`,
nunca editando archivos ahí**: la fuente de verdad es este repo.

```bash
ssh mi-vps
git clone git@github-libraclub:marianocappucci/libraclub.git /root/libraclub
cd /root/libraclub && git checkout develop
# el .env se genera EN EL SERVIDOR, chmod 600, y nunca se versiona
docker compose up -d --build
docker compose exec -T libraclub-dev alembic upgrade head
docker compose exec -T libraclub-dev python scripts/semilla_dev.py
```

Cuatro cosas que no se pueden saltear, cada una porque ya falló en la familia:

1. **El puerto publicado tiene que ser único en el host.** Elegirlo mirando
   `ss -ltn` —lo que escucha de verdad— y no la lista de Docker: hay servicios
   del VPS que escuchan sin ser contenedores.
2. **La deploy key va con alias propio, y el alias antes del `Host *`** de
   `~/.ssh/config`. SSH usa la primera coincidencia: un alias declarado después
   del genérico autentica con otra identidad, y GitHub lo acepta igual.
   Verificar con `ssh -T github-libraclub` — el saludo tiene que nombrar **este**
   repo.
3. **Las migraciones no las corre el arranque.** El contenedor levanta *healthy*
   con la base vacía, porque `/salud` sólo hace `SELECT 1`.
4. **El proxy host de Nginx Proxy Manager se crea por la API**, no editando los
   `.conf`: esos archivos son generados desde `database.sqlite` y se revierten
   en el próximo arranque de NPM. Y con `certificate_id: "new"` hay que **volver
   a pedir el host y corregirlo con un `PUT`**: NPM emite el certificado
   *después* de guardar, así que `ssl_forced` y `http2_support` quedan apagados
   aunque el alta los haya mandado en `true`.

## Tests

Corren **contra PostgreSQL real**, nunca contra SQLite: una suite verde sobre
SQLite no dice nada sobre el motor de producción, y este producto se apoya en
un constraint de exclusión que SQLite ni siquiera tiene.

```bash
pip install -e '.[dev]'
pytest -q
```
