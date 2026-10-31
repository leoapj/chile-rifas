"""
Prueba tu configuración de correo y muestra el error real si falla.

    python manage.py send_test_email
    python manage.py send_test_email otro@correo.cl
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from raffles.models import SiteConfiguration


class Command(BaseCommand):
    help = "Envía un correo de prueba (a Configuración del sitio > Correo para avisos, o al correo indicado)."

    def add_arguments(self, parser):
        parser.add_argument("to", nargs="?", help="Destinatario (opcional)")

    def handle(self, *args, **options):
        to = options["to"] or SiteConfiguration.load().admin_notification_email
        if not to:
            raise CommandError("No hay destinatario: completa 'Correo para avisos' en el Admin o pásalo como argumento.")

        backend = settings.EMAIL_BACKEND
        self.stdout.write(f"Backend de correo: {backend}")
        if "console" in backend or "locmem" in backend:
            self.stdout.write(self.style.WARNING("OJO: este backend no envía correos reales. Revisa tu settings."))
        try:
            send_mail("Prueba de Chile Raffle", "Si lees esto, el correo está bien configurado.", settings.DEFAULT_FROM_EMAIL, [to])
        except Exception as exc:  # aquí sí mostramos el error completo
            raise CommandError(f"Falló el envío a {to}: {exc!r}") from exc
        self.stdout.write(self.style.SUCCESS(f"Enviado a {to}."))
