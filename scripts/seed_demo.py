#!/usr/bin/env python3
"""Datos de ejemplo de la instancia demo pública.

Va **por la API** y no por SQL —a diferencia de `semilla_dev.py`, que escribe
con SQLAlchemy— porque acá lo que se siembra son **reservas**: el precio
congelado, el constraint de no-superposición y la máquina de estados salen del
mismo camino que usa el producto, y no de un `INSERT` que puede dejar
invariantes rotas que después la pantalla reporta como alarma.

**Vive en el repo y no suelto en el servidor.** El estado limpio de la demo es
código: agregar un dato de ejemplo es un commit, no una operación manual sobre
el VPS a las cinco de la mañana. `scripts/reset_demo.sh` lo saca de
`origin/develop` cada noche.

🔴 **Las fechas de las reservas son relativas a hoy.** La agenda es la primera
pantalla que ve el visitante y muestra la semana en curso: con fechas fijas, a
la semana siguiente la demo abre en una grilla **vacía**, que es exactamente la
impresión que no queremos dar. Todo se ancla al lunes de esta semana.

Se corta solo si ya hay sucursales cargadas: es un seed, no un importador.

    python3 seed_demo.py --url https://demo.libraclub.com.ar \\
        --usuario admin --password "$LIBRACLUB_ADMIN_PASSWORD"
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", required=True, help="Base de la instancia, con https://")
parser.add_argument("--usuario", default="admin")
parser.add_argument("--password", required=True)
args = parser.parse_args()

BASE = args.url.rstrip("/")
OFFSET = "-03:00"  # Argentina: UTC-3 fijo, sin horario de verano

cookies = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))


def pedir(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo, default=str).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=30) as r:
            texto = r.read().decode()
            return r.status, (json.loads(texto) if texto else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def crear(ruta, cuerpo, etiqueta, obligatorio=True):
    codigo, salida = pedir("POST", ruta, cuerpo)
    if codigo != 201:
        print(f"  x {etiqueta}: {codigo} {salida}")
        if obligatorio:
            sys.exit(1)
        return None
    print(f"  ok {etiqueta} -> id {salida['id']}")
    return salida["id"]


# El lunes de esta semana: todo lo que se cree cae en la vista que abre la
# agenda. Ver el 🔴 del encabezado.
HOY = date.today()
LUNES = HOY - timedelta(days=HOY.weekday())


def cuando(dia_offset: int, hora: int, minuto: int = 0) -> str:
    """ISO 8601 **con offset**. Un datetime sin zona se toma como UTC, y la
    reserva de las 20:00 apareceria a las 17:00."""
    d = LUNES + timedelta(days=dia_offset)
    return f"{d.isoformat()}T{hora:02d}:{minuto:02d}:00{OFFSET}"


# ---- sesión ---------------------------------------------------------------
# 🔴 Por `https://` y no por el puerto local: la cookie de sesión está marcada
# `Secure`, así que sobre http el login devuelve 200 y **todo lo demás 401**.
codigo, _ = pedir("POST", "/auth/login", {"username": args.usuario, "password": args.password})
if codigo != 200:
    print(f"login: {codigo}")
    sys.exit(1)
print("sesion abierta")

codigo, sucursales = pedir("GET", "/api/sucursales")
if codigo != 200:
    print(f"no se puede leer sucursales: {codigo} -- la cookie no viajo?")
    sys.exit(1)
if sucursales:
    print(f"ya hay {len(sucursales)} sucursales cargadas: no toco nada")
    sys.exit(0)

# ---- sucursales -----------------------------------------------------------
print("sucursales")
centro = crear("/api/sucursales", {
    "nombre": "Complejo Centro", "localidad": "Suipacha",
    "direccion": "San Martin 100", "telefono": "2324-401122",
    "punto_venta_arca": 1}, "Complejo Centro")
# 🔑 Punto de venta DISTINTO: dos sucursales con el mismo se pisan la
# numeracion de comprobantes, y un indice unico parcial lo rechaza.
norte = crear("/api/sucursales", {
    "nombre": "Complejo Norte", "localidad": "Mercedes",
    "telefono": "2324-556677", "punto_venta_arca": 2}, "Complejo Norte")

# ---- canchas --------------------------------------------------------------
# Deportes y duraciones distintas a proposito: la grilla de la agenda se arma
# con la duracion de CADA cancha, y con todas iguales eso no se ve.
print("canchas")
p1 = crear("/api/canchas", {"sucursal_id": centro, "nombre": "Padel 1",
                            "deporte": "padel", "duracion_turno_min": 90,
                            "techada": True, "superficie": "Cesped sintetico",
                            "orden": 1}, "Padel 1 (techada, 90 min)")
p2 = crear("/api/canchas", {"sucursal_id": centro, "nombre": "Padel 2",
                            "deporte": "padel", "duracion_turno_min": 90,
                            "superficie": "Cesped sintetico", "orden": 2}, "Padel 2")
f5 = crear("/api/canchas", {"sucursal_id": centro, "nombre": "Futbol 5",
                            "deporte": "futbol", "duracion_turno_min": 60,
                            "superficie": "Cesped sintetico", "orden": 3},
           "Futbol 5 (60 min)")
crear("/api/canchas", {"sucursal_id": norte, "nombre": "Padel Norte 1",
                       "deporte": "padel", "duracion_turno_min": 90, "orden": 1},
      "Padel Norte 1")
crear("/api/canchas", {"sucursal_id": norte, "nombre": "Tenis", "deporte": "tenis",
                       "duracion_turno_min": 60, "superficie": "Polvo de ladrillo",
                       "orden": 2}, "Tenis Norte")

# ---- tarifas --------------------------------------------------------------
# Cuatro tarifas que muestran la resolucion por especificidad: la de "todos los
# dias" es el piso, la nocturna le gana por franja, y la del sabado por dia.
print("tarifas")
crear("/api/tarifas", {"sucursal_id": centro, "nombre": "Diurna",
                       "alcance_dia": "todos", "hora_desde": "08:00:00",
                       "hora_hasta": "18:00:00", "precio": "9000.00",
                       "sena_porcentaje": 50}, "Diurna 08-18 $9.000")
crear("/api/tarifas", {"sucursal_id": centro, "nombre": "Nocturna",
                       "alcance_dia": "todos", "hora_desde": "18:00:00",
                       "hora_hasta": "23:59:00", "precio": "14000.00",
                       "sena_porcentaje": 50}, "Nocturna 18-24 $14.000")
crear("/api/tarifas", {"sucursal_id": centro, "nombre": "Sabado a la noche",
                       "alcance_dia": "dia_semana", "dia_semana": 5,
                       "hora_desde": "18:00:00", "hora_hasta": "23:59:00",
                       "precio": "18000.00", "sena_porcentaje": 50},
      "Sabado noche $18.000")
crear("/api/tarifas", {"sucursal_id": norte, "nombre": "Norte, todo el dia",
                       "alcance_dia": "todos", "hora_desde": "08:00:00",
                       "hora_hasta": "23:59:00", "precio": "11000.00"},
      "Norte $11.000")

# ---- clientes -------------------------------------------------------------
print("clientes")
# El documento va como TEXTO: un DNI que empieza con cero conserva el cero.
c1 = crear("/api/clientes", {"nombre": "Martin Alvarez", "telefono": "2324-501122",
                             "documento": "04123456"}, "Martin Alvarez")
c2 = crear("/api/clientes", {"nombre": "Lucia Fernandez", "telefono": "2324-502233",
                             "email": "lucia@ejemplo.com"}, "Lucia Fernandez")
c3 = crear("/api/clientes", {"nombre": "Grupo del jueves",
                             "observaciones": "Cancha fija, cuatro jugadores"},
           "Grupo del jueves")

# ---- reservas -------------------------------------------------------------
# Un juego que muestre lo que el producto sabe hacer, no solo que "hay filas":
# franjas distintas (para que se vea el tarifario resolviendo), varios estados y
# varios origenes.
print("reservas")
plan = [
    (p1, c1, cuando(0, 19, 0), "confirmada", "telefono", None),
    (p1, c2, cuando(0, 20, 30), "confirmada", "whatsapp", None),
    (p2, c3, cuando(1, 18, 0), "confirmada", "mostrador", None),
    (p2, c1, cuando(1, 21, 0), "pendiente_pago", "whatsapp", "Esperando la sena"),
    (f5, c2, cuando(2, 20, 0), "confirmada", "telefono", None),
    (p1, c3, cuando(3, 19, 0), "provisoria", "portal", "Retenida 15 minutos"),
    (p2, c2, cuando(4, 22, 0), "confirmada", "whatsapp", "Viernes a la noche"),
    (p1, c1, cuando(5, 11, 0), "confirmada", "mostrador", "Sabado a la manana"),
    (p2, c3, cuando(5, 21, 0), "confirmada", "telefono", "Sabado a la noche"),
]
creadas = []
for cancha, cliente, comienza, estado, origen, obs in plan:
    cuerpo = {"cancha_id": cancha, "cliente_id": cliente, "comienza_at": comienza,
              "estado": estado, "origen": origen}
    if obs:
        cuerpo["observaciones"] = obs
    r = crear("/api/reservas", cuerpo, f"{comienza[:16]} ({estado})", obligatorio=False)
    if r:
        creadas.append(r)

# Una cancelada, para que el estado exista y se vea que la fila NO se borra.
if creadas:
    codigo, _ = pedir("POST", f"/api/reservas/{creadas[-1]}/estado",
                      {"estado": "cancelada", "motivo": "El cliente aviso que no puede"})
    print(f"  {'ok' if codigo == 200 else 'x'} reserva {creadas[-1]} cancelada con motivo")

# ---- un bloqueo -----------------------------------------------------------
print("bloqueo")
crear("/api/reservas/bloqueos",
      {"cancha_id": p1, "comienza_at": cuando(2, 8, 0), "termina_at": cuando(2, 12, 0),
       "motivo": "Mantenimiento del cesped"},
      "miercoles 08-12 mantenimiento", obligatorio=False)

# ---- una cancha fija ------------------------------------------------------
# Desde la semana que viene, para no chocar con las reservas de arriba.
print("cancha fija")
codigo, salida = pedir("POST", "/api/reservas/series", {
    "cancha_id": p2, "cliente_id": c3, "dia_semana": 3, "hora": "20:00:00",
    "duracion_min": 90, "desde": (LUNES + timedelta(days=7)).isoformat(),
    "observaciones": "Grupo de los jueves, todas las semanas",
})
print(f"  {'ok' if codigo == 201 else 'x'} serie de los jueves 20:00 -> {codigo}")

# ---- lo que quedó ---------------------------------------------------------
print("\nasi quedo la demo:")
for ruta, nombre in (("/api/sucursales", "sucursales"), ("/api/canchas", "canchas"),
                     ("/api/tarifas", "tarifas"), ("/api/clientes", "clientes"),
                     ("/api/reservas", "reservas")):
    _, filas = pedir("GET", ruta)
    print(f"  {nombre}: {len(filas or [])}")

# La contraprueba de que la agenda no abre vacia, que es el unico modo de falla
# que este seed existe para evitar.
_, reservas = pedir("GET", "/api/reservas")
if not reservas:
    print("\nx la demo quedo SIN reservas: la agenda abriria vacia")
    sys.exit(1)
print("\nok la agenda de esta semana tiene con que abrir")
