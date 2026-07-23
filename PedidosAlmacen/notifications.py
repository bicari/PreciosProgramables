from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth import get_user_model
import logging

logger = logging.getLogger(__name__)

_GROUP_TIENDA = 'Pedidos Tienda'
_GROUP_ALMACEN = 'Pedidos Almacen'
_GROUP_SUPERVISOR = 'Pedidos Supervisor'


def _emails_por_grupos(*nombres_grupo):
    """Correos distintos (no vacíos) de usuarios activos en los grupos dados.

    Cae a settings.EMAIL_USERS si ningún usuario del rol tiene correo configurado.
    """
    User = get_user_model()
    emails = (
        User.objects
        .filter(groups__name__in=nombres_grupo, status=True)
        .exclude(email='')
        .values_list('email', flat=True)
        .distinct()
    )
    limpios = [e.strip() for e in emails if e and e.strip()]
    # dict.fromkeys preserva el orden y elimina duplicados
    result = list(dict.fromkeys(limpios))
    if not result:
        logger.warning(
            f'Sin correos configurados para grupos {nombres_grupo}; usando EMAIL_USERS como fallback.'
        )
        return list(settings.EMAIL_USERS)
    return result


def notificar_nuevo_pedido(pedido):
    if not settings.PEDIDOS_ENVIAR_CORREOS:
        logger.info(f'Correos de pedidos desactivados; se omite notificación del pedido #{pedido.numero_pedido}')
        return
    try:
        html_str = render_to_string('pedido-mail.html', context={
            'titulo': 'Nuevo Pedido de Tienda',
            'mensaje': f'Se ha creado el pedido #{pedido.numero_pedido} por {pedido.solicitante.username}.',
            'pedido': pedido,
            'items': pedido.items.all(),
        })
        text_content = strip_tags(html_str)
        destinatarios = _emails_por_grupos(_GROUP_ALMACEN, _GROUP_SUPERVISOR)
        send_mail(
            subject=f'Nuevo Pedido #{pedido.numero_pedido}',
            message=text_content,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=destinatarios,
            html_message=html_str,
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f'Error al notificar nuevo pedido #{pedido.numero_pedido}: {e}')


def notificar_despacho(pedido):
    if not settings.PEDIDOS_ENVIAR_CORREOS:
        logger.info(f'Correos de pedidos desactivados; se omite notificación del pedido #{pedido.numero_pedido}')
        return
    try:
        html_str = render_to_string('pedido-mail.html', context={
            'titulo': 'Pedido Despachado',
            'mensaje': f'El pedido #{pedido.numero_pedido} ha sido despachado por {pedido.despachador.username}.',
            'pedido': pedido,
            'items': pedido.items.all(),
            'solo_items': True,
        })
        text_content = strip_tags(html_str)
        send_mail(
            subject=f'Pedido #{pedido.numero_pedido} Despachado',
            message=text_content,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=_emails_por_grupos(_GROUP_TIENDA),
            html_message=html_str,
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f'Error al notificar despacho pedido #{pedido.numero_pedido}: {e}')


def notificar_despacho_parcial(pedido):
    if not settings.PEDIDOS_ENVIAR_CORREOS:
        logger.info(f'Correos de pedidos desactivados; se omite notificación del pedido #{pedido.numero_pedido}')
        return
    try:
        items_despachados = pedido.items.filter(estado='DESPACHADO')
        items_back_order = pedido.items.filter(estado='BACK_ORDER')
        html_str = render_to_string('pedido-mail.html', context={
            'titulo': 'Despacho Parcial de Pedido',
            'mensaje': (
                f'El pedido #{pedido.numero_pedido} ha sido despachado parcialmente por {pedido.despachador.username}. '
                f'Hay {items_back_order.count()} item(s) en Back Order pendientes de envío.'
            ),
            'pedido': pedido,
            'items': items_despachados,
            'solo_items': True,
        })
        text_content = strip_tags(html_str)
        send_mail(
            subject=f'Pedido #{pedido.numero_pedido} Despachado Parcialmente',
            message=text_content,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=_emails_por_grupos(_GROUP_TIENDA),
            html_message=html_str,
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f'Error al notificar despacho parcial pedido #{pedido.numero_pedido}: {e}')
