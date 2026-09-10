"""Módulos y add-ons de la instancia: el contrato que espera el backoffice.

🔴 **Este archivo existe por el backoffice, no por la app.** El backoffice
prende/apaga add-ons y lee su estado corriendo un snippet DENTRO de este
contenedor (`libracore.admin.services.set_addon` / `addons_de_instancia`), y ese
snippet hace `from app.database import get_modulos` / `set_addon`. Desde que
`plans.py` declara `ADDONS = {"resguardo_externo"}`, LibraClub tiene que cumplir
ese contrato: sin este módulo el `docker exec` muere con `ImportError` y el
backoffice muestra el add-on como "no se pudo leer".

⚠️ No confundir con `app/db.py`, que es el engine de SQLAlchemy de la base del
**dominio**. La tabla `modulos` no vive ahí: vive en la base de LibraCore
(`LIBRACLUB_LIBRACORE_DATABASE_URL`), la crea `init_core_schema()` y la lee
`libracore.db.modulos`. Acá no se copia lógica: se delega en esa implementación
única de la familia, con el mismo patrón que `libradesk/app/database.py`.
"""

from __future__ import annotations


def _asegurar_core_configurado() -> None:
    """Apunta `libracore.db.core` a la base de LibraCore de ESTA instancia si nadie lo hizo.

    Estas dos funciones tienen dos vidas muy distintas:

    - Dentro de la app, `crear_app()` ya configuró el core
      (`servicios.facturacion.configurar`) y acá no hay nada que hacer.
    - Bajo `docker exec python3 -c "from app.database import get_modulos"` no
      corrió ningún arranque, así que el core está sin configurar y
      `get_connection()` levanta `RuntimeError`. Ese caso se resuelve solo, sin
      pedirle al backoffice que bootee la app entera.

    🔴 **Con `core=True`.** En LibraClub la base del dominio y la de LibraCore
    son dos bases distintas (`app/config.py`), y `modulos` está en la segunda:
    `url_de_instancia("libraclub")` a secas apuntaría a la del dominio, que no
    tiene esa tabla. `requerida=True` para que una instancia sin la variable
    falle nombrándola, y no conectándose a la cadena vacía.

    Se pregunta antes de configurar (`esta_configurado()`) para no pisarle la
    configuración a una app viva.
    """
    from libracore.db import core as libracore_core
    from libracore.db.url_de_instancia import url_de_instancia

    if not libracore_core.esta_configurado():
        libracore_core.configure(url_de_instancia("libraclub", core=True, requerida=True))


def get_modulos() -> dict[str, bool]:
    """`{modulo: habilitado}` de esta instancia. Ver `_asegurar_core_configurado`."""
    _asegurar_core_configurado()
    from libracore.db.modulos import get_modulos as _get_modulos

    return _get_modulos()


def set_addon(nombre: str, habilitado: bool) -> None:
    """Prende/apaga un add-on suelto en esta instancia.

    Efecto inmediato: `app.addons.require_addon` relee `get_modulos()` en cada
    request. No valida que `nombre` sea un add-on: eso lo hace quien llama,
    contra `plans.ADDONS`.
    """
    _asegurar_core_configurado()
    from libracore.db.modulos import set_addon as _set_addon

    _set_addon(nombre, habilitado)
