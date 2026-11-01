"""Rutas del panel de moderación (/moderar/...)."""

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import mod_views as v

urlpatterns = [
    path("login/", v.ModLoginView.as_view(), name="mod-login"),
    path("salir/", LogoutView.as_view(), name="mod-logout"),
    path("", v.dashboard, name="mod-dashboard"),
    path("liberar-vencidas/", v.release_expired, name="mod-release-expired"),
    # pagos
    path("pagos/", v.payment_list, name="mod-payments"),
    path("pagos/masivo/", v.payment_bulk, name="mod-payment-bulk"),
    path("pagos/<int:pk>/", v.payment_detail, name="mod-payment-detail"),
    path("pagos/<int:pk>/accion/", v.payment_action, name="mod-payment-action"),
    # rifas
    path("rifas/", v.raffle_list, name="mod-raffles"),
    path("rifas/nueva/", v.raffle_form, name="mod-raffle-new"),
    path("rifas/<int:pk>/", v.raffle_detail, name="mod-raffle-detail"),
    path("rifas/<int:pk>/editar/", v.raffle_form, name="mod-raffle-edit"),
    path("rifas/<int:pk>/accion/", v.raffle_action, name="mod-raffle-action"),
    path("rifas/<int:pk>/venta-manual/", v.manual_sale, name="mod-manual-sale"),
    path("rifas/<int:pk>/exportar.csv", v.raffle_export, name="mod-raffle-export"),
    path("rifas/<int:pk>/numero/<int:number>/", v.ticket_action, name="mod-ticket-action"),
    # cuentas, configuración, moderadores
    path("cuentas/", v.account_list, name="mod-accounts"),
    path("cuentas/nueva/", v.account_form, name="mod-account-new"),
    path("cuentas/<int:pk>/editar/", v.account_form, name="mod-account-edit"),
    path("cuentas/<int:pk>/accion/", v.account_action, name="mod-account-action"),
    path("configuracion/", v.site_config, name="mod-config"),
    path("moderadores/", v.user_list, name="mod-users"),
    path("moderadores/nuevo/", v.user_create, name="mod-user-new"),
    path("moderadores/<int:pk>/accion/", v.user_action, name="mod-user-action"),
]
