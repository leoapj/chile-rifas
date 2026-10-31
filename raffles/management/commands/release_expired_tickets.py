"""
Libera los números cuya reserva venció sin que llegara comprobante.

    python manage.py release_expired_tickets

Es OPCIONAL: la web ya ejecuta esta limpieza cada vez que alguien abre una rifa
o reserva. Prográmalo como Cron Job (Render) solo si quieres que el Admin
siempre refleje el estado real aunque nadie visite el sitio.
"""

from django.core.management.base import BaseCommand

from raffles.services.reservations import release_expired_reservations


class Command(BaseCommand):
    help = "Expira los pagos pendientes vencidos y libera sus números."

    def handle(self, *args, **options):
        payments, tickets = release_expired_reservations()
        self.stdout.write(self.style.SUCCESS(f"{payments} pago(s) expirado(s), {tickets} número(s) liberado(s)."))
