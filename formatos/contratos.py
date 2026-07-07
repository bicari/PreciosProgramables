"""Contrato de datos para las plantillas ReportBro.

El código define aquí qué datos puede usar cada plantilla; el diseñador solo
los consume. Estas funciones son la única fuente de datos tanto para la
generación real como para el preview.
"""
from django.utils import timezone


def _fmt_fecha(valor) -> str:
    if not valor:
        return ''
    if timezone.is_aware(valor):
        valor = timezone.localtime(valor)
    return valor.strftime('%d/%m/%Y %H:%M')


def _usuario(usuario) -> str:
    return usuario.username if usuario else ''


def datos_despacho(despacho, items) -> dict:
    """Arma el diccionario de datos de un despacho para ReportBro.

    Args:
        despacho: Instancia de Despacho.
        items: Iterable de DespachoItem (idealmente select_related('pedido_item')).

    Returns:
        Diccionario con las claves del contrato de despacho.
    """
    pedido = despacho.pedido
    filas = []
    for item in items:
        pi = item.pedido_item
        filas.append({
            'codigo': pi.codigo if pi else item.codigo_real,
            'descripcion': pi.descripcion if pi else item.descripcion_real,
            'referencia': pi.referencia if pi else '',
            'puesto': pi.puesto if pi else '',
            'ref_proveedor': pi.ref_proveedor if pi else '',
            'cantidad_solicitada': pi.cantidad_solicitada if pi else 0,
            'cantidad_despachada': item.cantidad_despachada,
            'cantidad_recibida': item.cantidad_recibida,
            'observacion': item.observacion,
        })
    return {
        'numero_despacho': despacho.numero_despacho,
        'numero_pedido': pedido.numero_pedido,
        'estado': despacho.get_estado_display(),
        'condicion': pedido.get_condicion_display() if pedido.condicion else '',
        'deposito': pedido.deposito,
        'solicitante': _usuario(pedido.solicitante),
        'despachador': _usuario(despacho.despachador),
        'picker': _usuario(despacho.picker),
        'receptor': _usuario(despacho.receptor),
        'fecha_despacho': _fmt_fecha(despacho.fecha_despacho),
        'fecha_recepcion': _fmt_fecha(despacho.fecha_recepcion),
        'observaciones': despacho.observaciones,
        'items': filas,
        'total_items': len(filas),
        'total_despachado': sum(f['cantidad_despachada'] for f in filas),
    }


def datos_pedido(pedido, items, mostrar_cantidades: bool = True) -> dict:
    """Arma el diccionario de datos de un pedido para ReportBro.

    Args:
        pedido: Instancia de Pedido.
        items: Iterable de PedidoItem.
        mostrar_cantidades: Si es False (usuarios sin privilegio, ej. tienda),
            las cantidades sensibles (despachada, back order, recibida) se
            envían como None — defensa a nivel de datos: aunque la plantilla
            muestre esas columnas, los valores llegan vacíos. La plantilla
            además puede ocultar la columna completa con printIf
            ``${mostrar_cantidades}`` en la celda de encabezado.
    """
    filas = [{
        'codigo': it.codigo,
        'descripcion': it.descripcion,
        'referencia': it.referencia,
        'puesto': it.puesto,
        'ref_proveedor': it.ref_proveedor,
        'cantidad_solicitada': it.cantidad_solicitada,
        'cantidad_despachada': it.cantidad_despachada if mostrar_cantidades else None,
        'cantidad_back_order': it.cantidad_back_order if mostrar_cantidades else None,
        'cantidad_recibida': it.cantidad_recibida if mostrar_cantidades else None,
        'estado': it.get_estado_display(),
        'observacion': it.observacion,
    } for it in items]
    return {
        'mostrar_cantidades': mostrar_cantidades,
        'numero_pedido': pedido.numero_pedido,
        'estado': pedido.get_estado_display(),
        'condicion': pedido.get_condicion_display() if pedido.condicion else '',
        'deposito': pedido.deposito,
        'categoria': pedido.categoria_nombre or pedido.categoria,
        'solicitante': _usuario(pedido.solicitante),
        'despachador': _usuario(pedido.despachador),
        'picker': _usuario(pedido.picker),
        'fecha_creacion': _fmt_fecha(pedido.fecha_creacion),
        'fecha_despacho': _fmt_fecha(pedido.fecha_despacho),
        'fecha_recepcion': _fmt_fecha(pedido.fecha_recepcion),
        'observaciones': pedido.observaciones,
        'items': filas,
        'total_items': len(filas),
        'total_solicitado': sum(f['cantidad_solicitada'] for f in filas),
    }


_ITEM_SINTETICO = {
    'codigo': 'ABC123', 'descripcion': 'Producto de ejemplo', 'referencia': 'REF-1',
    'puesto': 'A-01', 'ref_proveedor': 'PROV-9', 'cantidad_solicitada': 10,
    'cantidad_despachada': 8, 'cantidad_recibida': 8, 'observacion': '',
}

_EJEMPLO_DESPACHO = {
    'numero_despacho': 1, 'numero_pedido': 1, 'estado': 'Enviado',
    'condicion': 'Urgente', 'deposito': 'Tienda de ejemplo',
    'solicitante': 'tienda', 'despachador': 'almacen', 'picker': 'picker',
    'receptor': '', 'fecha_despacho': '01/01/2026 08:00', 'fecha_recepcion': '',
    'observaciones': 'Datos de ejemplo', 'items': [dict(_ITEM_SINTETICO)],
    'total_items': 1, 'total_despachado': 8,
}

_EJEMPLO_PEDIDO = {
    'mostrar_cantidades': True,
    'numero_pedido': 1, 'estado': 'Pendiente', 'condicion': 'Surtido',
    'deposito': 'Tienda de ejemplo', 'categoria': 'Hogar',
    'solicitante': 'tienda', 'despachador': '', 'picker': '',
    'fecha_creacion': '01/01/2026 08:00', 'fecha_despacho': '', 'fecha_recepcion': '',
    'observaciones': 'Datos de ejemplo',
    'items': [{**_ITEM_SINTETICO, 'cantidad_back_order': 2, 'estado': 'Pendiente'}],
    'total_items': 1, 'total_solicitado': 10,
}


def datos_ejemplo(tipo: str) -> dict:
    """Datos de prueba para preview/validación: último registro real o sintético.

    Raises:
        ValueError: si el tipo no es 'despacho' ni 'pedido'.
    """
    from PedidosAlmacen.models import Despacho, Pedido

    if tipo == 'despacho':
        despacho = (Despacho.objects.select_related('pedido__solicitante')
                    .order_by('-numero_despacho').first())
        if despacho is not None:
            return datos_despacho(despacho, despacho.items.select_related('pedido_item'))
        return dict(_EJEMPLO_DESPACHO)
    if tipo == 'pedido':
        pedido = (Pedido.objects.select_related('solicitante')
                  .order_by('-numero_pedido').first())
        if pedido is not None:
            return datos_pedido(pedido, pedido.items.all())
        return dict(_EJEMPLO_PEDIDO)
    raise ValueError(f'Tipo de documento desconocido: {tipo}')
