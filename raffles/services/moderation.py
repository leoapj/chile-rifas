"""
Operaciones del panel de moderación que van más allá de confirmar/rechazar un pago.

Todas son atómicas y bloquean filas con select_for_update() (mismo orden que el resto del
proyecto: pagos primero, números después) para no chocar con compras simultáneas.
"""

import random
from datetime import timedelta
import re

from django.db import transaction
from django.utils import timezone

from raffles import models as m
from raffles.services import notifications


class ModerationError(Exception):
    """Mensaje pensado para mostrarse tal cual al moderador."""


def parse_numbers(text: str, total: int) -> list[int]:
    """'1, 5, 10-12' -> [1, 5, 10, 11, 12]. Valida que estén dentro de 1..total."""
    numbers: set[int] = set()
    for part in re.split(r"[,\s;]+", (text or "").strip()):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)-(\d+)", part)
        if match:
            a, b = int(match[1]), int(match[2])
            if a > b or b - a > 5000:
                raise ModerationError(f"Rango inválido: {part}")
            numbers.update(range(a, b + 1))
        elif part.isdigit():
            numbers.add(int(part))
        else:
            raise ModerationError(f"No entiendo «{part}». Usa números separados por coma o rangos como 10-15.")
    if not numbers:
        raise ModerationError("Escribe al menos un número.")
    out_of_range = sorted(n for n in numbers if n < 1 or n > total)
    if out_of_range:
        raise ModerationError(f"Fuera de rango (1 a {total}): {out_of_range[:10]}")
    return sorted(numbers)


@transaction.atomic
def manual_sale(*, raffle, numbers: list[int], name: str, phone: str, email: str, notes: str, user) -> "m.Payment":
    """
    Registra una venta hecha fuera de la web (efectivo, WhatsApp…): crea un pago ya PAGADO y marca los
    números como pagados. Solo acepta números DISPONIBLES.
    """
    tickets = list(m.Ticket.objects.select_for_update().filter(raffle=raffle, number__in=numbers).order_by("number"))
    missing = set(numbers) - {t.number for t in tickets}
    if missing:
        raise ModerationError(f"Los números {sorted(missing)} no existen en esta rifa.")
    busy = [t.number for t in tickets if t.status != m.Ticket.Status.AVAILABLE]
    if busy:
        raise ModerationError(f"Los números {busy} no están disponibles (están reservados, pagados o bloqueados).")

    now = timezone.now()
    payment = m.Payment.objects.create(
        raffle=raffle,
        status=m.Payment.Status.COMPLETED,
        amount=raffle.price_clp * len(tickets),
        buyer_name=name,
        buyer_phone=phone,
        buyer_email=email,
        buyer_reference="venta manual",
        admin_notes=notes,
        verified_by=user,
        verified_at=now,
        expires_at=now,
    )
    payment.tickets.set(tickets)
    for ticket in tickets:
        ticket.mark_paid(payment)
    transaction.on_commit(lambda: notifications.notify_buyer_payment_result(payment.pk))
    transaction.on_commit(lambda: notifications.notify_raffle_progress(raffle.pk))
    return payment


@transaction.atomic
def set_winner(raffle, number: int | None = None) -> "m.Ticket":
    """
    Fija el número ganador y finaliza la rifa. Sin `number` elige uno al azar entre los PAGADOS.
    Con `number` (por ejemplo el que salió en la lotería) exige que esté pagado.
    """
    raffle = m.Raffle.objects.select_for_update().get(pk=raffle.pk)
    paid = list(raffle.tickets.filter(status=m.Ticket.Status.PAID))
    if number is None:
        if not paid:
            raise ModerationError("No hay números pagados para sortear.")
        winner = random.SystemRandom().choice(paid)
    else:
        winner = next((t for t in paid if t.number == number), None)
        if winner is None:
            raise ModerationError(f"El número {number} no está pagado, no puede ser el ganador.")
    raffle.winner_ticket = winner
    raffle.status = m.Raffle.Status.FINISHED
    raffle.save(update_fields=["winner_ticket", "status", "updated_at"])
    return winner


@transaction.atomic
def sync_tickets(raffle) -> None:
    """Deja los números de la rifa en 1..total_tickets (crea los que faltan; borra los libres que sobran)."""
    existing = set(raffle.tickets.values_list("number", flat=True))
    missing = [n for n in range(1, raffle.total_tickets + 1) if n not in existing]
    if missing:
        m.Ticket.objects.bulk_create([m.Ticket(raffle=raffle, number=n) for n in missing])
    raffle.tickets.filter(number__gt=raffle.total_tickets, status=m.Ticket.Status.AVAILABLE).delete()


def extend_reservation(payment, hours: int) -> None:
    """Alarga la reserva de un pago pendiente (por ejemplo si el comprador avisó que transfiere más tarde)."""
    with transaction.atomic():
        payment = m.Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status != m.Payment.Status.PENDING:
            raise ModerationError("Solo se puede extender un pago pendiente.")
        base = max(payment.expires_at, timezone.now())
        new_expiry = base + timedelta(hours=hours)
        payment.expires_at = new_expiry
        payment.save(update_fields=["expires_at", "updated_at"])
        payment.tickets.filter(status=m.Ticket.Status.RESERVED).update(reserved_until=new_expiry)
