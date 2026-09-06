import { expect, test } from '@playwright/test'

// Lo único que un unitario no puede ver: que la SPA construida, servida por la
// app real, deje entrar y muestre una pantalla de dominio. Si el bundle quedó
// viejo, si el gate de Términos tapa todo, si el login devuelve HTML por el
// catch-all en vez de JSON, esto se pone rojo y los unitarios no.
//
// Los campos se ubican por los `id` que pone `createLogin` de libra-ui
// (`#username`, `#password`): `getByLabel('Contraseña')` matchea también al
// botón «Mostrar contraseña», y el nombre del producto es un wordmark, no un
// heading accesible. La primera pantalla se reconoce por el sidebar de libra-ui
// (`data-sidebar="sidebar"`) y por su título.
test('entra por /login, acepta los Términos y ve la primera pantalla', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('button', { name: 'Ingresar' })).toBeVisible()

  await page.locator('#username').fill(process.env.SMOKE_USER ?? 'admin')
  await page.locator('#password').fill(process.env.SMOKE_PASSWORD ?? '')
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page).toHaveURL(/\/agenda/)

  // Una instancia recién nacida pone el gate de Términos y Condiciones delante
  // de todo (libraauth v0.34.0, libra-ui GateTerminos): es lo que ve un cliente
  // nuevo, y lo que en agosto dejó las ocho demos "vacías" sin que ningún
  // unitario lo viera. El smoke lo atraviesa como el humano: tilda, acepta.
  await expect(page.getByRole('heading', { name: /Términos y Condiciones/ })).toBeVisible()
  await page.getByRole('checkbox', { name: /Leí y acepto/ }).check()
  await page.getByRole('button', { name: 'Aceptar y continuar' }).click()

  await expect(page.locator('[data-sidebar="sidebar"]').first()).toBeVisible()
  await expect(page.getByText('Agenda', { exact: true }).first()).toBeVisible()
  await expect(page.locator('#username')).toHaveCount(0)
})

test('una credencial mala no entra (control)', async ({ page }) => {
  // Sin esto el test de arriba podría pasar con un login que acepte cualquier
  // cosa; el rechazo tiene que verse en la pantalla, no sólo en la API.
  await page.goto('/login')
  await page.locator('#username').fill('admin')
  await page.locator('#password').fill('esta-no-es')
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page).toHaveURL(/\/login/)
  await expect(page.locator('p.text-destructive')).toBeVisible()
  await expect(page.locator('#username')).toBeVisible()
})
