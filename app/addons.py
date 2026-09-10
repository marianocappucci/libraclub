"""El gate de los add-ons: `require_addon(nombre)`.

LibraClub **no tiene gating por módulo**: los tres planes están vacíos a
propósito (ver el docstring de `plans.py`). Lo único gateable son los add-ons
de `plans.ADDONS`, que se prenden por instancia desde el backoffice, y esto es
lo mínimo para gatearlos.

🔴 **Por qué no el `require_module` del motor** (`libracore.modules_gate`): lee
`request.app.state.modules`, que este producto no carga — no hay plan con
módulos que cargar. Usarlo acá daría un error por atributo faltante en cada
request, o, peor, un día alguien le pondría un `app.state.modules = {}` para
callarlo y el gate quedaría decidiendo sobre un diccionario que nadie llena. Esto
lee la tabla `modulos` en cada request, que es lo mismo que escribe el
backoffice: prenderlo tiene efecto inmediato, sin reiniciar el contenedor.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from app import database
from app.servicios import facturacion

_log = logging.getLogger(__name__)


def require_addon(nombre: str):
    """Dependencia que corta con 403 salvo que el add-on esté prendido en esta instancia.

    🔑 **Falla cerrado, y con 403 — nunca con 500.** La pantalla compartida de
    `libra-ui` trata el 403 como "tu plan no lo incluye" y esconde la tarjeta;
    un 500 lo mostraría como un error. Y sin poder leer el estado no se sabe si
    el cliente lo contrató, así que lo que corresponde es no servirlo:

    - Sin base de LibraCore (instancia sin `LIBRACLUB_LIBRACORE_DATABASE_URL`)
      no hay tabla `modulos` de dónde leer: 403 sin intentar conectarse.
    - Si la lectura falla —falta la tabla, la base no contesta—, 403 y un
      warning en el log con el motivo, para que no quede mudo.
    - Sin fila para el add-on, o con la fila en falso: 403. Viene apagado.
    """

    def _gate() -> None:
        prendido = False
        if facturacion.hay_base():
            try:
                prendido = bool(database.get_modulos().get(nombre, False))
            # Amplio a propósito: cualquier falla de lectura es "apagado".
            except Exception:
                _log.warning("No se pudo leer el add-on %r; se trata como apagado", nombre, exc_info=True)
        if not prendido:
            raise HTTPException(403, f"El add-on '{nombre}' no está habilitado en esta instancia.")

    return _gate
