"""Rutas de la API."""

from django.urls import path

from . import views

urlpatterns = [
    path("raffles/", views.list_active_raffles, name="raffle-list"),
    path("raffles/<slug:slug>/", views.raffle_detail, name="raffle-detail"),
    path("payments/reserve/", views.ReserveTicketsView.as_view(), name="payment-reserve"),
    path("payments/<uuid:public_id>/status/", views.payment_status, name="payment-status-api"),
    path("payments/<uuid:public_id>/submit-proof/", views.SubmitPaymentProofView.as_view(), name="payment-submit-proof"),
]
