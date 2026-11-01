# Chile Raffle — rifas en CLP con pago por transferencia bancaria

Django + DRF + PostgreSQL. Precios en pesos chilenos; el comprador transfiere y tú confirmas el abono desde el Admin.
Cada rifa puede tener **sus propias cuentas** para transferir (útil para publicar rifas de otras personas).

## Flujo de una compra
1. El comprador elige números (o «Sorprenderme» al azar) → quedan **reservados** (30 min por defecto).
2. Ve la cuenta de **esa** rifa, el monto exacto y un código `RIFA-00042` para el comentario de la transferencia.
3. Envía su **N° de operación** → reserva extendida (24 h por defecto) y **te llega un correo** para validar.
4. Admin → **Pagos** → filtro «Con comprobante» → **✅ Confirmar transferencia recibida**. (O ❌ Rechazar.)
5. Te avisan por correo al llegar al **50%** y cuando la rifa se **completa**.

## Panel de moderación
`/moderar/` (login solo para `is_staff`): pagos, rifas, números, ventas manuales, ganador, cuentas, configuración y moderadores. Ver DEPLOY.md §5.

## Configuraciones (como en tu otra app)
- `config/settings.py` — normal/producción (Render, variables de entorno). `config/settings_dev.py` — tu PC (**fuera de git**).
- Desarrollo: `python manage.py runserver --settings=config.settings_dev` (por defecto).

## Primer arranque local (PyCharm)
```bash
python -m venv venv
venv\Scripts\activate            # Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
```
1. Crea la base en PostgreSQL y revisa que `config/settings_dev.py` tenga tus datos (NAME, USER, PASSWORD):
```sql
CREATE USER raffle_user WITH PASSWORD 'raffle_pass';
CREATE DATABASE chile_raffle_db OWNER raffle_user;
```
2. **Correo**: en `settings_dev.py` reemplaza `PON_AQUI_TU_CONTRASENA_DE_APLICACION` por la contraseña de aplicación de
   `chilerifas93634@gmail.com` (Google → Seguridad → Verificación en 2 pasos → Contraseñas de aplicaciones; la contraseña normal no sirve para SMTP).
3. Comandos:
```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py send_test_email tu@correo.cl    # prueba el envío real
python manage.py test                            # 23 tests
python manage.py runserver
```
En `/admin/` configura: **Cuentas bancarias**, **Configuración del sitio** (tu *Correo para avisos*) y **Rifas**.

## Producción
Guía completa y gratuita (Render + Neon + Brevo + Cloudinary + UptimeRobot): **[DEPLOY.md](DEPLOY.md)**.

## Notas
- Las rifas ya sorteadas se muestran en «Sorteos realizados» cuando marcas la rifa como *Finalizada* y eliges el *ticket ganador*.
- **Legal:** las rifas en Chile suelen requerir autorización (p. ej. Gobernación Provincial). Revísalo antes de cobrar.
