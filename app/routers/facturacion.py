"""La guarda de la facturacion: 503 con el motivo cuando falta la base.

Hasta el 2026-08-30 este modulo tenia ademas el router de `GET`/`PUT
/config/arca`. Lo sirve ahora `libracore.arca_router`, que sobre el mismo
prefijo hace lo que este no podia: subir el certificado y la clave, validarlos
antes de escribirlos, decir cuando vence, y autenticar contra WSAA.

🔴 Lo que NO vino del motor y por eso este archivo sigue existiendo es
`exigir_base`. El router del kit no sabe nada de
`LIBRACLUB_LIBRACORE_DATABASE_URL`: sin esta dependencia, una instancia sin esa
variable contestaria un 500 generico y el complejo veria "algo fallo" sin saber
que lo que hay que hacer es agregar una variable de entorno.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.servicios import facturacion


def exigir_base() -> None:
    """503 y no 500 si la instancia no tiene base de LibraCore.

    🔑 El mensaje dice **qué falta**, porque el síntoma del lado de la pantalla
    es idéntico al de un error cualquiera: sin esto, un complejo sin configurar
    vería "algo falló" y nadie sabría que lo que hay que hacer es agregar una
    variable de entorno.

    Pública —y no `_exigir_base`— porque la comparte `routers/facturas.py`: son
    los dos routers de la MISMA funcionalidad, partida en dos prefijos
    (`/config/arca` por el kit, `/api/facturas` por la convención del producto),
    así que les corresponde el mismo mensaje.

    ⚠️ `buffet.py` y `cuenta_corriente.py` tienen cada uno el suyo y **no hay que
    unificarlos con éste**: lo único que cambia es el sujeto de la frase —"El
    buffet", "La cuenta corriente"— y ahí está todo el valor. Un mensaje genérico
    diría que falta una variable sin decir qué se rompe por no tenerla.
    """
    if not facturacion.hay_base():
        raise HTTPException(
            503,
            "La facturación no está configurada en esta instancia: falta "
            "LIBRACLUB_LIBRACORE_DATABASE_URL.",
        )
