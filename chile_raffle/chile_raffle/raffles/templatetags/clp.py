"""Filtro de plantilla para pesos chilenos: {{ 12500|clp }} -> 12.500"""

from django import template

register = template.Library()


@register.filter
def clp(value) -> str:
    """Formatea un entero con punto como separador de miles (formato chileno)."""
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return ""
