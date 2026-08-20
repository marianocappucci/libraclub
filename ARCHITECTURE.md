# Arquitectura

## Forma general

Un proceso FastAPI que sirve la API y el build de la SPA en el **mismo origen**,
contra un PostgreSQL 16 propio. Una instancia por cliente; adentro de la
instancia, N sucursales.

```
                    ┌──────────────────────────────┐
   navegador  ─────►│  uvicorn app.asgi:app        │
                    │   /api/*  →  routers         │
                    │   /auth/* →  libraauth       │
                    │   /*      →  SPA (catch-all) │
                    └──────────────┬───────────────┘
                                   │
                          ┌────────▼────────┐
                          │  PostgreSQL 16  │
                          └─────────────────┘
```

El build de la SPA se hornea en `/opt/frontend-dist`, **fuera de `/app`**: el
compose de dev monta `./:/app` entero para el `--reload` de Python, y eso
taparía cualquier build copiado adentro del árbol.

## Capas

| Carpeta | Qué vive ahí |
|---|---|
| `app/models/` | SQLAlchemy 2 declarativo. Nada de lógica de negocio |
| `app/schemas/` | Pydantic. El contrato de la API, en ISO 8601 |
| `app/servicios/` | Las reglas. No importan FastAPI |
| `app/routers/` | HTTP: validar, delegar, traducir errores a códigos |

Los servicios no conocen el framework para que se puedan probar sin levantar la
app. Los routers no toman decisiones de negocio.

## Motores de la familia que se consumen

| Motor | Qué se usa | Cuándo entra |
|---|---|---|
| `libraauth` | Sesión, usuarios, roles, cookie propia | F1 |
| `libracore` | `respaldo` (backup/restore) | F1 |
| `libracore` | `mp_api` (Mercado Pago), `pdf_generator` | F2 |
| `libracore` | `arca_facturacion`, `arca_wsaa`, `arca_wsfe` | F3 |
| `libragenda` | `RecurrenceRule`, `generate_occurrences`, `intervals_overlap`, `ReminderPolicy` | F1/F2 |
| `libracommerce` | Catálogo, stock, POS del buffet | F4 |
| `libra-ui` | Componentes compartidos de la suite | F1 |

De `libragenda` se consume **dominio puro, no persistencia** — el motivo está en
`DECISIONS.md` ADR-004.

## El modelo de F1

```
sucursales ──┬── canchas ──┬── tarifas
             │             └── reservas ──┬── (F2) señas
             ├── cajas (F3)               └── series
             └── punto de venta ARCA (F3)
                                clientes ─┘
```

### `reservas` es una sola tabla, y los bloqueos están adentro

Un bloqueo por mantenimiento, lluvia o torneo **es una fila de `reservas`** con
`estado = 'bloqueo'`. No una tabla aparte.

El motivo es el constraint: la garantía de no-superposición es un `EXCLUDE
USING gist` sobre `(cancha_id, periodo)`, y un constraint sólo puede mirar su
propia tabla. Un bloqueo en otra tabla **no podría impedir una reserva** — habría
que volver a chequear en la aplicación, que es exactamente lo que este diseño
evita.

### La garantía de no-superposición

`periodo` es una columna **generada** (`tstzrange(comienza_at, termina_at,
'[)')`), y el constraint es:

```sql
EXCLUDE USING gist (cancha_id WITH =, periodo WITH &&)
    WHERE (estado IN ('provisoria','pendiente_pago','confirmada','jugada','bloqueo'))
```

Intervalo **semiabierto**: un turno que termina 20:00 y otro que empieza 20:00
no se solapan. Con `[]` se solaparían por el instante compartido y no se podrían
encadenar dos turnos seguidos.

Los estados del `WHERE` son los que ocupan la cancha (ADR-006). Cancelar libera
el turno porque la fila sale del predicado del índice — no porque alguien la
borre.

### Cómo se traduce al usuario

El servicio valida antes y devuelve un mensaje útil. Si igual llega el
`IntegrityError` —que es el caso concurrente, el que importa— se traduce por el
**nombre de la constraint**, no por el texto del error, y sale un `409`.

## Zona horaria

La base guarda `timestamptz`, la API habla ISO 8601, y el formateo `dd-mm-aaaa`
vive en `app/tiempo.py` y en un helper del frontend. Argentina, UTC-3 fijo, sin
horario de verano.

Las **tarifas** son la excepción que hay que mirar con cuidado: una franja
"18:00 a 23:00" es hora de pared del complejo, no un instante. Se guardan como
`time` y se resuelven contra la hora local de la reserva, nunca contra UTC.

## Autenticación

`libraauth` con cookie de sesión propia (`club_session`). Nombre propio a
propósito: dos instancias de productos distintos bajo el mismo dominio padre se
pisarían la sesión si compartieran nombre.

El backoffice de la suite administra los usuarios de la instancia con
`LIBRA_SERVICE_TOKEN`. Sin ese token, esas rutas piden sesión de admin — falla
cerrado, y un token vacío no abre nada.
