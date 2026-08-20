"""Cliente para la API REST de Nginx Proxy Manager (NPM).

Config leída desde `scripts/.npm_config.json` (lo genera `npm_setup.py`, y está
excluido del repo: tiene credenciales).

Envoltorio de configuración sobre `libracore.npm_api` — la lógica es compartida
con los otros seis productos.

🔴 **No es opcional aunque parezca un detalle.**
`libracore.provisioning.client_from_config()` hace `import npm_api` a secas y
devuelve `None` si no lo encuentra, **en silencio**: sin este archivo el alta de
un cliente termina sin crear su dominio y sin decir por qué.
"""
from pathlib import Path

from libracore.npm_api import (
    NPMClient,
    NPMError,
    client_from_config,
    configure,
    forward_host_from_config,
    le_email_from_config,
    load_config,
    save_config,
)

CONFIG_FILE = Path(__file__).parent / ".npm_config.json"
configure(config_file=CONFIG_FILE)

__all__ = [
    "NPMClient", "NPMError", "client_from_config", "configure",
    "forward_host_from_config", "le_email_from_config", "load_config",
    "save_config", "CONFIG_FILE",
]
