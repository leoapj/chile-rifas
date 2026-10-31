"""Páginas HTML (render en servidor). Consumen la API de views.py vía fetch()."""

import json

from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import BankAccount, Payment, Raffle, SiteConfiguration
from .services.reservations import release_expired_reservations


def home(request):
    release_expired_reservations()
    raffles = Raffle.objects.filter(status=Raffle.Status.ACTIVE)
    return render(request, "raffles/home.html", {"raffles": raffles})


@ensure_csrf_cookie
def raffle_detail_page(request, slug):
    release_expired_reservations()
    raffle = get_object_or_404(Raffle, slug=slug, status=Raffle.Status.ACTIVE)
    config = SiteConfiguration.load()
    return render(
        request,
        "raffles/detail.html",
        {
            "raffle": raffle,
            "tickets": list(raffle.tickets.order_by("number").values("number", "status")),
            "reservation_minutes": config.ticket_reservation_minutes,
            "max_tickets": config.max_tickets_per_purchase,
            "price_clp_js": json.dumps(raffle.price_clp),
            "max_tickets_js": json.dumps(config.max_tickets_per_purchase),
        },
    )


@ensure_csrf_cookie
def payment_status_page(request, public_id):
    release_expired_reservations()
    payment = get_object_or_404(Payment.objects.select_related("raffle"), public_id=public_id)
    config = SiteConfiguration.load()
    return render(
        request,
        "raffles/payment_status.html",
        {
            "payment": payment,
            "ticket_numbers": sorted(t.number for t in payment.tickets.all()),
            "bank_accounts": BankAccount.objects.filter(is_active=True),
            "config": config,
            "requires_proof": payment.status == Payment.Status.PENDING and not payment.has_proof,
        },
    )
