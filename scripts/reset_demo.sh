#!/usr/bin/env bash
# Reset diario de la demo publica de LibraClub.
#
# Deja la base de cero, corre las migraciones y siembra. **El estado limpio es
# codigo, no un backup guardado a mano**: eso es lo que hace que sea
# reproducible, y que agregar un dato de ejemplo sea un commit y no una
# operacion manual sobre el servidor.
#
# Corre por cron a las 05:05, despues de los resets de las otras seis demos
# (04:30 a 04:55) para no cargar el I/O del VPS en el mismo minuto.
#
# 🔴 **Solo toca la instancia demo.** El contenedor esta escrito aca, no viene
# por argumento: un reset apuntado al contenedor equivocado le borra la base a
# un cliente y no hay confirmacion que valga a las cinco de la manana. Hoy
# LibraClub no tiene instancias de cliente; el dia que tenga una, este script ya
# esta escrito como si la hubiera.
#
# Copiado del reset de Ventalibra, que acumula las defensas de tres incidentes
# de esta familia. La diferencia propia esta marcada con [LIBRACLUB].
set -euo pipefail

CONTENEDOR="libraclub-demo"
CHECKOUT="/root/libraclub"
URL_PUBLICA="https://demo.libraclub.com.ar"

# La rama de la que sale el seed. `origin/develop` salvo que se la pise, que es
# lo que permite **probar este script antes de mergear**: sin eso, la unica forma
# de estrenar un cambio del reset es mergearlo y esperar al cron.
RAMA_DEL_SEED="${RAMA_DEL_SEED:-origin/develop}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# --- Las guardas ----------------------------------------------------------
# Si el nombre no es el de una demo, no se sigue. Es barato, y es lo unico que
# separa "resetear la demo" de "borrarle la base a un cliente".
case "$CONTENEDOR" in
  *-demo|*-publica) ;;
  *) log "ABORTA: '$CONTENEDOR' no parece una instancia demo."; exit 2 ;;
esac

# 🔴 La guarda del nombre no alcanza, y esto no es teorico: hasta el 2026-08-07
# el contenedor llamado `restolibra-demo` era el que servia
# sistema.restolibra.com.ar. El nombre decia demo y no lo era. Por eso se
# verifica una propiedad real de la instancia --DEMO_MODE, lo unico que
# enciende el auto-login publico-- y no como se llama.
if ! docker exec "$CONTENEDOR" printenv DEMO_MODE 2>/dev/null | grep -qx 1; then
  log "ABORTA: $CONTENEDOR no tiene DEMO_MODE=1. El nombre no alcanza."
  exit 4
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTENEDOR"; then
  log "ABORTA: el contenedor $CONTENEDOR no esta corriendo."
  exit 3
fi

log "=== reset de $CONTENEDOR ==="

# --- 0. El seed, ANTES de tocar la base -----------------------------------
# 🔴 El 2026-08-06 el reset de otro producto borro la base y recien despues
# descubrio que no podia sembrar: el seed vivia en `develop` y el checkout del
# VPS estaba en `main`. Cinco demos quedaron vacias, y el cron lo habria
# repetido todas las noches. El orden correcto es conseguir el seed primero: si
# no esta, no se borra nada.
SEED_LOCAL=/tmp/seed-libraclub-demo.py
git -C "$CHECKOUT" fetch -q origin || { log "ABORTA: no se pudo hacer fetch."; exit 5; }
git -C "$CHECKOUT" show "$RAMA_DEL_SEED":scripts/seed_demo.py > "$SEED_LOCAL" \
  || { log "ABORTA: no esta scripts/seed_demo.py en $RAMA_DEL_SEED."; exit 6; }
[ -s "$SEED_LOCAL" ] || { log "ABORTA: el seed salio vacio."; exit 7; }
log "seed listo desde $RAMA_DEL_SEED ($(wc -l < "$SEED_LOCAL") lineas)"

# --- 1. El sidecar --------------------------------------------------------
# [LIBRACLUB] Este producto es PostgreSQL siempre, asi que no hay motor que
# detectar -- pero igual se verifica, en vez de suponerlo: si un dia la URL no
# fuera de PostgreSQL, borrar "el schema public" no aplicaria y el reset diria
# "listo" sin haber reseteado nada.
URL_BASE=$(docker exec "$CONTENEDOR" printenv DATABASE_URL 2>/dev/null || true)
if [ -z "$URL_BASE" ]; then
  log "ABORTA: no pude leer DATABASE_URL del contenedor."
  exit 8
fi
case "$URL_BASE" in
  postgres://*|postgresql://*|postgresql+*://*) ;;
  *) log "ABORTA: DATABASE_URL no es PostgreSQL. Este reset no aplica."; exit 8 ;;
esac

# El sidecar: su nombre es el host de la URL, que en esta red es la clave del
# servicio y tambien el `container_name`.
SIDECAR=${URL_BASE#*@}
SIDECAR=${SIDECAR%%:*}
SIDECAR=${SIDECAR%%/*}
if ! docker ps --format '{{.Names}}' | grep -qx "$SIDECAR"; then
  log "ABORTA: el sidecar '$SIDECAR' no esta corriendo."
  exit 9
fi
log "motor: PostgreSQL (sidecar $SIDECAR)"

# 🔴 [LIBRACLUB] **Son DOS bases, no una.** El dominio vive en `libraclub` y
# LibraCore en `libraclub_core`, separadas a proposito porque
# `init_core_schema()` crea `usuarios` y `auth_log`, que este producto ya tiene
# con la forma de `libraauth`.
#
# Resetear solo la del dominio deja **33 tablas de LibraCore con los datos de
# ayer**: los turnos de caja, sus movimientos y el espejo de `usuarios`. Y ese
# espejo es lo peor de los tres: `turnos_caja.usuario_id` tiene una FK a los
# usuarios de LibraCore, asi que quedarian turnos apuntando a usuarios de una
# base del dominio que ya no existe. Nada de eso falla al arrancar.
URL_CORE=$(docker exec "$CONTENEDOR" printenv LIBRACLUB_LIBRACORE_DATABASE_URL 2>/dev/null || true)
if [ -z "$URL_CORE" ]; then
  log "ABORTA: no pude leer LIBRACLUB_LIBRACORE_DATABASE_URL del contenedor."
  log "        Sin ella este script reseteria media instancia y diria que anduvo."
  exit 8
fi
BASE_CORE=${URL_CORE##*/}
BASE_CORE=${BASE_CORE%%\?*}
log "bases a resetear: la del dominio y '$BASE_CORE' (LibraCore)"

# Cuantas filas hay en tres tablas del dominio **y dos de LibraCore**. Es la
# unica forma de que este script pueda DECIR que reseteo: se mide antes y
# despues, y si despues no dio cero, se aborta sin sembrar. Un reset que no
# resetea y siembra igual deja la demo con los datos de ayer mas los de hoy, y
# no avisa nunca.
filas_del_dominio() {
  local dominio core
  dominio=$(docker exec "$SIDECAR" sh -c '
    psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
      SELECT COALESCE((SELECT COUNT(*) FROM sucursales), 0)
           + COALESCE((SELECT COUNT(*) FROM canchas), 0)
           + COALESCE((SELECT COUNT(*) FROM reservas), 0)"
  ' 2>/dev/null) || { echo "?"; return; }
  # Si la base de core todavia no existe, cuenta como cero: es el estado
  # esperado justo despues del reset, antes de que la app la recree.
  core=$(docker exec "$SIDECAR" sh -c "
    psql -tA -U \"\$POSTGRES_USER\" -d $BASE_CORE -c \"
      SELECT COALESCE((SELECT COUNT(*) FROM turnos_caja), 0)
           + COALESCE((SELECT COUNT(*) FROM caja_movimientos), 0)\"
  " 2>/dev/null || echo 0)
  [ -z "$dominio" ] && { echo "?"; return; }
  echo $(( ${dominio:-0} + ${core:-0} ))
}

ANTES=$(filas_del_dominio)
log "filas del dominio + LibraCore antes del reset: $ANTES"

# --- 1b. Los codigos de acceso, que SI sobreviven al reset -----------------
# 🔴 En este producto `usuarios` --y con el las tablas satelite de libraauth,
# entre ellas `demo_codigos`-- vive en la MISMA base que el dominio. O sea que
# el `DROP SCHEMA` de abajo **se lleva los codigos emitidos**.
#
# En Gestiolibra/MedLibra/VentaLibra eso no pasa porque ahi esa tabla esta en
# otra base, que el reset no toca. Sin este paso, este producto se comportaria
# distinto del resto de la familia: un codigo emitido a un cliente potencial
# --que el sistema declara valido por 7 dias y 10 usos-- dejaria de servir en
# el reset de esa misma noche, sin que nadie lo haya revocado.
CODIGOS_DUMP=/tmp/demo-codigos-$CONTENEDOR.sql
rm -f "$CODIGOS_DUMP"
if docker exec "$SIDECAR" sh -c '
     psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"        -c "SELECT 1 FROM information_schema.tables WHERE table_name = '"'"'demo_codigos'"'"'"
   ' 2>/dev/null | grep -q 1; then
  docker exec "$SIDECAR" sh -c '
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --data-only --table=demo_codigos
  ' > "$CODIGOS_DUMP" 2>/dev/null || true
  VIVOS=$(docker exec "$SIDECAR" sh -c '
    psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT COUNT(*) FROM demo_codigos"
  ' 2>/dev/null || echo 0)
  log "codigos de acceso a preservar: ${VIVOS:-0}"
else
  log "todavia no existe demo_codigos: nada que preservar"
fi

# --- 2. Base de cero ------------------------------------------------------
# Se para la app ANTES de tocar el schema. Con el contenedor arriba, sus
# conexiones abiertas dejan el `DROP SCHEMA` esperando un lock: no falla, se
# cuelga -- ya paso, veinte minutos en silencio.
docker stop "$CONTENEDOR" >/dev/null
log "app parada para soltar las conexiones"

# `psql` se corre DENTRO del sidecar y con las variables de su propio entorno:
# asi la contrasena no pasa por la linea de comandos del host, donde quedaria
# en el `ps` y en el log del cron.
docker exec "$SIDECAR" sh -c '
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "DROP SCHEMA IF EXISTS public CASCADE" \
    -c "CREATE SCHEMA public" \
    -c "GRANT ALL ON SCHEMA public TO \"$POSTGRES_USER\""
' >/dev/null || { log "ABORTA: no se pudo recrear el schema del dominio."; docker start "$CONTENEDOR" >/dev/null; exit 10; }
log "schema del dominio recreado, vacio"

# [LIBRACLUB] Y la de LibraCore. La app la recrea sola al arrancar
# (`init_core_schema`), asi que alcanza con dejarla vacia.
docker exec "$SIDECAR" sh -c "
  psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d $BASE_CORE \
    -c \"DROP SCHEMA IF EXISTS public CASCADE\" \
    -c \"CREATE SCHEMA public\" \
    -c \"GRANT ALL ON SCHEMA public TO \\\"\$POSTGRES_USER\\\"\"
" >/dev/null || { log "ABORTA: no se pudo recrear el schema de $BASE_CORE."; docker start "$CONTENEDOR" >/dev/null; exit 10; }
log "schema de $BASE_CORE recreado, vacio"

docker start "$CONTENEDOR" >/dev/null

for _ in $(seq 1 40); do
  estado=$(docker inspect -f '{{.State.Health.Status}}' "$CONTENEDOR" 2>/dev/null || echo starting)
  [ "$estado" = "healthy" ] && break
  sleep 3
done
estado=$(docker inspect -f '{{.State.Health.Status}}' "$CONTENEDOR" 2>/dev/null || echo desconocido)
log "contenedor: $estado"
if [ "$estado" != "healthy" ]; then
  log "ABORTA: no levanto sano; no se siembra sobre una instancia rota."
  exit 4
fi

# --- 3. Las migraciones ---------------------------------------------------
# 🔴 [LIBRACLUB] **El arranque NO las corre**, a diferencia de otros productos
# de la familia que reconstruyen el esquema solos. Y el healthcheck es
# `/salud`, que consulta la base pero no mira si hay tablas: el contenedor se
# reporta **healthy con la base vacia**. Sin este paso, el seed de abajo
# fallaria contra un esquema inexistente y la demo quedaria en blanco todas las
# noches, con el chequeo de salud en verde.
docker exec "$CONTENEDOR" alembic upgrade head >/dev/null 2>&1 \
  || { log "ABORTA: fallaron las migraciones."; exit 12; }
TABLAS=$(docker exec "$SIDECAR" sh -c '
  psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '"'"'public'"'"'"' 2>/dev/null || echo 0)
log "migraciones aplicadas: $TABLAS tablas"
if [ "${TABLAS:-0}" -lt 10 ]; then
  log "ABORTA: quedaron $TABLAS tablas, esperaba al menos 10."
  exit 12
fi

# El usuario del visitante lo siembra `ensure_demo_user` AL ARRANCAR, y este
# arranque fue contra la base vacia. Sin este reinicio, `POST /auth/demo`
# contesta 503 "demo user not provisioned" hasta que alguien lo note.
docker restart "$CONTENEDOR" >/dev/null
for _ in $(seq 1 40); do
  estado=$(docker inspect -f '{{.State.Health.Status}}' "$CONTENEDOR" 2>/dev/null || echo starting)
  [ "$estado" = "healthy" ] && break
  sleep 3
done
log "reiniciado para sembrar admin y visitante: $estado"

# --- 4. Que de verdad haya reseteado --------------------------------------
# La post-condicion. Sin esto el script dice "listo" igual cuando no borro nada,
# que es exactamente como se rompe un reset al cambiar de motor: el paso de
# borrado deja de aplicar, nadie lo nota, y el seed se apila todas las noches.
DESPUES=$(filas_del_dominio)
log "filas del dominio despues del reset: $DESPUES"
if [ "$DESPUES" = "?" ]; then
  log "ABORTA: no pude contar las filas -- puede que una tabla haya cambiado"
  log "        de nombre. Sin poder medir, no se siembra."
  exit 11
fi
if [ "$DESPUES" != "0" ]; then
  log "ABORTA: la base no quedo vacia (antes $ANTES, despues $DESPUES)."
  log "        No se siembra encima: quedaria la demo de ayer mas la de hoy."
  exit 11
fi
if [ "$ANTES" = "0" ]; then
  log "OJO: antes tambien habia 0 filas -- el chequeo no probo nada esta vez."
fi


# --- 4b. Devolver los codigos de acceso -----------------------------------
# Ver el 🔴 del paso 1b. La tabla ya existe: la crea `libraauth` al arrancar.
if [ -s "$CODIGOS_DUMP" ]; then
  if docker exec -i "$SIDECAR" sh -c '
       psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"
     ' < "$CODIGOS_DUMP" >/dev/null 2>&1; then
    DEVUELTOS=$(docker exec "$SIDECAR" sh -c '
      psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT COUNT(*) FROM demo_codigos"
    ' 2>/dev/null || echo 0)
    log "codigos de acceso devueltos: ${DEVUELTOS:-0}"
  else
    # No aborta: la demo ya quedo usable y sin codigos se puede emitir otro.
    # Pero se dice fuerte, porque el sintoma seria "a nadie le anda el codigo".
    log "OJO: no se pudieron devolver los codigos de acceso. Hay que emitir uno nuevo."
  fi
  rm -f "$CODIGOS_DUMP"
fi

# --- 5. Sembrar -----------------------------------------------------------
# Por la API y desde adentro del contenedor: la contrasena sale de su propio
# entorno y nunca pasa por la linea de comandos del host, donde quedaria en el
# `ps` y en el log del cron.
docker cp "$SEED_LOCAL" "$CONTENEDOR:/tmp/seed.py"
docker exec -i "$CONTENEDOR" sh -c "
  python3 /tmp/seed.py \
    --url $URL_PUBLICA \
    --usuario \"\${LIBRACLUB_ADMIN_USERNAME:-admin}\" \
    --password \"\$LIBRACLUB_ADMIN_PASSWORD\"
"
# 🔴 `--user root` y `|| true`. `docker cp` deja el archivo como root, y el
# contenedor corre sin privilegios: sin el `--user root` este `rm` falla con
# "Operation not permitted" y, con `set -e`, **el script sale 1 despues de
# haber sembrado bien**. El cron registraria un rojo todas las noches por un
# archivo temporal, y --peor-- el control final de abajo no llegaria a correr.
docker exec --user root "$CONTENEDOR" rm -f /tmp/seed.py || true

# --- 6. Y que la demo siga siendo una demo --------------------------------
# El ultimo control: que el visitante pueda entrar. Todo lo de arriba puede
# haber salido bien y aun asi haber dejado la instancia sin el usuario de la
# demo, que es el modo de falla mas silencioso de este script.
if docker exec "$CONTENEDOR" python3 -c "
import json, urllib.request
r = urllib.request.urlopen('http://localhost:8000/auth/demo', timeout=5)
d = json.load(r)
raise SystemExit(0 if d.get('enabled') and d.get('username') else 1)
" 2>/dev/null; then
  log "la demo se sigue anunciando como tal"
else
  log "ABORTA: GET /auth/demo no devolvio una demo valida."
  exit 13
fi

log "=== listo ==="
