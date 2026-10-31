from django.apps import AppConfig


class RafflesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "raffles"
    verbose_name = "Rifas"

    def ready(self):
        from . import signals  # noqa: F401  (auto-genera los tickets de cada rifa nueva)
