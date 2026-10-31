"""Liberación de reservas vencidas (compartida por el comando, el cron y las vistas)."""

from django.db import transaction
from django.utils import timezone

from raffles.models import Payment, Ticket


@transaction.atomic
def release_expired_reservations() -> tuple[int, int]:
    """
    Marca como EXPIRADOS los pagos pendientes cuyo plazo venció y libera sus números.

    Orden de bloqueo: primero pagos, luego tickets (igual que en models.py y views.py)
    para no generar deadlocks. Devuelve (pagos_expirados, tickets_liberados).
    """
    now = timezone.now()

    expired_payments = list(
        Payment.objects.select_for_update().filter(status=Payment.Status.PENDING, expires_at__lt=now).order_by("pk")
    )
    for payment in expired_payments:
        payment.status = Payment.Status.EXPIRED
        payment.save(update_fields=["status", "updated_at"])

    expired_tickets = list(
        Ticket.objects.select_for_update()
        .filter(status=Ticket.Status.RESERVED, reserved_until__lt=now)
        .order_by("pk")
    )
    for ticket in expired_tickets:
        ticket.release()

    return len(expired_payments), len(expired_tickets)
