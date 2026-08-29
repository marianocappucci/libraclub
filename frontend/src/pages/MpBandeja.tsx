// La bandeja de MercadoPago: conciliar lo que entró a la cuenta y facturarlo.
//
// Re-export puro de `libra-ui/MpBandeja` — no hay nada que este producto
// ajuste. La pantalla estaba escrita **dos veces**, en Contalibra y Restolibra,
// con una sola línea de diferencia; se extrajo al kit (v0.45.0) y LibraClub la
// estrena desde ahí, así que no llegó a existir la tercera copia.
//
// 🔑 **No hace falta ninguna prop porque el backend ya estaba unificado.** Los
// tres productos montan el mismo `libracore.mp_bandeja_router` bajo el mismo
// prefijo `/api/mp-bandeja`, y lo único que este complejo decide —que los
// cobros de reservas NO entren a la bandeja, porque su webhook ya los
// resolvió— se resuelve del lado del servidor, en `app/routers/mp_bandeja.py`.
//
// El archivo existe igual, en vez de importar el kit directo en `App.tsx`,
// para que la pantalla se siga viendo en `pages/` como todas las demás.
export { MpBandeja } from 'libra-ui/MpBandeja'
