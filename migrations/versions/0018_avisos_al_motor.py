"""Los avisos de LibraClub pasan al motor: `avisos` -> `avisos_envios` (ADR-030; libracore ADR-090).

Qué hace:

1. **Lleva cada fila de `avisos` a `avisos_envios`** (la tabla del motor, `libracore.avisos`) con la misma clave que va a
   calcular el barrido nuevo (`reserva:{id}:{tipo}:{horas_antes|-}`), el mismo estado y los mismos intentos. Es lo que
   evita que el primer barrido nuevo vuelva a mandar lo que el viejo ya mandó: sin esto, la 1ª corrida le reenvía a cada
   cliente el recordatorio de las próximas 24 horas, y la confirmación de las últimas 2.
   - `registrado` queda `registrado`: el motor lo trata igual que LibraClub (cierra el tema sólo para un proveedor
     simulado; con Evolution se manda).
   - Las fechas pasan de `timestamptz` a la hora de Argentina como texto (`YYYY-MM-DD HH24:MI:SS`), que es como el
     motor guarda las suyas.
   - **Idempotente**: `ON CONFLICT (canal, clave) DO NOTHING`. Si el barrido nuevo ya escribió una clave, no se pisa.
2. **`config_avisos.whatsapp` pasa a ser nullable y deja de leerse.** El modo de WhatsApp es del motor (`config.json`,
   `avisos_whatsapp_modo`); si la fila decía `registro` y el motor sigue en su default (`apagado`), se lleva ese valor
   **una vez**. La columna no se borra: queda por si hay que volver atrás.

🔑 **`avisos` NO se borra ni se renombra.** Es el respaldo: si hay que volver a la imagen anterior, el código viejo
encuentra su tabla con lo que había hasta esta migración. Se borra en una migración aparte, cuando el motor lleve unas
semanas en producción. Volver atrás **después** de que corrió el barrido nuevo puede reenviar los avisos de las últimas
horas (el código viejo no ve lo que se mandó desde acá): el techo del daño es una ventana de recordatorios.

🔴 **Necesita `avisos_envios`, que crea la cadena del motor** (`libracore-migrar`, que corre antes que esta en el
compose, en `panel_admin.actualizar` y en `reset_demo.sh`). Si la tabla no está y `avisos` tiene filas, **falla** diciendo
qué correr: seguir sin ella sería dejar los avisos sin llevar, en silencio. Si no está y `avisos` está vacía (una base
nueva, o la de la suite, donde el motor arma su schema recién al arrancar la app) no hay nada que llevar y sigue.

Revision ID: 0018_avisos_al_motor
Revises: 0017_sena_del_mostrador_vence
Create Date: 2026-10-28
"""

import logging

import sqlalchemy as sa
from alembic import op

revision = "0018_avisos_al_motor"
down_revision = "0017_sena_del_mostrador_vence"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

#: Cómo el motor guarda las fechas de `avisos_envios`: hora de Argentina, como texto.
_HORA_AR = "'YYYY-MM-DD HH24:MI:SS'"
_ZONA = "'America/Argentina/Buenos_Aires'"

_LLEVAR = f"""
INSERT INTO avisos_envios
    (canal, clave, tipo, destino, asunto, cuerpo, plantilla, variables, proveedor, estado, intentos, detalle,
     id_externo, enviado_at, created_at, updated_at)
SELECT a.canal::text,
       'reserva:' || a.reserva_id || ':' || a.tipo::text || ':' || COALESCE(a.horas_antes::text, '-'),
       a.tipo::text,
       COALESCE(a.destino, ''),
       COALESCE(a.asunto, ''),
       COALESCE(a.cuerpo, ''),
       '',
       '{{}}',
       CASE WHEN a.estado::text = 'omitido' THEN ''
            WHEN a.canal::text = 'email' THEN 'smtp'
            ELSE 'registro' END,
       a.estado::text,
       a.intentos,
       left(COALESCE(a.detalle, ''), 500),
       '',
       COALESCE(to_char(a.enviado_at AT TIME ZONE {_ZONA}, {_HORA_AR}), ''),
       to_char(a.created_at AT TIME ZONE {_ZONA}, {_HORA_AR}),
       to_char(a.updated_at AT TIME ZONE {_ZONA}, {_HORA_AR})
FROM avisos a
ORDER BY a.id
ON CONFLICT (canal, clave) DO NOTHING
"""


def _existe(conexion, tabla: str) -> bool:
    return conexion.execute(sa.text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{tabla}"}).scalar_one()


def llevar_los_avisos(conexion) -> int:
    """Copia `avisos` a `avisos_envios`. Devuelve cuántas filas entraron (las que no estaban)."""
    en_avisos = conexion.execute(sa.text("SELECT count(*) FROM avisos")).scalar_one()
    if not _existe(conexion, "avisos_envios"):
        if en_avisos:
            raise RuntimeError(
                f"Hay {en_avisos} avisos para llevar al motor pero falta la tabla `avisos_envios`: corré "
                "`libracore-migrar upgrade --prefijo libraclub` (libracore >= 1.202.0) antes de `alembic upgrade head`."
            )
        return 0
    return conexion.execute(sa.text(_LLEVAR)).rowcount or 0


def llevar_el_modo_de_whatsapp(conexion) -> str | None:
    """Pasa el modo viejo de WhatsApp (`registro`) a la configuración del motor, si el motor no tiene uno propio.

    **Nunca hace fallar la migración**: el modo se vuelve a elegir en la pantalla «Avisos», y el peor caso de no llevarlo
    es que WhatsApp quede `apagado`, que es el default seguro. Devuelve el modo que dejó puesto, o `None`.
    """
    modo = conexion.execute(sa.text("SELECT whatsapp::text FROM config_avisos WHERE id = 1")).scalar_one_or_none()
    if modo != "registro":
        return None
    try:
        from libracore.avisos import configuracion

        if configuracion.leer().modo != configuracion.MODO_APAGADO:
            return None  # el motor ya tiene uno propio: manda él
        configuracion.guardar(modo=configuracion.MODO_REGISTRO)
    except Exception as e:  # noqa: BLE001 — nada de esto puede tumbar el deploy
        logger.warning(
            "No se pudo llevar el modo de WhatsApp «registro» al motor (%s): elegilo en la pantalla Avisos.",
            type(e).__name__,
        )
        return None
    return "registro"


def upgrade() -> None:
    conexion = op.get_bind()
    llevadas = llevar_los_avisos(conexion)
    logger.info("avisos -> avisos_envios: %s filas llevadas", llevadas)
    llevar_el_modo_de_whatsapp(conexion)
    op.alter_column("config_avisos", "whatsapp", nullable=True)


def downgrade() -> None:
    # La columna vuelve a ser obligatoria; las filas que escribió el código nuevo (sin modo) quedan en `apagado`.
    # `avisos_envios` es del motor y no se toca: lo que se mandó desde la subida no vuelve a `avisos`, así que el código
    # viejo puede reenviar los avisos de las últimas horas (ver el docstring).
    op.execute("UPDATE config_avisos SET whatsapp = 'apagado' WHERE whatsapp IS NULL")
    op.alter_column("config_avisos", "whatsapp", nullable=False)
