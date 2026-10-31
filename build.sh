#!/usr/bin/env bash
# Build Command en Render: ./build.sh   (DJANGO_SETTINGS_MODULE=config.settings viene de render.yaml)
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Opcional: crea tu usuario admin desde variables de entorno (no hace nada si ya existe o si no las defines).
if [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" && -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]]; then
  python manage.py createsuperuser --noinput --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" || true
fi
