"""
Modelos de la plataforma de rifas para Chile (precios en CLP, pago solo por
transferencia bancaria con confirmación manual desde el Admin).

Modelos:
    - SiteConfiguration: singleton con parámetros globales (tiempos, límites, contacto).
    - BankAccount: cuentas bancarias donde los compradores transfieren.
    - Raffle: una rifa, con precio por número en CLP.
    - Ticket: cada número de una rifa y su estado.
    - Payment: una compra (uno o varios tickets) y su comprobante de transferencia.

Flujo de un pago:
    PENDING --(admin confirma)--> COMPLETED   (tickets -> PAID)
    PENDING --(admin rechaza)---> FAILED      (tickets liberados)
    PENDING --(se vence plazo)--> EXPIRED     (tickets liberados)
    EXPIRED --(admin confirma, si los tickets siguen libres)--> COMPLETED
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from .services import notifications


class PaymentStateError(Exception):
    """Se intentó una transición de estado que no corresponde (o los tickets ya no están disponibles)."""


class SiteConfiguration(models.Model):
    """Configuración global del sitio (singleton: siempre pk=1), editable en el Admin."""

    ticket_reservation_minutes = models.PositiveIntegerField(
        default=30,
        verbose_name="Minutos para transferir",
        help_text="Tiempo que los números quedan reservados mientras el comprador hace la transferencia.",
    )
    proof_review_hours = models.PositiveIntegerField(
        default=24,
        verbose_name="Horas para revisar el comprobante",
        help_text="Cuando el comprador envía su comprobante, los números quedan reservados este tiempo extra para que tú verifiques la transferencia.",
    )
    max_tickets_per_purchase = models.PositiveIntegerField(
        default=20,
        verbose_name="Máximo de números por compra",
        help_text="Evita que una sola persona (o un script) reserve toda la rifa.",
    )
    contact_whatsapp = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="WhatsApp de contacto",
        help_text="Solo dígitos con código de país, ej. 56912345678. Se muestra en la página de pago.",
    )
    promo_whatsapp = models.CharField(
        max_length=20,
        default="56957066093",
        blank=True,
        verbose_name="WhatsApp para publicar rifas",
        help_text="Solo dígitos con código de país. Aparece en la portada en 'Publica tu rifa aquí'. Si lo dejas vacío, la sección se oculta.",
    )
    admin_notification_email = models.EmailField(
        blank=True,
        verbose_name="Correo para avisos",
        help_text="Aquí te llega un aviso cuando un comprador envía su comprobante (para que valides) y cuando una rifa se llena. Cámbialo cuando quieras.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración del sitio"
        verbose_name_plural = "Configuración del sitio"

    def __str__(self):
        return "Configuración del sitio"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """La configuración única no se puede borrar."""

    @property
    def promo_whatsapp_display(self) -> str:
        """56957066093 -> +56 9 5706 6093 (formato celular chileno)."""
        n = self.promo_whatsapp
        if len(n) == 11 and n.startswith("56"):
            return f"+56 {n[2]} {n[3:7]} {n[7:]}"
        return f"+{n}" if n else ""

    @classmethod
    def load(cls) -> "SiteConfiguration":
        obj, _ = cls.objects.get_or_create(
            pk=1, defaults={"ticket_reservation_minutes": settings.TICKET_RESERVATION_MINUTES}
        )
        return obj


class BankAccount(models.Model):
    """Cuenta bancaria chilena a la que el comprador debe transferir."""

    class AccountType(models.TextChoices):
        CORRIENTE = "corriente", "Cuenta corriente"
        VISTA = "vista", "Cuenta vista / Chequera electrónica"
        RUT = "rut", "Cuenta RUT"
        AHORRO = "ahorro", "Cuenta de ahorro"

    bank_name = models.CharField(max_length=80, verbose_name="Banco", help_text="Ej. Banco Estado, Banco de Chile, Santander…")
    account_type = models.CharField(max_length=20, choices=AccountType.choices, verbose_name="Tipo de cuenta")
    account_number = models.CharField(max_length=30, verbose_name="Número de cuenta")
    holder_name = models.CharField(max_length=120, verbose_name="Titular")
    holder_rut = models.CharField(max_length=15, verbose_name="RUT del titular", help_text="Ej. 12.345.678-9")
    notification_email = models.EmailField(
        blank=True,
        verbose_name="Correo para avisos de transferencia",
        help_text="Es el correo que el comprador debe poner en el campo 'email' de su transferencia.",
    )
    is_active = models.BooleanField(default=True, verbose_name="Visible para los compradores")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "bank_name"]
        verbose_name = "Cuenta bancaria"
        verbose_name_plural = "Cuentas bancarias"

    def __str__(self):
        return f"{self.bank_name} · {self.get_account_type_display()} · {self.account_number}"


class Raffle(models.Model):
    """Una rifa. El precio por número se define directamente en pesos chilenos (CLP)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        ACTIVE = "active", "Activa"
        FINISHED = "finished", "Finalizada"
        CANCELLED = "cancelled", "Cancelada"

    name = models.CharField(max_length=150, verbose_name="Nombre del premio")
    slug = models.SlugField(max_length=170, unique=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="raffles/", blank=True, null=True)

    organizer_name = models.CharField(
        max_length=100, blank=True, verbose_name="Organizador",
        help_text="Si la rifa es de otra persona, escribe su nombre: se muestra como «Organiza: …». Vacío = rifa tuya.",
    )
    bank_accounts = models.ManyToManyField(
        "BankAccount", blank=True, related_name="raffles", verbose_name="Cuentas para transferir",
        help_text="Cuentas donde los compradores transfieren el dinero de ESTA rifa. Si no eliges ninguna, se muestran tus cuentas generales.",
    )

    price_clp = models.PositiveIntegerField(
        verbose_name="Precio por número (CLP)", help_text="En pesos chilenos, sin decimales. Ej. 2000."
    )
    total_tickets = models.PositiveIntegerField(verbose_name="Cantidad total de números")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    half_sold_notified_at = models.DateTimeField(
        null=True, blank=True, editable=False, help_text="Cuándo se avisó por correo que se vendió el 50%."
    )
    draw_date = models.DateTimeField(verbose_name="Fecha del sorteo")
    winner_ticket = models.OneToOneField(
        "Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="won_raffle"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Rifa"
        verbose_name_plural = "Rifas"

    def __str__(self):
        return f"{self.name} (${self.price_clp:,} CLP)".replace(",", ".")

    def payment_accounts(self):
        """Cuentas que ve el comprador: las de esta rifa; si no tiene, las cuentas generales (no ligadas a ninguna rifa)."""
        own = self.bank_accounts.filter(is_active=True)
        if own.exists():
            return own
        return BankAccount.objects.filter(is_active=True, raffles__isnull=True)

    def tickets_sold_count(self) -> int:
        return self.tickets.filter(status=Ticket.Status.PAID).count()

    def tickets_available_count(self) -> int:
        return self.tickets.filter(status=Ticket.Status.AVAILABLE).count()

    def days_until_draw(self) -> int:
        return max((self.draw_date - timezone.now()).days, 0)

    def is_almost_sold_out(self) -> bool:
        """Quedan pocos números (20% o menos), pero aún hay."""
        available = self.tickets_available_count()
        return 0 < available <= self.total_tickets * 0.2

    def percent_sold(self) -> int:
        if not self.total_tickets:
            return 0
        return round(self.tickets_sold_count() / self.total_tickets * 100)


class Ticket(models.Model):
    """Un número de una rifa. Las transiciones de estado se protegen con select_for_update()."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        RESERVED = "reserved", "Reservado"
        PAID = "paid", "Pagado"
        CANCELLED = "cancelled", "Cancelado"

    raffle = models.ForeignKey(Raffle, on_delete=models.CASCADE, related_name="tickets")
    number = models.PositiveIntegerField(verbose_name="Número")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE, db_index=True)

    buyer_name = models.CharField(max_length=150, blank=True)
    buyer_phone = models.CharField(max_length=30, blank=True)
    buyer_email = models.EmailField(blank=True)

    reserved_at = models.DateTimeField(null=True, blank=True)
    reserved_until = models.DateTimeField(null=True, blank=True, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("raffle", "number")
        ordering = ["raffle", "number"]
        verbose_name = "Número"
        verbose_name_plural = "Números"
        indexes = [models.Index(fields=["status", "reserved_until"])]

    def __str__(self):
        return f"#{self.number} - {self.raffle.name} ({self.get_status_display()})"

    def mark_reserved(self, buyer_name: str, buyer_phone: str, buyer_email: str, until):
        self.status = self.Status.RESERVED
        self.buyer_name = buyer_name
        self.buyer_phone = buyer_phone
        self.buyer_email = buyer_email
        self.reserved_at = timezone.now()
        self.reserved_until = until
        self.save()

    def mark_paid(self, payment: "Payment"):
        """Pasa a PAGADO y deja los datos del comprador (por si el ticket había sido liberado antes)."""
        self.status = self.Status.PAID
        self.buyer_name = payment.buyer_name
        self.buyer_phone = payment.buyer_phone
        self.buyer_email = payment.buyer_email
        self.paid_at = timezone.now()
        self.save()

    def release(self):
        """Vuelve a DISPONIBLE y borra los datos del comprador."""
        self.status = self.Status.AVAILABLE
        self.buyer_name = ""
        self.buyer_phone = ""
        self.buyer_email = ""
        self.reserved_at = None
        self.reserved_until = None
        self.save()


class Payment(models.Model):
    """
    Una compra: uno o varios números de la misma rifa, pagados con UNA transferencia.

    `reference_code` (ej. RIFA-00042) se le muestra al comprador para que lo
    escriba en el comentario de su transferencia; así puedes cruzar cada abono
    de tu cartola con su compra.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        COMPLETED = "completed", "Pagado"
        FAILED = "failed", "Rechazado"
        EXPIRED = "expired", "Expirado"

    # UUID público: se usa en las URLs para que nadie pueda adivinar pagos ajenos.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    raffle = models.ForeignKey(Raffle, on_delete=models.CASCADE, related_name="payments")
    tickets = models.ManyToManyField(Ticket, related_name="payments")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    amount = models.PositiveIntegerField(verbose_name="Monto a transferir (CLP)")

    buyer_name = models.CharField(max_length=150, verbose_name="Nombre")
    buyer_phone = models.CharField(max_length=30, verbose_name="Teléfono")
    buyer_email = models.EmailField(blank=True, verbose_name="Correo")

    buyer_reference = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="N° de operación (informado por el comprador)",
        help_text="Número de operación/comprobante que le entregó su banco.",
    )
    proof_submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="Comprobante enviado")
    admin_notes = models.TextField(blank=True, verbose_name="Notas internas")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_payments"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self):
        return f"{self.reference_code} · ${self.amount:,} CLP · {self.get_status_display()}".replace(",", ".")

    @property
    def reference_code(self) -> str:
        return f"RIFA-{self.pk:05d}"

    @property
    def has_proof(self) -> bool:
        return self.proof_submitted_at is not None

    # ------------------------------------------------------------------
    # Transiciones de estado (todas atómicas y con bloqueo de filas)
    # ------------------------------------------------------------------
    def _ticket_held_by_other_payment(self, ticket: Ticket) -> bool:
        """True si OTRA compra vigente tiene hoy este número reservado."""
        return (
            Payment.objects.filter(tickets=ticket, status=self.Status.PENDING, expires_at__gt=timezone.now())
            .exclude(pk=self.pk)
            .exists()
        )

    def submit_proof(self, buyer_reference: str) -> None:
        """
        El comprador informa su N° de operación. Si es la primera vez, se
        extiende la reserva `proof_review_hours` para que puedas verificar la
        transferencia sin que los números se liberen mientras tanto.
        """
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=self.pk)
            if payment.status != self.Status.PENDING or payment.expires_at <= timezone.now():
                raise PaymentStateError("La reserva ya venció. Si ya transferiste, escríbenos por WhatsApp.")

            first_time = payment.proof_submitted_at is None
            payment.buyer_reference = buyer_reference
            payment.proof_submitted_at = timezone.now()
            if first_time:
                hours = SiteConfiguration.load().proof_review_hours
                new_expiry = timezone.now() + timedelta(hours=hours)
                payment.expires_at = new_expiry
                payment.tickets.update(reserved_until=new_expiry)
            payment.save()
            transaction.on_commit(lambda: notifications.notify_proof_submitted(payment.pk))
        self.refresh_from_db()

    def mark_completed(self, verified_by=None) -> None:
        """
        Confirma la transferencia: el pago pasa a PAGADO y los números a PAGADOS.

        También sirve para pagos EXPIRADOS (el comprador transfirió tarde), pero
        solo si cada número sigue libre o reservado por este mismo pago. Si otra
        persona ya lo tomó, lanza PaymentStateError para que lo resuelvas a mano
        (devolución o cambio de número).
        """
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=self.pk)
            if payment.status == self.Status.COMPLETED:
                return
            if payment.status not in (self.Status.PENDING, self.Status.EXPIRED):
                raise PaymentStateError(f"{payment.reference_code} está {payment.get_status_display().lower()} y no puede confirmarse.")

            tickets = list(payment.tickets.select_for_update().order_by("number"))
            blocked = [
                t.number
                for t in tickets
                if t.status in (Ticket.Status.PAID, Ticket.Status.CANCELLED)
                or (t.status == Ticket.Status.RESERVED and payment._ticket_held_by_other_payment(t))
            ]
            if blocked:
                raise PaymentStateError(
                    f"{payment.reference_code}: los números {blocked} ya no están disponibles (los tomó otra compra). Resuélvelo manualmente."
                )

            for ticket in tickets:
                ticket.mark_paid(payment)
            payment.status = self.Status.COMPLETED
            payment.verified_by = verified_by
            payment.verified_at = timezone.now()
            payment.save()
            transaction.on_commit(lambda: notifications.notify_buyer_payment_result(payment.pk))
            transaction.on_commit(lambda: notifications.notify_raffle_progress(payment.raffle_id))
        self.refresh_from_db()

    def mark_failed(self, verified_by=None) -> None:
        """Rechaza el pago (ej. la transferencia nunca llegó) y libera sus números."""
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=self.pk)
            if payment.status == self.Status.COMPLETED:
                raise PaymentStateError(f"{payment.reference_code} ya está pagado; no se puede rechazar.")

            for ticket in payment.tickets.select_for_update().order_by("number"):
                if ticket.status == Ticket.Status.RESERVED and not payment._ticket_held_by_other_payment(ticket):
                    ticket.release()
            payment.status = self.Status.FAILED
            payment.verified_by = verified_by
            payment.verified_at = timezone.now()
            payment.save()
            transaction.on_commit(lambda: notifications.notify_buyer_payment_result(payment.pk))
        self.refresh_from_db()
