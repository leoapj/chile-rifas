"""
API JSON de la plataforma.

    GET  /api/raffles/                       rifas activas
    GET  /api/raffles/<slug>/                detalle + estado de cada número
    POST /api/payments/reserve/              reserva números y crea el pago pendiente
    POST /api/payments/<uuid>/submit-proof/  el comprador informa su N° de operación
    GET  /api/payments/<uuid>/status/        estado del pago (polling de la página)

La confirmación del pago NO ocurre aquí: la hace una persona desde el Admin
después de ver el abono en la cartola del banco.
"""

import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Payment, PaymentStateError, Raffle, SiteConfiguration, Ticket
from .serializers import (
    PaymentSerializer,
    RaffleSerializer,
    ReserveTicketsInputSerializer,
    SubmitProofInputSerializer,
)
from .services.reservations import release_expired_reservations

logger = logging.getLogger(__name__)


class TicketsUnavailableError(Exception):
    """Uno o más números pedidos no existen o ya no están disponibles."""


@api_view(["GET"])
@permission_classes([AllowAny])
def list_active_raffles(request):
    raffles = Raffle.objects.filter(status=Raffle.Status.ACTIVE)
    return Response(RaffleSerializer(raffles, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def raffle_detail(request, slug):
    raffle = get_object_or_404(Raffle, slug=slug)
    data = RaffleSerializer(raffle).data
    data["tickets"] = list(raffle.tickets.values("number", "status"))
    return Response(data)


class ReserveTicketsView(APIView):
    """
    POST /api/payments/reserve/

        {"raffle_id": 1, "ticket_numbers": [12, 13], "buyer_name": "...",
         "buyer_phone": "+56912345678", "buyer_email": "opcional@correo.cl"}

    Dentro de UNA transacción: libera reservas vencidas, bloquea los números
    pedidos con select_for_update() (dos compradores nunca pueden obtener el
    mismo número), los reserva y crea el Payment con el monto en CLP.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "reserve"

    def post(self, request):
        serializer = ReserveTicketsInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        config = SiteConfiguration.load()
        numbers = set(data["ticket_numbers"])
        if len(numbers) > config.max_tickets_per_purchase:
            return Response(
                {"detail": f"Puedes comprar hasta {config.max_tickets_per_purchase} números por vez."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raffle = get_object_or_404(Raffle, pk=data["raffle_id"], status=Raffle.Status.ACTIVE)

        try:
            payment = self._reserve(
                raffle=raffle,
                numbers=numbers,
                config=config,
                buyer_name=data["buyer_name"],
                buyer_phone=data["buyer_phone"],
                buyer_email=data.get("buyer_email", ""),
            )
        except TicketsUnavailableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def _reserve(self, *, raffle, numbers, config, buyer_name, buyer_phone, buyer_email) -> Payment:
        # 1) Libera reservas vencidas para que sus números vuelvan a estar disponibles.
        release_expired_reservations()

        # 2) Bloquea las filas pedidas (orden fijo por número: evita deadlocks).
        tickets = list(
            Ticket.objects.select_for_update().filter(raffle=raffle, number__in=numbers).order_by("number")
        )
        missing = numbers - {t.number for t in tickets}
        if missing:
            raise TicketsUnavailableError(f"Los números {sorted(missing)} no existen en esta rifa.")

        taken = [t.number for t in tickets if t.status != Ticket.Status.AVAILABLE]
        if taken:
            raise TicketsUnavailableError(f"Los números {taken} ya no están disponibles. Elige otros.")

        # 3) Reserva y crea el pago (monto en CLP, calculado en el servidor).
        expires_at = timezone.now() + timedelta(minutes=config.ticket_reservation_minutes)
        for ticket in tickets:
            ticket.mark_reserved(buyer_name, buyer_phone, buyer_email, until=expires_at)

        payment = Payment.objects.create(
            raffle=raffle,
            amount=raffle.price_clp * len(tickets),
            buyer_name=buyer_name,
            buyer_phone=buyer_phone,
            buyer_email=buyer_email,
            expires_at=expires_at,
        )
        payment.tickets.set(tickets)
        return payment


class SubmitPaymentProofView(APIView):
    """POST /api/payments/<uuid>/submit-proof/  {"buyer_reference": "N° de operación"}"""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "proof"

    def post(self, request, public_id):
        payment = get_object_or_404(Payment, public_id=public_id)

        serializer = SubmitProofInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payment.submit_proof(serializer.validated_data["buyer_reference"])
        except PaymentStateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response(PaymentSerializer(payment).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def payment_status(request, public_id):
    """Estado ligero del pago, consultado cada pocos segundos. Solo lee: no toma bloqueos."""
    payment = get_object_or_404(Payment, public_id=public_id)
    return Response(PaymentSerializer(payment).data)
