#!/usr/bin/env python3
"""Configura la conexión a Nginx Proxy Manager.

    python3 scripts/npm_setup.py

Guarda la config en `scripts/.npm_config.json`, que no entra al repo.
Envoltorio sobre `libracore.npm_setup`, compartido con el resto de la familia.
"""
from pathlib import Path

from libracore.npm_api import configure as _configure_npm_api
from libracore.npm_setup import main as _main

_configure_npm_api(config_file=Path(__file__).parent / ".npm_config.json")


def main():
    _main(product_name="LIBRACLUB")


if __name__ == "__main__":
    main()
