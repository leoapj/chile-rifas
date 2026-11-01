"""
Correos de aviso al administrador. Nunca deben romper una compra: si el envío
falla se registra en el log y el flujo sigue.

El destinatario se edita en Admin > Configuración del sitio > "Correo para avisos".
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _send(subject: str, body: str) -> None:
    from raffles.models import SiteConfiguration

    to = SiteConfiguration.load().admin_notification_email
    if not to:
        logger.warning("Correo NO enviado (%s): falta el «Correo para avisos» en Admin > Configuración del sitio.", subject)
        return
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        logger.info("Correo enviado a %s: %s", to, subject)
    except Exception:  # noqa: BLE001 - un fallo de correo jamás debe afectar la compra
        logger.exception("No se pudo enviar el correo de aviso a %s", to)


def notify_proof_submitted(payment_id: int) -> None:
    """Avisa que un comprador dice haber transferido y hay que validar el abono."""
    from raffles.models import Payment

    payment = Payment.objects.select_related("raffle").get(pk=payment_id)
    numbers = ", ".join(f"#{n}" for n in sorted(t.number for t in payment.tickets.all()))
    admin_path = f"/admin/raffles/payment/{payment.pk}/change/"
    _send(
        f"[Rifas] Validar pago {payment.reference_code} — ${payment.amount:,}".replace(",", "."),
        f"Un comprador avisó que transfirió.\n\n"
        f"Código (comentario de la transferencia): {payment.reference_code}\n"
        f"Rifa: {payment.raffle.name}"
        + (f" (organiza: {payment.raffle.organizer_name})" if payment.raffle.organizer_name else "")
        + f"\nNúmeros: {numbers}\n"
        + "Debió transferir a: "
        + (" | ".join(str(a) for a in payment.raffle.payment_accounts()) or "(no hay cuenta configurada)")
        + "\n"
        f"Monto esperado: ${payment.amount:,} CLP\n".replace(",", ".")
        + f"N° de operación: {payment.buyer_reference}\n"
        f"Comprador: {payment.buyer_name} · {payment.buyer_phone} · {payment.buyer_email or 'sin correo'}\n\n"
        f"Revisa tu cartola y confirma en el Admin (Pagos > Con comprobante):\n{admin_path}\n",
    )


def notify_raffle_progress(raffle_id: int) -> None:
    """
    Se llama después de confirmar cada pago. Envía (una sola vez cada uno):
      - un aviso cuando se vendió el 50% de los números,
      - un aviso cuando se vendieron todos.
    "Vendido" = pagado y confirmado por ti.
    """
    from django.utils import timezone

    from raffles.models import Raffle, Ticket

    raffle = Raffle.objects.get(pk=raffle_id)
    total = raffle.total_tickets
    if not total:
        return
    sold = raffle.tickets.filter(status=Ticket.Status.PAID).count()

    if sold * 2 >= total:
        # El UPDATE condicional garantiza que solo UNA petición "gana" y envía el correo.
        won = Raffle.objects.filter(pk=raffle.pk, half_sold_notified_at__isnull=True).update(
            half_sold_notified_at=timezone.now()
        )
        if won:
            _send(
                f"[Rifas] 50% vendido: {raffle.name}",
                f"«{raffle.name}» ya vendió {sold} de {total} números ({round(sold / total * 100)}%).\n"
                f"Sorteo: {raffle.draw_date:%d-%m-%Y %H:%M}\n",
            )

    if sold >= total:
        _send(
            f"[Rifas] ¡Rifa completa! {raffle.name}",
            f"Se pagaron los {total} números de «{raffle.name}».\n"
            f"Fecha del sorteo: {raffle.draw_date:%d-%m-%Y %H:%M}\n",
        )
