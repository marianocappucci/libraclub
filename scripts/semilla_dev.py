"""Datos de ejemplo para una instancia `dev`. Una pantalla vacia no se revisa.

Se corre una vez, despues de `alembic upgrade head`:

    docker compose exec -T libraclub-dev python scripts/semilla_dev.py

**Idempotente**: si ya hay sucursales no hace nada, para que una segunda corrida
—o el proximo que quiera "asegurarse"— no duplique el catalogo entero.

🔴 **Va en el repo y no suelto en el servidor.** La primera version de este
archivo se escribio directo en el checkout del VPS, que es justo lo que la regla
del ecosistema prohibe: la fuente de verdad es el repo, y un archivo sin
trackear adentro del arbol le complica el `git pull` del proximo deploy.

⚠️ Es para `dev` y para nada mas. Una instancia de cliente arranca vacia: datos
de ejemplo ahi son basura que alguien va a tener que borrar a mano y que, peor,
se parece lo suficiente a datos reales como para que nadie se anime a tocarla.
"""
from datetime import time
from decimal import Decimal

from app import db
from app.config import Config
from app.models.enums import AlcanceDia, Deporte
from app.models.maestros import Cancha, Cliente, Sucursal
from app.models.tarifas import Tarifa

db.inicializar(Config.desde_entorno())
S = db.fabrica_de_sesiones()
with S() as s:
    if s.query(Sucursal).count():
        print("ya hay datos, no se siembra nada")
        raise SystemExit(0)

    centro = Sucursal(nombre="Complejo Centro", localidad="Suipacha",
                      direccion="San Martin 100", telefono="2324-401122",
                      punto_venta_arca=1)
    norte = Sucursal(nombre="Complejo Norte", localidad="Mercedes",
                     telefono="2324-556677", punto_venta_arca=2)
    s.add_all([centro, norte])
    s.commit()

    canchas = [
        Cancha(sucursal_id=centro.id, nombre=f"Cancha {i}", deporte=Deporte.PADEL,
               duracion_turno_min=90, techada=(i != 3), orden=i)
        for i in (1, 2, 3)
    ]
    canchas.append(Cancha(sucursal_id=centro.id, nombre="Futbol 5",
                          deporte=Deporte.FUTBOL, duracion_turno_min=60, orden=9))
    canchas.append(Cancha(sucursal_id=norte.id, nombre="Cancha A",
                          deporte=Deporte.PADEL, duracion_turno_min=90, orden=1))
    s.add_all(canchas)
    s.commit()

    s.add_all([
        Cliente(nombre="Juan Perez", telefono="2324-401122"),
        Cliente(nombre="Grupo de los martes", telefono="2324-556677"),
        Cliente(nombre="Ana Gomez", telefono="11-5566-7788"),
    ])
    s.commit()

    s.add_all([
        Tarifa(sucursal_id=centro.id, nombre="Diurna", alcance_dia=AlcanceDia.TODOS,
               hora_desde=time(8, 0), hora_hasta=time(18, 0),
               precio=Decimal("9000.00"), sena_porcentaje=50),
        Tarifa(sucursal_id=centro.id, nombre="Nocturna", alcance_dia=AlcanceDia.TODOS,
               hora_desde=time(18, 0), hora_hasta=time(23, 59),
               precio=Decimal("14000.00"), sena_porcentaje=50, prioridad=1),
        Tarifa(sucursal_id=centro.id, nombre="Finde nocturna",
               alcance_dia=AlcanceDia.DIA_SEMANA, dia_semana=5,
               hora_desde=time(18, 0), hora_hasta=time(23, 59),
               precio=Decimal("18000.00"), sena_porcentaje=50, prioridad=2),
        Tarifa(sucursal_id=norte.id, nombre="Unica", alcance_dia=AlcanceDia.TODOS,
               hora_desde=time(8, 0), hora_hasta=time(23, 59),
               precio=Decimal("11000.00")),
    ])
    s.commit()
    print("sembrado: 2 sucursales, 5 canchas, 3 clientes, 4 tarifas")
