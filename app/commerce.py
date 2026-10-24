"""De dónde sale el repositorio de LibraCommerce en LibraClub.

Existe por una sola razón, la misma que en VentaLibra: que **ningún servicio
construya el repositorio desnudo**. Envuelto, cada escritura queda en
`actividad_log`; desnudo, no — y no se nota, porque el log sigue mostrando las
filas de los otros servicios y parece sano.

`test_ningun_servicio_usa_el_repositorio_desnudo` es lo que lo sostiene: falla si
alguien vuelve a importar `SqliteCommerceRepository` fuera de este archivo.

⚠️ **Con DOS bases, `actividad_log` es un SEGUNDO log, distinto del de la pantalla
de Logs.** El de `/logs` es el de `libraauth` y vive en la base del dominio; éste
es el del motor comercial y vive en la de LibraCore. No es una duplicación a
resolver acá: son dos bases y dos motores. Lo que sí es un pendiente es que la
pantalla de Logs muestre los dos — hoy muestra uno.

🔑 **Con UNA sola base (ADR-020) son la misma tabla.** Las dos definiciones de
`actividad_log` —la de `libraauth` y la del motor comercial— tienen las mismas
columnas a propósito, así que `/logs` ve también lo que escribe el buffet y el
pendiente de arriba desaparece solo cuando la instancia se une. El código no
cambia: `repositorio()` sigue abriendo la conexión de LibraCore, que ahí es la
del dominio.
"""

from __future__ import annotations

import sqlite3

from libraauth.auditoria import registrador_dbapi
from libracommerce.db.auditoria import (
    CREAR,
    Cambio,
    RepositorioAuditado,
    entidades_por_tabla,
    opciones_del_registrador,
)
from libracommerce.db.repository import SqliteCommerceRepository
from libracore.db import core as libracore_core

#: Quién arma la fila de `actividad_log`. Desde libracommerce v0.57.0 (ADR-050) el
#: motor no tiene formato propio: le pasa un `Cambio` a un registrador, y el de
#: `libraauth` es el mismo que usa el resto de la familia. Se construye una vez y
#: sin cliente en la lista blanca: LibraClub no configura `libracore.auditoria`.
#: El usuario ya no es un parámetro del envoltorio: el registrador lo lee del
#: `ContextVar` de `libraauth`, que llena `agregar_middleware_de_usuario` en cada
#: request (fuera de un request, «Sistema»).
_REGISTRADOR = registrador_dbapi(entidades_por_tabla(), **opciones_del_registrador())


def repositorio(conexion: sqlite3.Connection | None = None) -> RepositorioAuditado:
    """El repositorio del motor comercial, auditado.

    Sin argumento abre su propia conexión contra la base de LibraCore. El
    usuario de cada fila lo resuelve el registrador, del `ContextVar` de
    `libraauth` (ver `_REGISTRADOR`).
    """
    conn = conexion or libracore_core.get_connection()
    return RepositorioAuditado(SqliteCommerceRepository(conn), conn, _REGISTRADOR)


def auditar_alta(conn, tabla: str, fila_id: int, valores: dict) -> None:
    """Anota en `actividad_log`, con la `conn` que recibe, el alta de una fila que el motor escribió por SQL.

    Para lo que NO pasa por `repositorio()`: `registrar_venta` del motor escribe la venta con SQL, fuera del
    envoltorio auditado, y sin esto la venta del buffet dejaría de verse en `/logs`. No confirma: corre en la
    transacción de quien la llama, así el alta y la fila quedan juntas o no queda ninguna.
    """
    _REGISTRADOR(conn, Cambio(tabla=tabla, accion=CREAR, id=fila_id, antes=None, despues=valores))
