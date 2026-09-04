from django import template
from django.utils.html import format_html

from ..models import Condicion

register = template.Library()

# bg-info y bg-warning son fondos claros de Bootstrap; necesitan texto oscuro para contraste.
_COLORES_CLAROS = {'info', 'warning'}


@register.simple_tag
def condicion_badge(codigo):
    """Badge Bootstrap para una condición de pedido, con color/ícono desde el catálogo."""
    if not codigo:
        return format_html('<span class="text-muted">—</span>')

    condicion = Condicion.objects.filter(codigo=codigo).first()
    if condicion is None:
        return format_html('<span class="badge bg-secondary">{}</span>', codigo)

    icono_html = ''
    if condicion.icono:
        icono_html = format_html('<i class="fas {} me-1"></i>', condicion.icono)

    clase_contraste = ' text-dark' if condicion.color_badge in _COLORES_CLAROS else ''

    return format_html(
        '<span class="badge bg-{}{}">{}{}</span>',
        condicion.color_badge, clase_contraste, icono_html, condicion.nombre,
    )


@register.filter
def condicion_nombre(codigo):
    """Nombre catalogado de una condición; cae al código si no está en el catálogo."""
    if not codigo:
        return ''
    condicion = Condicion.objects.filter(codigo=codigo).first()
    return condicion.nombre if condicion else codigo


@register.filter
def condicion_color(codigo):
    """Color Bootstrap catalogado de una condición (para usos fuera del badge, ej. texto)."""
    if not codigo:
        return ''
    condicion = Condicion.objects.filter(codigo=codigo).first()
    return condicion.color_badge if condicion else 'secondary'
