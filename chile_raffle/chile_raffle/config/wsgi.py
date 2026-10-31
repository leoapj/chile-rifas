"""Configuración WSGI para despliegue en Render (gunicorn) y servidores tradicionales."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
