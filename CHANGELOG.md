# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/),
versionado [SemVer](https://semver.org/lang/es/).

## [No publicado]

### Agregado

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
