# Publicar en producción (gratis) — paso a paso

Piezas: **GitHub** (código) → **Render** (servidor) + **Neon** (base PostgreSQL) + **Brevo** (correos) + **Cloudinary** (fotos).
Sin tarjeta de crédito. ~25 minutos.

## Cómo está organizada la configuración

| Archivo | Para qué | Se sube a GitHub |
|---|---|---|
| `config/settings.py` | **normal / producción** (Render): lee todo de variables de entorno | sí (sin claves) |
| `config/settings_dev.py` | **tu PC**: PostgreSQL local + Gmail real (reutiliza `settings.py`) | **no** (.gitignore) |

- Desarrollo: `python manage.py runserver --settings=config.settings_dev` (es el valor por defecto de `manage.py`, así que basta `runserver`).
- Producción: Render ya usa `config.settings` (viene en `render.yaml`).
- `config/settings_dev.example.py` es una copia para recrear tu archivo en otro equipo.

## 0. Sube el código a GitHub
Repositorio **privado**. El `.gitignore` ya excluye `settings_dev.py` y cualquier `.env*`. Nunca pegues claves en el chat.

## 1. Base de datos: Neon
1. https://neon.com → crea cuenta → proyecto (región **AWS US East**).
2. **Connect** → copia la cadena `postgresql://...?sslmode=require`. Es tu `DATABASE_URL`.

## 2. Correos: Brevo
Render gratis **bloquea el SMTP** (Gmail por SMTP no funciona allí), así que en producción el correo sale por la API de Brevo (HTTPS),
con remitente `chilerifas93634@gmail.com`.
1. https://www.brevo.com → regístrate con **chilerifas93634@gmail.com** (plan gratis: 300 correos al día).
2. *Senders, Domains & Dedicated IPs → Senders → Add a sender*: `chilerifas93634@gmail.com`, y confírmalo con el código que llega a ese correo.
3. *SMTP & API → API keys → Generate a new API key* → cópiala (`xkeysib-...`). Es tu `BREVO_API_KEY`.
4. Aviso honesto: como Gmail no permite autenticar su dominio con Brevo, el correo puede llegar con «vía brevo» o caer en **Spam** la primera vez.
   Márcalo como «No es spam». Si te molesta, la alternativa es un plan de pago de Render (permite SMTP de Gmail) o un dominio propio.

## 3. Fotos: Cloudinary
https://cloudinary.com → cuenta gratis → Dashboard → *API Environment variable* → `cloudinary://...`. Es tu `CLOUDINARY_URL`.
(Sin esto, las fotos subidas se pierden cada vez que Render reinicia.)

## 4. Servidor: Render
1. https://render.com → *New + → Blueprint* → tu repositorio. Lee `render.yaml`.
2. Completa:

| Variable | Valor |
|---|---|
| `DATABASE_URL` | la de Neon |
| `BREVO_API_KEY` | la de Brevo |
| `CLOUDINARY_URL` | la de Cloudinary |
| `DJANGO_SUPERUSER_USERNAME/PASSWORD/EMAIL` | opcional: crea tu admin al desplegar (o créalo desde tu PC, abajo) |

`SECRET_KEY`, `DEBUG=False`, `DJANGO_SETTINGS_MODULE=config.settings`, hosts y HTTPS se configuran solos.

## 5. Panel de moderación (`/moderar/`)
Es el panel pensado para el día a día (y para otras personas que te ayuden), más simple que el Admin de Django:
- **Entrar:** `https://TU-SITIO.onrender.com/moderar/` (también hay un enlace discreto «Acceso administradores» al pie del sitio). Usa tu usuario admin.
- **Inicio:** pagos por revisar, totales y avance de cada rifa. **Pagos:** buscar/filtrar, confirmar o rechazar (uno o varios a la vez), corregir datos, extender reserva, reenviar el correo al comprador.
- **Rifas:** crear/editar, publicar o cancelar, tablero de números (bloquear/liberar), **venta manual** (efectivo/WhatsApp), elegir **ganador**, exportar CSV y ver el 10 % de comisión.
- **Cuentas:** bancos por rifa. **Configuración:** correo de avisos, WhatsApp, tiempos. **Moderadores** (solo administrador): crear personas que pueden moderar sin ver el Admin de Django.
- El correo que te llega al enviarse un comprobante trae un botón-enlace directo al pago en este panel. Para que el enlace salga completo, Render lo deduce solo (o define `SITE_URL`).
- Al confirmar o rechazar, el comprador recibe un correo con su resultado, números y datos (si dejó su correo).

## 5b. Configura el sitio desde el Admin (`/admin/`) — alternativa avanzada
1. **Cuentas bancarias**: tus cuentas generales.
2. **Configuración del sitio**: *Correo para avisos* = donde quieres recibir los avisos (tu correo personal). Luego marca la configuración y usa la acción **📧 Enviar correo de prueba**.
3. **Rifas**: crea la rifa y, si es de otra persona, escribe su nombre en *Organizador* y elige **sus** cuentas en *Cuentas para transferir*.

### Publicar la rifa de otra persona
Cuando te contacte: (1) cobra tu comisión por adelantado, (2) crea su cuenta bancaria en *Cuentas bancarias*, (3) crea la rifa,
pone *Organizador*, asigna esa cuenta y déjala en estado *Activa*. Cada rifa muestra solo su cuenta; las rifas sin cuenta propia usan las generales.
El correo de «validar pago» te indica a qué cuenta debió transferir el comprador, para que busques el abono en la cartola correcta.

## 6. Operar la base de producción desde tu PC
1. Copia `.env.production.example` a `.env.production` y pega `SECRET_KEY`, `DATABASE_URL`, etc.
2. Ejecuta: `python manage.py createsuperuser --settings=config.settings` (o `migrate`, `send_test_email`…).
3. Verás `⚠️ CONECTADO A LA BASE REMOTA (PRODUCCIÓN)`, y `test` / `flush` quedan bloqueados.

## 7. Que no se «duerma»
Render gratis apaga el servicio tras 15 min sin visitas (tarda ~1 min en despertar). Solución gratis:
1. https://uptimerobot.com → *Add New Monitor* → tipo **HTTP(s)** → URL `https://TU-URL.onrender.com/healthz/` → intervalo **5 minutos**.
2. Las 750 horas gratis de Render al mes alcanzan para un servicio encendido todo el mes.

## Límites del plan gratis (verificados)
- **Render:** se duerme a los 15 min, sin terminal, disco temporal, SMTP bloqueado.
- **Neon:** 1 GB y 100 horas de cómputo al mes; no caduca.
- **Brevo:** 300 correos al día.
- Con ventas reales conviene pasar Render a un plan de pago.
