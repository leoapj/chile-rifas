"""
Panel de moderación (/moderar/): lo mismo que el Admin de Django, pero pensado para personas no técnicas.

Acceso: solo usuarios con is_staff. Todas las acciones que cambian datos son POST (con CSRF).
La lógica delicada (confirmar, rechazar, bloquear filas) vive en models.py y services/; aquí solo se orquesta.
"""

import csv
import functools

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import mod_forms as forms
from .models import BankAccount, Payment, PaymentStateError, Raffle, SiteConfiguration, Ticket
from .services import moderation as svc
from .services import notifications
from .services.reservations import release_expired_reservations

User = get_user_model()


# ----------------------------------------------------------------------------- acceso
class ModLoginView(LoginView):
    template_name = "moderar/login.html"
    authentication_form = forms.StaffLoginForm
    redirect_authenticated_user = True


def staff_required(view):
    """Solo personal autorizado; los demás van al login."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and user.is_active and user.is_staff):
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return view(request, *args, **kwargs)

    return wrapper


def superuser_required(view):
    @functools.wraps(view)
    @staff_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Solo el administrador principal puede gestionar moderadores.")
            return redirect("mod-dashboard")
        return view(request, *args, **kwargs)

    return wrapper


def _back(request, fallback, *args):
    """Vuelve a la página de origen si es segura; si no, a `fallback`."""
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/moderar/") else reverse(fallback, args=args))


# ----------------------------------------------------------------------------- inicio
@staff_required
def dashboard(request):
    release_expired_reservations()
    now = timezone.now()
    pending = Payment.objects.filter(status=Payment.Status.PENDING, expires_at__gt=now)
    to_review = pending.filter(proof_submitted_at__isnull=False)
    completed = Payment.objects.filter(status=Payment.Status.COMPLETED)
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    raffles = list(
        Raffle.objects.filter(status=Raffle.Status.ACTIVE)
        .annotate(paid_count=Count("tickets", filter=Q(tickets__status=Ticket.Status.PAID)),
                  reserved_count=Count("tickets", filter=Q(tickets__status=Ticket.Status.RESERVED)))
        .order_by("draw_date")
    )
    for r in raffles:
        r.percent = round(r.paid_count / r.total_tickets * 100) if r.total_tickets else 0
    return render(request, "moderar/dashboard.html", {
        "to_review": to_review.select_related("raffle").order_by("proof_submitted_at")[:15],
        "to_review_count": to_review.count(),
        "no_proof_count": pending.filter(proof_submitted_at__isnull=True).count(),
        "completed_today": completed.filter(verified_at__gte=today).count(),
        "revenue": completed.aggregate(s=Sum("amount"))["s"] or 0,
        "revenue_today": completed.filter(verified_at__gte=today).aggregate(s=Sum("amount"))["s"] or 0,
        "paid_tickets": Ticket.objects.filter(status=Ticket.Status.PAID).count(),
        "raffles": raffles,
        "recent": Payment.objects.select_related("raffle").order_by("-created_at")[:8],
        "nav": "dashboard",
    })


@staff_required
@require_POST
def release_expired(request):
    payments, tickets = release_expired_reservations()
    messages.success(request, f"Reservas vencidas liberadas: {payments} pago(s), {tickets} número(s).")
    return _back(request, "mod-dashboard")


# ----------------------------------------------------------------------------- pagos
def _filtered_payments(request):
    qs = Payment.objects.select_related("raffle").prefetch_related("tickets")
    status = request.GET.get("estado", "")
    proof = request.GET.get("comprobante", "")
    raffle = request.GET.get("rifa", "")
    q = request.GET.get("q", "").strip()
    if status == "por_revisar":
        qs = qs.filter(status=Payment.Status.PENDING, proof_submitted_at__isnull=False)
    elif status in Payment.Status.values:
        qs = qs.filter(status=status)
    if proof == "si":
        qs = qs.filter(proof_submitted_at__isnull=False)
    elif proof == "no":
        qs = qs.filter(proof_submitted_at__isnull=True)
    if raffle.isdigit():
        qs = qs.filter(raffle_id=int(raffle))
    if q:
        code = q.upper().replace("RIFA-", "")
        cond = (Q(buyer_name__icontains=q) | Q(buyer_phone__icontains=q) | Q(buyer_email__icontains=q)
                | Q(buyer_reference__icontains=q) | Q(raffle__name__icontains=q))
        if code.isdigit():
            cond |= Q(pk=int(code)) | Q(tickets__number=int(code))
        qs = qs.filter(cond).distinct()
    return qs.order_by("-proof_submitted_at", "-created_at") if status == "por_revisar" else qs


@staff_required
def payment_list(request):
    release_expired_reservations()
    page = Paginator(_filtered_payments(request), 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "moderar/payments.html", {
        "page": page, "raffles": Raffle.objects.all(), "querystring": params.urlencode(),
        "f": {k: request.GET.get(k, "") for k in ("estado", "comprobante", "rifa", "q")},
        "statuses": Payment.Status.choices, "nav": "pagos",
    })


@staff_required
def payment_detail(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("raffle", "verified_by"), pk=pk)
    return render(request, "moderar/payment_detail.html", {
        "payment": payment,
        "tickets": payment.tickets.order_by("number"),
        "accounts": payment.raffle.payment_accounts(),
        "form": forms.PaymentEditForm(instance=payment),
        "can_confirm": payment.status in (Payment.Status.PENDING, Payment.Status.EXPIRED),
        "can_reject": payment.status != Payment.Status.COMPLETED and payment.status != Payment.Status.FAILED,
        "nav": "pagos",
    })


def _apply_payment_action(request, payment, action) -> bool:
    try:
        if action == "confirm":
            payment.mark_completed(verified_by=request.user)
            messages.success(request, f"✅ {payment.reference_code} confirmado."
                             + (" Se avisó al comprador por correo." if payment.buyer_email else ""))
        elif action == "reject":
            payment.mark_failed(verified_by=request.user)
            messages.success(request, f"❌ {payment.reference_code} rechazado y números liberados."
                             + (" Se avisó al comprador por correo." if payment.buyer_email else ""))
        return True
    except PaymentStateError as exc:
        messages.warning(request, str(exc))
        return False


@staff_required
@require_POST
def payment_action(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    action = request.POST.get("action")
    if action in ("confirm", "reject"):
        _apply_payment_action(request, payment, action)
    elif action == "save":
        form = forms.PaymentEditForm(request.POST, instance=payment)
        if form.is_valid():
            form.save()
            messages.success(request, "Datos guardados.")
        else:
            messages.error(request, "Revisa los datos: " + "; ".join(sum(form.errors.values(), [])))
    elif action == "resend":
        if payment.status in (Payment.Status.COMPLETED, Payment.Status.FAILED) and payment.buyer_email:
            notifications.notify_buyer_payment_result(payment.pk)
            messages.success(request, f"Correo reenviado a {payment.buyer_email}.")
        else:
            messages.warning(request, "Solo se reenvía en pagos confirmados o rechazados que tengan correo.")
    elif action == "extend":
        try:
            svc.extend_reservation(payment, int(request.POST.get("hours", 24)))
            messages.success(request, "Reserva extendida.")
        except (svc.ModerationError, ValueError) as exc:
            messages.warning(request, str(exc))
    return _back(request, "mod-payment-detail", pk)


@staff_required
@require_POST
def payment_bulk(request):
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    action = request.POST.get("action")
    if not ids or action not in ("confirm", "reject"):
        messages.warning(request, "Marca al menos un pago y elige una acción.")
        return _back(request, "mod-payments")
    done = sum(_apply_payment_action(request, p, action) for p in Payment.objects.filter(pk__in=ids).order_by("pk"))
    messages.info(request, f"{done} de {len(ids)} pago(s) procesados.")
    return _back(request, "mod-payments")


# ----------------------------------------------------------------------------- rifas
@staff_required
def raffle_list(request):
    raffles = Raffle.objects.annotate(
        paid_count=Count("tickets", filter=Q(tickets__status=Ticket.Status.PAID), distinct=True),
        reserved_count=Count("tickets", filter=Q(tickets__status=Ticket.Status.RESERVED), distinct=True),
    ).order_by("-created_at")
    status = request.GET.get("estado")
    if status in Raffle.Status.values:
        raffles = raffles.filter(status=status)
    for r in raffles:
        r.percent = round(r.paid_count / r.total_tickets * 100) if r.total_tickets else 0
    return render(request, "moderar/raffles.html", {
        "raffles": raffles, "estado": status or "", "statuses": Raffle.Status.choices, "nav": "rifas",
    })


@staff_required
def raffle_form(request, pk=None):
    raffle = get_object_or_404(Raffle, pk=pk) if pk else None
    form = forms.RaffleForm(request.POST or None, request.FILES or None, instance=raffle)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        svc.sync_tickets(saved)
        messages.success(request, f"Rifa «{saved.name}» guardada.")
        return redirect("mod-raffle-detail", saved.pk)
    return render(request, "moderar/raffle_form.html", {"form": form, "raffle": raffle, "nav": "rifas"})


@staff_required
def raffle_detail(request, pk):
    release_expired_reservations()
    raffle = get_object_or_404(Raffle.objects.select_related("winner_ticket"), pk=pk)
    tickets = raffle.tickets.order_by("number")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("estado", "")
    shown = tickets
    if status in Ticket.Status.values:
        shown = shown.filter(status=status)
    if q:
        cond = Q(buyer_name__icontains=q) | Q(buyer_phone__icontains=q) | Q(buyer_email__icontains=q)
        if q.isdigit():
            cond |= Q(number=int(q))
        shown = shown.filter(cond)
    counts = {s: tickets.filter(status=s).count() for s in Ticket.Status.values}
    revenue = raffle.payments.filter(status=Payment.Status.COMPLETED).aggregate(s=Sum("amount"))["s"] or 0
    paid_payments = {t.pk: p for p in raffle.payments.filter(status__in=["completed", "pending"]).prefetch_related("tickets")
                     for t in p.tickets.all()}
    cells = [{"t": t, "payment": paid_payments.get(t.pk)} for t in shown]
    return render(request, "moderar/raffle_detail.html", {
        "raffle": raffle, "cells": cells, "counts": counts, "q": q, "estado": status,
        "revenue": revenue, "commission": round(revenue * 0.10),
        "sale_form": forms.ManualSaleForm(), "winner_form": forms.WinnerForm(),
        "accounts": raffle.payment_accounts(), "nav": "rifas",
        "ticket_statuses": Ticket.Status.choices,
    })


@staff_required
@require_POST
def raffle_action(request, pk):
    raffle = get_object_or_404(Raffle, pk=pk)
    action = request.POST.get("action")
    if action in ("activate", "draft", "cancel", "finish"):
        raffle.status = {"activate": Raffle.Status.ACTIVE, "draft": Raffle.Status.DRAFT,
                         "cancel": Raffle.Status.CANCELLED, "finish": Raffle.Status.FINISHED}[action]
        raffle.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Estado: {raffle.get_status_display()}.")
    elif action == "winner":
        form = forms.WinnerForm(request.POST)
        if form.is_valid():
            try:
                winner = svc.set_winner(raffle, form.cleaned_data["number"])
                messages.success(request, f"🏆 Ganador: número #{winner.number} — {winner.buyer_name} ({winner.buyer_phone}). Rifa finalizada.")
            except svc.ModerationError as exc:
                messages.warning(request, str(exc))
    elif action == "clear_winner":
        raffle.winner_ticket = None
        raffle.save(update_fields=["winner_ticket", "updated_at"])
        messages.success(request, "Ganador quitado.")
    elif action == "delete":
        if raffle.tickets.filter(status=Ticket.Status.PAID).exists():
            messages.error(request, "No se puede eliminar: tiene números pagados. Cancélala en su lugar.")
        else:
            name = raffle.name
            raffle.delete()
            messages.success(request, f"Rifa «{name}» eliminada.")
            return redirect("mod-raffles")
    return _back(request, "mod-raffle-detail", pk)


@staff_required
@require_POST
def ticket_action(request, pk, number):
    raffle = get_object_or_404(Raffle, pk=pk)
    ticket = get_object_or_404(Ticket, raffle=raffle, number=number)
    action = request.POST.get("action")
    if action == "release" and ticket.status == Ticket.Status.RESERVED:
        ticket.release()
        messages.success(request, f"Número #{number} liberado.")
    elif action == "block" and ticket.status == Ticket.Status.AVAILABLE:
        ticket.status = Ticket.Status.CANCELLED
        ticket.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Número #{number} bloqueado (no se puede comprar).")
    elif action == "unblock" and ticket.status == Ticket.Status.CANCELLED:
        ticket.status = Ticket.Status.AVAILABLE
        ticket.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Número #{number} disponible otra vez.")
    else:
        messages.warning(request, "Esa acción no corresponde al estado actual del número.")
    return _back(request, "mod-raffle-detail", pk)


@staff_required
@require_POST
def manual_sale(request, pk):
    raffle = get_object_or_404(Raffle, pk=pk)
    form = forms.ManualSaleForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Revisa el formulario de venta manual: " + "; ".join(sum(form.errors.values(), [])))
        return redirect("mod-raffle-detail", pk)
    d = form.cleaned_data
    try:
        numbers = svc.parse_numbers(d["numbers"], raffle.total_tickets)
        payment = svc.manual_sale(raffle=raffle, numbers=numbers, name=d["buyer_name"], phone=d["buyer_phone"],
                                  email=d["buyer_email"], notes=d["notes"], user=request.user)
    except svc.ModerationError as exc:
        messages.error(request, str(exc))
        return redirect("mod-raffle-detail", pk)
    messages.success(request, f"Venta manual registrada ({payment.reference_code}).")
    return redirect("mod-payment-detail", payment.pk)


@staff_required
def raffle_export(request, pk):
    """CSV con los números pagados (para el sorteo o para enviar al organizador)."""
    raffle = get_object_or_404(Raffle, pk=pk)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{raffle.slug}-vendidos.csv"'
    response.write("﻿")  # para que Excel respete las tildes
    writer = csv.writer(response)
    writer.writerow(["Número", "Estado", "Nombre", "Teléfono", "Correo", "Pagado el"])
    for t in raffle.tickets.exclude(status=Ticket.Status.AVAILABLE).order_by("number"):
        writer.writerow([t.number, t.get_status_display(), t.buyer_name, t.buyer_phone, t.buyer_email,
                         timezone.localtime(t.paid_at).strftime("%d-%m-%Y %H:%M") if t.paid_at else ""])
    return response


# ----------------------------------------------------------------------------- cuentas bancarias
@staff_required
def account_list(request):
    return render(request, "moderar/accounts.html", {
        "accounts": BankAccount.objects.prefetch_related("raffles"), "nav": "cuentas"})


@staff_required
def account_form(request, pk=None):
    account = get_object_or_404(BankAccount, pk=pk) if pk else None
    form = forms.BankAccountForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cuenta guardada.")
        return redirect("mod-accounts")
    return render(request, "moderar/account_form.html", {"form": form, "account": account, "nav": "cuentas"})


@staff_required
@require_POST
def account_action(request, pk):
    account = get_object_or_404(BankAccount, pk=pk)
    if request.POST.get("action") == "toggle":
        account.is_active = not account.is_active
        account.save(update_fields=["is_active"])
        messages.success(request, "Cuenta " + ("activada." if account.is_active else "ocultada."))
    elif request.POST.get("action") == "delete":
        account.delete()
        messages.success(request, "Cuenta eliminada.")
    return redirect("mod-accounts")


# ----------------------------------------------------------------------------- configuración
@staff_required
def site_config(request):
    config = SiteConfiguration.load()
    form = forms.SiteConfigForm(request.POST or None, instance=config)
    if request.method == "POST":
        if request.POST.get("action") == "test_email":
            if not config.admin_notification_email:
                messages.error(request, "Primero guarda un «Correo para avisos».")
            else:
                try:
                    send_mail("Prueba de Chile Raffle", "Si lees esto, el correo está bien configurado.",
                              settings.DEFAULT_FROM_EMAIL, [config.admin_notification_email])
                    messages.success(request, f"Correo de prueba enviado a {config.admin_notification_email}.")
                except Exception as exc:  # noqa: BLE001
                    messages.error(request, f"Falló el envío: {exc!r}")
            return redirect("mod-config")
        if form.is_valid():
            form.save()
            messages.success(request, "Configuración guardada.")
            return redirect("mod-config")
    return render(request, "moderar/config.html", {"form": form, "nav": "config"})


# ----------------------------------------------------------------------------- moderadores
@superuser_required
def user_list(request):
    return render(request, "moderar/users.html", {
        "users": User.objects.filter(is_staff=True).order_by("-is_superuser", "username"),
        "form": forms.ModeratorCreateForm(), "pw_form": forms.PasswordResetForm(), "nav": "usuarios"})


@superuser_required
@require_POST
def user_create(request):
    form = forms.ModeratorCreateForm(request.POST)
    if form.is_valid():
        user = form.save()
        messages.success(request, f"Moderador «{user.username}» creado. Ya puede entrar en /moderar/.")
    else:
        messages.error(request, "No se pudo crear: " + "; ".join(sum(form.errors.values(), [])))
    return redirect("mod-users")


@superuser_required
@require_POST
def user_action(request, pk):
    user = get_object_or_404(User, pk=pk, is_staff=True)
    if user.is_superuser and user != request.user:
        messages.error(request, "No se pueden modificar otros administradores principales desde aquí.")
    elif request.POST.get("action") == "toggle":
        if user == request.user:
            messages.error(request, "No puedes desactivarte a ti mismo.")
        else:
            user.is_active = not user.is_active
            user.save(update_fields=["is_active"])
            messages.success(request, f"{user.username}: " + ("activo." if user.is_active else "desactivado."))
    elif request.POST.get("action") == "password":
        form = forms.PasswordResetForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data["password"])
            user.save()
            messages.success(request, f"Contraseña de {user.username} actualizada.")
        else:
            messages.error(request, "La contraseña debe tener al menos 8 caracteres.")
    return redirect("mod-users")
