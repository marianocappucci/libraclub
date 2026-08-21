"""De dónde sale el repositorio de LibraCommerce en LibraClub.

Existe por una sola razón, la misma que en VentaLibra: que **ningún servicio
construya el repositorio desnudo**. Envuelto, cada escritura queda en
`actividad_log`; desnudo, no — y no se nota, porque el log sigue mostrando las
filas de los otros servicios y parece sano.

`test_ningun_servicio_usa_el_repositorio_desnudo` es lo que lo sostiene: falla si
alguien vuelve a importar `SqliteCommerceRepository` fuera de este archivo.

⚠️ **`actividad_log` es un SEGUNDO log, distinto del de la pantalla de Logs.**
El de `/logs` es el de `libraauth` y vive en la base del dominio; éste es el del
motor comercial y vive en la de LibraCore. No es una duplicación a resolver acá:
son dos bases y dos motores. Lo que sí es un pendiente es que la pantalla de
Logs muestre los dos — hoy muestra uno.
"""

from __future__ import annotations

import sqlite3

from libraauth.auditoria import usuario_actual
from libracommerce.db.auditoria import RepositorioAuditado
from libracommerce.db.repository import SqliteCommerceRepository
from libracore.db import core as libracore_core


def repositorio(conexion: sqlite3.Connection | None = None) -> RepositorioAuditado:
    """El repositorio del motor comercial, auditado.

    Sin argumento abre su propia conexión contra la base de LibraCore. El
    usuario sale del `ContextVar` de `libraauth`, que llena
    `agregar_middleware_de_usuario` en cada request: se pasa como callable y no
    como valor porque cambia por request, y va de este lado para que el motor
    comercial no dependa del de auth.
    """
    conn = conexion or libracore_core.get_connection()
    return RepositorioAuditado(
        SqliteCommerceRepository(conn), conn, usuario=usuario_actual.get
    )
