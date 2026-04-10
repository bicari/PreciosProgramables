from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging

logger = logging.getLogger(__name__)


def notificar_nuevo_pedido(pedido):
    try:
        html_str = render_to_string('pedido-mail.html', context={
            'titulo': 'Nuevo Pedido de Tienda',
            'mensaje': f'Se ha creado el pedido #{pedido.numero_pedido} por {pedido.solicitante.username}.',
            'pedido': pedido,
            'items': pedido.items.all(),
        })
        text_content = strip_tags(html_str)
        destinatarios = getattr(settings, 'EMAIL_ALMACEN', settings.EMAIL_USERS)
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
    try:
        html_str = render_to_string('pedido-mail.html', context={
            'titulo': 'Pedido Despachado',
            'mensaje': f'El pedido #{pedido.numero_pedido} ha sido despachado por {pedido.despachador.username}.',
            'pedido': pedido,
            'items': pedido.items.all(),
        })
        text_content = strip_tags(html_str)
        send_mail(
            subject=f'Pedido #{pedido.numero_pedido} Despachado',
            message=text_content,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[pedido.solicitante.username],
            html_message=html_str,
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f'Error al notificar despacho pedido #{pedido.numero_pedido}: {e}')


def notificar_recepcion(pedido):
    try:
        html_str = render_to_string('pedido-mail.html', context={
            'titulo': 'Pedido Recibido',
            'mensaje': f'El pedido #{pedido.numero_pedido} ha sido recibido por {pedido.solicitante.username}.',
            'pedido': pedido,
            'items': pedido.items.all(),
        })
        text_content = strip_tags(html_str)
        destinatarios = getattr(settings, 'EMAIL_ALMACEN', settings.EMAIL_USERS)
        send_mail(
            subject=f'Pedido #{pedido.numero_pedido} Recibido',
            message=text_content,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=destinatarios,
            html_message=html_str,
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f'Error al notificar recepcion pedido #{pedido.numero_pedido}: {e}')
