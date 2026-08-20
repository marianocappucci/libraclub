"""Los planes comerciales de LibraClub y qué módulos habilita cada uno.

Fuente de verdad compartida con `libracore.provisioning.nuevo_cliente`, que
asigna el plan al dar de alta un cliente. Mismo patrón que el `plans.py` de los
otros productos de la familia.

⚠️ **Los precios son una decisión comercial, no técnica.** Quedan alineados con
los del resto de la familia como punto de partida. Cuando el negocio defina qué
se cobra para complejos deportivos, se cambia este archivo y nada más.

## Hoy los tres planes habilitan lo mismo, y es a propósito

**No hay ningún módulo gateable.** Todo lo que LibraClub sabe hacer al
2026-08-20 —sucursales, canchas, tarifas, clientes, la agenda, las reservas, los
bloqueos y las canchas fijas— es **el núcleo**: un LibraClub sin agenda no es un
plan más barato, es otra cosa. Es el mismo criterio que tomaron LibraDesk y
LibraCargo.

🔴 **Y por eso los conjuntos van vacíos en vez de anticipar el roadmap.**
Declarar acá `portal`, `buffet` o `reportes` —que son los tres candidatos
naturales, y están en el `ROADMAP.md`— le daría al backoffice tres casillas para
habilitar funciones que **no existen**: un cliente en premium vería prometido
algo que su instancia no sirve. Se agregan cuando el módulo esté construido, no
cuando esté planeado.

Los tres candidatos, para cuando toque:

| Módulo | Qué gatearía | Cuándo |
|---|---|---|
| `portal` | El portal público de reservas con seña por Mercado Pago | F2 |
| `buffet` | Catálogo, stock y POS sobre LibraCommerce | F4 |
| `reportes` | Ocupación por franja y rentabilidad por cancha | F6 |
"""

PLANES = ["basico", "estandar", "premium"]

PLAN_LABELS = {
    "basico": "Básico",
    "estandar": "Estándar",
    "premium": "Premium",
}

#: Precio mensual de referencia (informativo, para mostrar en el backoffice).
#: Alineado con el resto de la familia.
PLAN_PRECIOS = {
    "basico": 15000,
    "estandar": 25000,
    "premium": 40000,
}

# Básico: el núcleo del complejo, completo. No son módulos gateables.
_BASICO: set[str] = set()

# Estándar y Premium: hoy, lo mismo. Ver el encabezado — lo que los va a
# distinguir todavía no está construido, y anticiparlo acá sería prometerlo.
_ESTANDAR = set(_BASICO)
_PREMIUM = set(_ESTANDAR)

PLAN_MODULOS = {
    "basico": sorted(_BASICO),
    "estandar": sorted(_ESTANDAR),
    "premium": sorted(_PREMIUM),
}

#: Todos los módulos gateables, para que el backoffice pueda listarlos.
MODULOS = sorted(_PREMIUM)

MODULO_LABELS: dict[str, str] = {}
