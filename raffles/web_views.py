"""Páginas HTML (render en servidor). Consumen la API de views.py vía fetch()."""

import json

from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import Payment, Raffle, SiteConfiguration
from .services.reservations import release_expired_reservations


def home(request):
    release_expired_reservations()
    raffles = list(Raffle.objects.filter(status=Raffle.Status.ACTIVE).order_by("draw_date"))
    for raffle in raffles:
        raffle.available = raffle.tickets_available_count()
        raffle.sold = raffle.tickets_sold_count()
        raffle.percent = round(raffle.sold / raffle.total_tickets * 100) if raffle.total_tickets else 0
        raffle.almost_out = 0 < raffle.available <= raffle.total_tickets * 0.2

    # Rifa destacada: la que tiene el sorteo más cercano. Se muestra como boleto grande con su tablero real.
    now = timezone.now()
    upcoming = [r for r in raffles if r.draw_date >= now]
    featured = (upcoming or raffles or [None])[0]
    featured_cells = list(featured.tickets.order_by("number").values("number", "status")[:60]) if featured else []

    return render(
        request,
        "raffles/home.html",
        {
            "raffles": raffles,
            "featured": featured,
            "featured_cells": featured_cells,
            "numbers_sold": sum(r.sold for r in raffles),
            "winners": Raffle.objects.filter(status=Raffle.Status.FINISHED, winner_ticket__isnull=False)
            .select_related("winner_ticket").order_by("-draw_date")[:3],
            "config": SiteConfiguration.load(),
        },
    )


@ensure_csrf_cookie
def raffle_detail_page(request, slug):
    release_expired_reservations()
    raffle = get_object_or_404(Raffle, slug=slug, status=Raffle.Status.ACTIVE)
    config = SiteConfiguration.load()
    og_image = ""
    if raffle.image:
        og_image = request.build_absolute_uri(raffle.image.url) if not raffle.image.url.startswith("http") else raffle.image.url
    return render(
        request,
        "raffles/detail.html",
        {
            "raffle": raffle,
            "og_image": og_image,
            "page_url": request.build_absolute_uri(),
            "max_tickets_js_value": config.max_tickets_per_purchase,
            "tickets": list(raffle.tickets.order_by("number").values("number", "status")),
            "reservation_minutes": config.ticket_reservation_minutes,
            "max_tickets": config.max_tickets_per_purchase,
            "price_clp_js": json.dumps(raffle.price_clp),
            "share_text_js": json.dumps(f"¡Mira esta rifa: {raffle.name}! Número desde ${raffle.price_clp:,}".replace(",", ".")),
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
            "bank_accounts": payment.raffle.payment_accounts(),
            "config": config,
            "requires_proof": payment.status == Payment.Status.PENDING and not payment.has_proof,
        },
    )


def healthz(request):
    """Responde 'ok' sin tocar la base de datos. Úsalo para el monitor que mantiene despierto el servidor."""
    return HttpResponse("ok", content_type="text/plain")
