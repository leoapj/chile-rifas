"""Al crear una rifa se generan sus tickets 1..total_tickets automáticamente."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Raffle, Ticket


@receiver(post_save, sender=Raffle)
def create_tickets_for_new_raffle(sender, instance: Raffle, created: bool, **kwargs):
    if created and instance.total_tickets > 0 and not instance.tickets.exists():
        Ticket.objects.bulk_create(
            [Ticket(raffle=instance, number=n) for n in range(1, instance.total_tickets + 1)]
        )
