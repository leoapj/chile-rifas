# Chile Raffle — rifas en CLP con pago por transferencia bancaria

Django + DRF + PostgreSQL. Versión para Chile del proyecto *Cuba Raffle*, pero **independiente**
(proyecto y base de datos propios).

## Cómo funciona

1. El comprador elige números → se **reservan** (por defecto 30 min) y se calcula el monto **en CLP** en el servidor.
2. Ve los datos de tu(s) cuenta(s) bancaria(s), el monto exacto y un **código `RIFA-00042`** para poner en el comentario de la transferencia.
3. Transfiere desde su banco e ingresa el **N° de operación**. Sus números quedan reservados 24 h más (configurable) para que verifiques.
4. Tú ves el abono en tu cartola, entras al Admin → **Pagos** → filtro *Con comprobante* → acción **✅ Confirmar transferencia recibida**. Los números pasan a *Pagado*.
   Si la transferencia nunca llegó: **❌ Rechazar pago** (libera los números).
5. Si el comprador no avisa a tiempo, los números se liberan solos.

Si alguien transfiere *después* de que expiró su reserva, aún puedes confirmarlo desde el Admin siempre que
esos números sigan libres; si otra persona ya los tomó, el sistema te avisa y no pisa su compra.

## Primer arranque local (PyCharm)

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # Linux/Mac: cp .env.example .env   (y edita los valores)
```

Crea la base en PostgreSQL (psql o pgAdmin):

```sql
CREATE USER raffle_user WITH PASSWORD 'raffle_pass';
CREATE DATABASE chile_raffle_db OWNER raffle_user;
```

Luego, en la terminal de PyCharm:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py test            # opcional: 16 tests, incluye uno de compras simultáneas
python manage.py runserver
```

Abre http://127.0.0.1:8000/admin/ y configura, en este orden:

1. **Cuentas bancarias** → agrega tu cuenta (banco, tipo, número, titular, RUT).
2. **Configuración del sitio** → tiempos, máximo de números por compra y WhatsApp de contacto.
3. **Rifas** → crea una rifa con estado *Activa* (sus números se generan solos). Precio en pesos, sin decimales.

La web está en http://127.0.0.1:8000/

## Despliegue en Render

**Con Blueprint:** sube el repo a GitHub → Render → *New → Blueprint* → elige el repo (usa `render.yaml`).

**A mano:** crea una base PostgreSQL y un *Web Service* con:

| Campo | Valor |
|---|---|
| Build Command | `./build.sh` |
| Start Command | `gunicorn config.wsgi:application` |
| `DATABASE_URL` | la *Internal Database URL* de tu PostgreSQL |
| `SECRET_KEY` | una clave larga y aleatoria |
| `DEBUG` | `False` |

Después del primer deploy, crea tu usuario admin desde la pestaña *Shell* del servicio: `python manage.py createsuperuser`.

## Cosas a tener en cuenta

- **Limpieza de reservas:** ocurre automáticamente cuando alguien abre o compra en el sitio. Un Cron Job con
  `python manage.py release_expired_tickets` es opcional (solo para que el Admin esté siempre al día).
- **Imágenes de rifas:** el disco de Render se borra en cada deploy. Para que las fotos de los premios sobrevivan,
  usa un *Persistent Disk* de Render o un almacenamiento externo (Cloudinary, S3).
- **Seguridad:** las URLs de pago usan un UUID (no se pueden adivinar), hay límite de 10 reservas/min por IP y
  tope de números por compra.
- **Legal:** las rifas en Chile suelen requerir autorización de la autoridad (p. ej. Gobernación Provincial).
  Revisa los requisitos antes de cobrar.
