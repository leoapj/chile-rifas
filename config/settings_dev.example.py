"""
Configuración de DESARROLLO (tu PC): PostgreSQL local y correo real por Gmail.

Reutiliza `settings.py` y solo cambia lo local. Contiene tus claves: está en .gitignore y NO se sube a GitHub.
(Para recrearlo en otro equipo, copia settings_dev.example.py a settings_dev.py.)

    python manage.py runserver --settings=config.settings_dev     (o simplemente runserver)
"""

import os
from urllib.parse import quote

# --- Base de datos PostgreSQL LOCAL: ajusta estos 5 valores a los de tu PC ---
DB_NAME = "chile_raffle_db"
DB_USER = "raffle_user"
DB_PASSWORD = "raffle_pass"
DB_HOST = "localhost"
DB_PORT = "5432"

# --- Correo REAL (Gmail) ---
# Es lo ÚNICO que debes completar. Gmail no acepta tu contraseña normal por SMTP: crea una
# "contraseña de aplicación" (cuenta Google > Seguridad > Verificación en 2 pasos > Contraseñas de aplicaciones).
EMAIL_PASSWORD = "PON_AQUI_TU_CONTRASENA_DE_APLICACION"

# Variables que settings.py lee del entorno (aquí se fijan a mano; DEBUG=True activa el modo local).
os.environ["DEBUG"] = "True"
os.environ["SECRET_KEY"] = "dev-clave-solo-para-mi-computador"
os.environ["DATABASE_URL"] = f"postgres://{quote(DB_USER)}:{quote(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
os.environ["EMAIL_HOST_PASSWORD"] = EMAIL_PASSWORD
os.environ["BREVO_API_KEY"] = ""      # en local se usa Gmail (vacío evita que .env.production lo reponga)
os.environ["CLOUDINARY_URL"] = ""     # en local las fotos van a la carpeta media/

from .settings import *  # noqa: E402,F401,F403
