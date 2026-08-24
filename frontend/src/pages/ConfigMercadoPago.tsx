/** Con qué cuenta de MercadoPago cobra el complejo.
 *
 *  Las credenciales las usan **dos cosas distintas**, y por eso están juntas:
 *
 *  - el **QR del mostrador** (Access Token + User ID + POS ID), que es lo que el
 *    encargado pone a cobrar desde el detalle de un turno;
 *  - el **webhook** (Webhook Secret), que es lo único que confirma una reserva
 *    pagada desde el portal. Sin secreto, el webhook no procesa nada: procesar
 *    sin verificar sería dejar que cualquiera confirme turnos.
 *
 *  🔑 **El QR es el cartel impreso de la caja, no una imagen.** El cartel no
 *  cambia nunca; lo que el sistema cambia es cuánto cobra cuando lo escanean.
 *  Por eso hacen falta los tres datos y no sólo el token: el collector id y el
 *  external_id de la caja van en la URL de la orden.
 */
import { useEffect, useState } from 'react'
import { configMercadoPago, type ConfigMercadoPago as Config } from '@/lib/api'
import { AvisoDeError } from '@/components/listado'
import { Input } from '@/components/ui/input'
import { buttonVariants } from '@/components/ui/button'

export function ConfigMercadoPago() {
  const [cfg, setCfg] = useState<Config | null>(null)
  const [guardando, setGuardando] = useState(false)
  const [guardado, setGuardado] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    configMercadoPago.ver()
      .then(setCfg)
      .catch((e) => setError((e as Error).message))
  }, [])

  function cambiar<K extends keyof Config>(campo: K, valor: Config[K]) {
    setCfg((actual) => (actual ? { ...actual, [campo]: valor } : actual))
    setGuardado(false)
  }

  async function guardar() {
    if (!cfg) return
    setGuardando(true)
    setError(null)
    setGuardado(false)
    try {
      setCfg(await configMercadoPago.guardar({
        access_token: cfg.access_token,
        user_id: cfg.user_id,
        pos_id: cfg.pos_id,
        webhook_secret: cfg.webhook_secret,
        auto_facturar: cfg.auto_facturar,
      }))
      setGuardado(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setGuardando(false)
    }
  }

  if (!cfg) {
    return (
      <div className="space-y-2">
        <AvisoDeError mensaje={error} />
        {!error && <p className="text-sm text-muted-foreground">Cargando…</p>}
      </div>
    )
  }

  return (
    <div className="max-w-2xl space-y-4">
      <div>
        <h3 className="text-base font-medium">Cobro con QR</h3>
        <p className="text-sm text-muted-foreground">
          El encargado pone el total del turno —cancha y buffet— en el QR impreso
          del mostrador y el cliente lo escanea. No hay ninguna imagen que
          mostrar en pantalla: el cartel es siempre el mismo y lo que cambia es
          cuánto cobra.
        </p>
      </div>

      <label className="block space-y-1">
        <span className="text-sm font-medium">Access Token</span>
        <Input
          type="password" autoComplete="off" placeholder="APP_USR-…"
          value={cfg.access_token}
          onChange={(e) => cambiar('access_token', e.target.value)}
        />
        <span className="block text-xs text-muted-foreground">
          El de la aplicación de MercadoPago del complejo, en «Tus integraciones
          → Credenciales de producción».
        </span>
      </label>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block space-y-1">
          <span className="text-sm font-medium">User ID</span>
          <Input
            placeholder="123456789"
            value={cfg.user_id}
            onChange={(e) => cambiar('user_id', e.target.value)}
          />
          <span className="block text-xs text-muted-foreground">
            El número de la cuenta vendedora, el mismo que muestra el perfil de
            MercadoPago.
          </span>
        </label>

        <label className="block space-y-1">
          <span className="text-sm font-medium">POS ID</span>
          <Input
            placeholder="CAJA01"
            value={cfg.pos_id}
            onChange={(e) => cambiar('pos_id', e.target.value)}
          />
          <span className="block text-xs text-muted-foreground">
            El <strong>identificador externo</strong> de la caja, no su nombre.
            Una caja sin ese campo cargado en MercadoPago no se puede
            direccionar y el cobro falla con «404».
          </span>
        </label>
      </div>

      <label className="block space-y-1">
        <span className="text-sm font-medium">Webhook Secret</span>
        <Input
          type="password" autoComplete="off"
          value={cfg.webhook_secret}
          onChange={(e) => cambiar('webhook_secret', e.target.value)}
        />
        <span className="block text-xs text-muted-foreground">
          La clave de firma de las notificaciones. <strong>Sin esto el portal no
          confirma ninguna reserva pagada</strong>: procesar una notificación sin
          verificarla sería dejar que cualquiera se lleve un turno.
        </span>
      </label>

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox" className="mt-0.5 size-4"
          checked={cfg.auto_facturar}
          onChange={(e) => cambiar('auto_facturar', e.target.checked)}
        />
        <span>
          Emitir la factura automáticamente al acreditarse el cobro
          <span className="block text-xs text-muted-foreground">
            Sólo para los turnos cobrados con este QR. Los demás se siguen
            facturando cuando alguien lo pide.
          </span>
        </span>
      </label>

      <AvisoDeError mensaje={error} />

      <div className="flex items-center gap-3">
        <button
          type="button" onClick={guardar} disabled={guardando}
          className={buttonVariants()}
        >
          {guardando ? 'Guardando…' : 'Guardar'}
        </button>
        {guardado && <span className="text-sm text-emerald-600">Guardado.</span>}
      </div>

      {!cfg.configurado && (
        <p className="rounded-md border border-amber-400/50 bg-amber-50 p-3 text-xs dark:bg-amber-950/30">
          Faltan datos: el mostrador no va a ofrecer el cobro con QR hasta que
          el Access Token, el User ID y el POS ID estén los tres cargados.
        </p>
      )}
    </div>
  )
}
