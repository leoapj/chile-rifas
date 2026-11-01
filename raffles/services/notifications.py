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


def _site_url(path: str) -> str:
    """Enlace absoluto para usar dentro de un correo (SITE_URL + ruta)."""
    return f"{settings.SITE_URL}{path}" if settings.SITE_URL else path


def _clp(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def notify_buyer_payment_result(payment_id: int) -> None:
    """
    Avisa al COMPRADOR (si dejó su correo) que su pago fue aprobado o rechazado,
    con sus números y datos. Nunca rompe el flujo: si falla, se registra en el log.
    """
    from html import escape

    from raffles.models import Payment, SiteConfiguration

    payment = Payment.objects.select_related("raffle").get(pk=payment_id)
    if not payment.buyer_email or payment.status not in (Payment.Status.COMPLETED, Payment.Status.FAILED):
        return
    raffle = payment.raffle
    numbers = ", ".join(f"#{n}" for n in sorted(t.number for t in payment.tickets.all()))
    page = _site_url(f"/pago/{payment.public_id}/")
    wa = SiteConfiguration.load().contact_whatsapp
    contact = f"\nDudas: https://wa.me/{wa}" if wa else ""

    if payment.status == Payment.Status.COMPLETED:
        subject = f"✅ Pago aprobado — {raffle.name} ({payment.reference_code})"
        lines = [
            f"¡Hola {payment.buyer_name}! Confirmamos tu transferencia. Ya estás participando.",
            "",
            f"Tu(s) número(s): {numbers}",
            f"Rifa: {raffle.name}" + (f" (organiza: {raffle.organizer_name})" if raffle.organizer_name else ""),
            f"Fecha del sorteo: {raffle.draw_date:%d-%m-%Y %H:%M}",
            f"Monto pagado: {_clp(payment.amount)} CLP",
            f"Código de compra: {payment.reference_code}",
            f"Nombre: {payment.buyer_name} · Teléfono: {payment.buyer_phone}",
            "",
            f"Ver tu compra: {page}",
            "¡Mucha suerte!" + contact,
        ]
        head, color = "Pago aprobado", "#1f8f74"
    else:
        subject = f"❌ Pago no confirmado — {raffle.name} ({payment.reference_code})"
        lines = [
            f"Hola {payment.buyer_name}. No pudimos confirmar tu transferencia, así que liberamos tus números ({numbers}).",
            "",
            f"Rifa: {raffle.name}",
            f"Monto esperado: {_clp(payment.amount)} CLP · Código: {payment.reference_code}",
            "",
            "Si ya transferiste, escríbenos con tu comprobante para revisarlo." + contact,
            f"Detalle: {page}",
        ]
        head, color = "Pago no confirmado", "#c0392b"

    text = "\n".join(lines)
    html = (
        f'<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;border:1px solid #ddd;border-radius:8px;overflow:hidden">'
        f'<div style="background:{color};color:#fff;padding:16px 20px;font-size:20px;font-weight:bold">{head}</div>'
        f'<div style="padding:20px;color:#222;line-height:1.5">'
        + "".join(f"<p style='margin:6px 0'>{escape(l)}</p>" if l else "<br>" for l in lines)
        + "</div></div>"
    )
    try:
        send_mail(subject, text, settings.DEFAULT_FROM_EMAIL, [payment.buyer_email], html_message=html)
        logger.info("Correo de resultado enviado al comprador de %s", payment.reference_code)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo enviar el correo al comprador de %s", payment.reference_code)


def notify_proof_submitted(payment_id: int) -> None:
    """Avisa que un comprador dice haber transferido y hay que validar el abono."""
    from raffles.models import Payment

    payment = Payment.objects.select_related("raffle").get(pk=payment_id)
    numbers = ", ".join(f"#{n}" for n in sorted(t.number for t in payment.tickets.all()))
    mod_link = _site_url(f"/moderar/pagos/{payment.pk}/")
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
        f"👉 Revisa tu cartola y modera con un clic:\n{mod_link}\n",
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
