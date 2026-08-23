# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/),
versionado [SemVer](https://semver.org/lang/es/).

## [No publicado]

### Agregado

- **Cobro con QR de MercadoPago y factura automática** (ADR-014): desde el
  detalle de un turno confirmado o jugado, «Cobrar con QR» pone el total —la
  cancha **más** el consumo de buffet— en el QR impreso del mostrador y espera a
  que MercadoPago avise. Al acreditarse, el cobro entra a la caja del turno y
  —si la instancia tiene la automática prendida— sale la factura sola, con las
  dos cosas detalladas. El QR es el cartel fijo de la caja y no cambia nunca;
  lo que cambia es cuánto cobra.

  Es el **primer cobro real de MercadoPago del producto**: hasta acá el webhook
  existía y verificaba firma, pero nada iniciaba un pago. Cancelar el cobro baja
  el monto del cartel, para que el próximo que escanee no pague el turno
  anterior. Sección nueva **Mercado Pago** en Configuración, que además reúne el
  Webhook Secret del portal. Migración `0008`. 20 tests de backend y 9 de
  frontend.

- **Torneos** (F6): eliminación directa, todos contra todos y zonas con
  playoff, para pádel, tenis y fútbol. Inscripción con integrantes y cabezas de
  serie, sorteo reproducible por semilla, fixture con byes, programación de
  cancha y horario, carga de resultados con avance automático del cuadro, y
  tabla de posiciones por zona.
- Un partido de torneo con cancha y horario **ocupa el turno en la agenda**: se
  crea un bloqueo real, así que nadie puede alquilar esa cancha a esa hora
  (ADR-010). Cancelar el torneo libera todos los bloqueos.

- Esqueleto del producto: configuración, sesión, salud, SPA y backup.
- Modelo de dominio de F1: canchas, tarifas, clientes, reservas, bloqueos y
  series recurrentes.
- Garantía de no-superposición a nivel de base con `EXCLUDE USING gist`.
- Alta de reserva desde la grilla de la agenda, con cliente nuevo en el mismo
  diálogo, y detalle de la reserva ocupada con sus transiciones.
- El alta de clientes la puede hacer un encargado (`staff`), no sólo un admin.
- ABM de canchas y de tarifas desde la UI: alta, edición y baja, con las
  acciones de escritura visibles sólo para admin.
- ABM de sucursales y de clientes desde la UI, con sus pantallas propias.
  Clientes trae buscador y filtro de dados de baja, y lo puede escribir un
  encargado.
- El selector de sucursal del encabezado se actualiza solo al crear, editar o
  borrar una sucursal, y se corre a otra si la elegida queda de baja.

### Corregido

- **«Quitar bloqueo» devolvía 500 desde la primera migración.** La máquina de
  estados declara `bloqueo -> cancelada` y el botón de la agenda manda esa
  transición, pero el CHECK `ck_reservas_cliente_segun_estado` exigía cliente a
  toda fila que no fuera `bloqueo` — y un bloqueo cancelado deja de ser
  `bloqueo` sin ganar cliente. La regla dice ahora lo que quiso decir siempre:
  el cliente es obligatorio mientras la fila esté viva (migración `0007`).
