"""Django Admin: aquí confirmas las transferencias y administras rifas y cuentas bancarias."""

from django.contrib import admin, messages

from .models import BankAccount, Payment, PaymentStateError, Raffle, SiteConfiguration, Ticket


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    list_display = ("__str__", "admin_notification_email", "ticket_reservation_minutes", "proof_review_hours", "max_tickets_per_purchase")

    actions = ["send_test_email"]

    def has_add_permission(self, request):
        return not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="📧 Enviar correo de prueba a «Correo para avisos»")
    def send_test_email(self, request, queryset):
        """Prueba el correo desde el propio Admin (en Render gratis no hay terminal). Muestra el error real si falla."""
        from django.conf import settings
        from django.core.mail import send_mail

        config = queryset.first()
        if not config or not config.admin_notification_email:
            self.message_user(request, "Primero escribe un «Correo para avisos» y guarda.", level=messages.ERROR)
            return
        backend = settings.EMAIL_BACKEND.rsplit(".", 2)[-2]
        try:
            send_mail("Prueba de Chile Raffle", "Si lees esto, el correo está bien configurado.",
                      settings.DEFAULT_FROM_EMAIL, [config.admin_notification_email])
        except Exception as exc:  # noqa: BLE001
            self.message_user(request, f"Falló el envío ({backend}): {exc!r}", level=messages.ERROR)
            return
        if backend == "console":
            self.message_user(request, "El correo NO salió: el servidor no tiene un backend de correo real. Revisa tu settings.", level=messages.WARNING)
        else:
            self.message_user(request, f"Enviado a {config.admin_notification_email} ({backend}). Revisa tu bandeja y spam.")


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("bank_name", "account_type", "account_number", "holder_name", "rifas", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")

    @admin.display(description="Rifas que la usan")
    def rifas(self, obj):
        names = ", ".join(r.name for r in obj.raffles.all()[:3])
        return names or "General (todas las rifas sin cuenta propia)"


@admin.register(Raffle)
class RaffleAdmin(admin.ModelAdmin):
    list_display = ("name", "organizer_name", "price_clp", "status", "total_tickets", "tickets_sold_count", "draw_date")
    list_filter = ("status",)
    filter_horizontal = ("bank_accounts",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")
    actions = ["generate_missing_tickets"]

    @admin.action(description="Generar números faltantes")
    def generate_missing_tickets(self, request, queryset):
        created = 0
        for raffle in queryset:
            if not raffle.tickets.exists() and raffle.total_tickets > 0:
                Ticket.objects.bulk_create([Ticket(raffle=raffle, number=n) for n in range(1, raffle.total_tickets + 1)])
                created += raffle.total_tickets
        self.message_user(request, f"{created} número(s) generado(s).")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("raffle", "number", "status", "buyer_name", "buyer_phone", "reserved_until")
    list_filter = ("status", "raffle")
    search_fields = ("buyer_name", "buyer_phone", "buyer_email", "number")
    readonly_fields = ("created_at", "updated_at", "reserved_at", "paid_at")


class ProofFilter(admin.SimpleListFilter):
    title = "comprobante"
    parameter_name = "proof"

    def lookups(self, request, model_admin):
        return [("yes", "Con comprobante (por revisar)"), ("no", "Sin comprobante")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(proof_submitted_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(proof_submitted_at__isnull=True)
        return queryset


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Flujo diario: filtra "Pendiente" + "Con comprobante", busca el abono en tu
    cartola por monto y por el código RIFA-xxxxx del comentario, y ejecuta
    "Confirmar transferencia recibida".
    """

    list_display = (
        "reference_code", "raffle", "amount", "buyer_name", "buyer_phone",
        "status", "buyer_reference", "proof_submitted_at", "expires_at",
    )
    list_filter = ("status", ProofFilter, "raffle")
    search_fields = ("buyer_name", "buyer_phone", "buyer_email", "buyer_reference")
    readonly_fields = (
        "public_id", "raffle", "tickets", "amount", "buyer_name", "buyer_phone", "buyer_email",
        "buyer_reference", "proof_submitted_at", "verified_by", "verified_at", "created_at", "updated_at", "expires_at",
    )
    actions = ["confirm_payments", "reject_payments"]

    @admin.display(description="Código")
    def reference_code(self, obj):
        return obj.reference_code

    def has_add_permission(self, request):
        return False

    def _apply(self, request, queryset, method_name: str, ok_text: str):
        done = 0
        for payment in queryset:
            try:
                getattr(payment, method_name)(verified_by=request.user)
                done += 1
            except PaymentStateError as exc:
                self.message_user(request, str(exc), level=messages.WARNING)
        if done:
            self.message_user(request, f"{done} pago(s) {ok_text}.")

    @admin.action(description="✅ Confirmar transferencia recibida (marca los números como pagados)")
    def confirm_payments(self, request, queryset):
        self._apply(request, queryset, "mark_completed", "confirmado(s)")

    @admin.action(description="❌ Rechazar pago (libera los números)")
    def reject_payments(self, request, queryset):
        self._apply(request, queryset, "mark_failed", "rechazado(s)")
