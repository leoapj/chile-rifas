"""Serializers DRF: validación de entrada y representación de rifas y pagos."""

import re

from django.utils import timezone
from rest_framework import serializers

from .models import Payment, Raffle

# Celulares chilenos: +56 9 XXXX XXXX (también acepta 9XXXXXXXX o 569XXXXXXXX).
_CL_MOBILE = re.compile(r"^(?:\+?56)?9\d{8}$")


class RaffleSerializer(serializers.ModelSerializer):
    tickets_available = serializers.IntegerField(source="tickets_available_count", read_only=True)
    tickets_sold = serializers.IntegerField(source="tickets_sold_count", read_only=True)

    class Meta:
        model = Raffle
        fields = [
            "id", "name", "slug", "description", "image", "price_clp", "total_tickets",
            "tickets_available", "tickets_sold", "status", "draw_date",
        ]


class ReserveTicketsInputSerializer(serializers.Serializer):
    raffle_id = serializers.IntegerField()
    ticket_numbers = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)
    buyer_name = serializers.CharField(max_length=150)
    buyer_phone = serializers.CharField(max_length=30)
    buyer_email = serializers.EmailField(required=False, allow_blank=True)

    def validate_buyer_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Ingresa tu nombre completo.")
        return value

    def validate_buyer_phone(self, value: str) -> str:
        digits = re.sub(r"[\s\-().]", "", value)
        if not _CL_MOBILE.match(digits):
            raise serializers.ValidationError("Ingresa un celular chileno válido, ej. +56 9 1234 5678.")
        return "+56" + digits[-9:]


class SubmitProofInputSerializer(serializers.Serializer):
    buyer_reference = serializers.CharField(max_length=100)

    def validate_buyer_reference(self, value: str) -> str:
        value = value.strip()
        if len(value) < 4:
            raise serializers.ValidationError("Ingresa el N° de operación completo que aparece en tu comprobante.")
        return value


class PaymentSerializer(serializers.ModelSerializer):
    """No expone el id numérico ni datos personales del comprador."""

    reference_code = serializers.CharField(read_only=True)
    status = serializers.SerializerMethodField()
    ticket_numbers = serializers.SerializerMethodField()
    requires_proof = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "public_id", "reference_code", "status", "amount", "ticket_numbers",
            "buyer_reference", "proof_submitted_at", "requires_proof", "expires_at",
        ]
        read_only_fields = fields

    def get_status(self, obj: Payment) -> str:
        """Un pago pendiente cuyo plazo ya pasó se informa como 'expired' sin esperar a la limpieza."""
        if obj.status == Payment.Status.PENDING and obj.expires_at <= timezone.now():
            return Payment.Status.EXPIRED
        return obj.status

    def get_ticket_numbers(self, obj: Payment):
        return sorted(t.number for t in obj.tickets.all())

    def get_requires_proof(self, obj: Payment) -> bool:
        return self.get_status(obj) == Payment.Status.PENDING and not obj.has_proof
