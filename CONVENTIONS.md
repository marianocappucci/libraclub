# Convenciones

## Idioma

**El dominio se escribe en castellano**: tablas, columnas, modelos, servicios,
rutas y mensajes. `cancha`, `reserva`, `sucursal`, `tarifa` — no `court`,
`booking`, `branch`, `rate`.

Es el idioma del operador que va a leer los mensajes de error, y el de los tres
productos más nuevos de la familia. Lo que viene de un motor conserva el suyo:
`libragenda` habla inglés y no se traduce en el borde.

## Fecha y hora

- La base guarda `timestamptz`. Siempre.
- La API habla **ISO 8601**, en las dos direcciones. Los parámetros de fecha en
  URLs también.
- `dd-mm-aaaa` (`dd-mm-aaaa HH:MM` con hora, reloj de 24 h) es **presentación
  únicamente**, y sale de `app/tiempo.py` en el backend y de un helper único en
  el frontend. Nunca repetido por vista.
- Zona: `America/Argentina/Buenos_Aires`, UTC-3 fijo, sin horario de verano.
- Un `<input type="date">` no se toca: habla ISO por definición.

## Dinero

`Numeric(12, 2)` en la base, `Decimal` en Python. **Nunca `float`.** El símbolo
es `$` argentino; no hay `€` en ningún lado, ni en templates ni en PDFs ni en
tickets.

## Migraciones

Todo cambio de schema va por Alembic. Ninguna tabla se crea con
`create_all()` salvo las de `libraauth`, que las versiona el motor y no
nosotros.

Una migración que agrega una columna `NOT NULL` a una tabla con datos lleva
`server_default` o va en dos pasos. Sin excepciones.

## Errores

Los servicios levantan excepciones propias del dominio. Los routers las
traducen a códigos HTTP. Un `IntegrityError` de PostgreSQL **se traduce por el
nombre de la constraint**, nunca haciendo `grep` sobre el texto del error: el
texto cambia entre versiones y entre locales.

## Tests

Contra PostgreSQL real, con la **misma imagen que producción** (`postgres:16`,
no `-alpine`: el collation viene de la imagen y alpine ordena por bytes).

Un test que crea el schema y no inserta filas no prueba las lecturas. Un test
que asserta sobre un cero necesita un control positivo que demuestre que el
camino se ejercita.

## Comentarios

Se comenta **por qué**, no qué. Un comentario que explica una trampa medida vale
más que diez que describen la línea de abajo. Si algo se hace de una forma rara
porque la obvia falló, eso se escribe.

## Dónde se arregla (regla de la familia, 2026-10-03)

**El arreglo de fondo vive siempre en el motor** (`libracore`; `libracommerce` y `libra-ui` para
lo suyo), **nunca en este repo.** Lo que otro producto comparte o podría compartir —el protocolo
con ARCA, las reglas fiscales y sus validaciones, las guardas contra duplicados, la numeración, la
cuenta corriente, los componentes de pantalla compartidos— se escribe y se arregla en el motor.
Este repo sólo aporta **costuras** (los hooks que el motor ya expone) y lo suyo: pantallas,
textos y su modelo de datos propio. Si falta la costura, se agrega al motor; si el arreglo hace
falta antes, igual se hace en el motor (PR y tag) y acá se sube el pin: nada «provisorio» en este
repo. Un hueco que se encuentra acá se busca en los demás productos antes de darlo por acotado.
Detalle y motivo: `reglas/producto.md` del wiki.
