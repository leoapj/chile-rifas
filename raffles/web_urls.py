"""Rutas de las páginas HTML."""

from django.urls import path

from . import web_views

urlpatterns = [
    path("healthz/", web_views.healthz, name="healthz"),
    path("", web_views.home, name="home"),
    path("rifa/<slug:slug>/", web_views.raffle_detail_page, name="raffle-detail-page"),
    path("pago/<uuid:public_id>/", web_views.payment_status_page, name="payment-status-page"),
]
