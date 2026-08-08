"""Cálculo de disponibilidad real de un SKU: existencia física menos lo ya

comprometido por pedidos activos que aún no fueron despachados.

Nota de concurrencia: este cálculo no toma locks. Dos solicitudes concurrentes
sobre el mismo SKU pueden ambas pasar la validación (ninguna ve el compromiso
de la otra hasta que se guarda). No se agrega `select_for_update` porque el
volumen de pedidos internos de almacén no lo justifica y el sistema ya
absorbe el sobre-compromiso vía back orders.
"""
from django.db.models import F, Value
from django.db.models.functions import Greatest

from .models import PedidoItem

# Estados de PedidoItem cuyo remanente (solicitado - despachado) sigue
# comprometiendo stock: aún no se despachó todo lo pedido.
ESTADOS_ITEM_COMPROMETIDOS = ('PENDIENTE', 'BACK_ORDER', 'PARCIAL')

# Estados de Pedido que ya no reservan stock aunque sus items sigan en un
# estado "comprometido" (p.ej. anular_pedido no reescribe el estado del item).
ESTADOS_PEDIDO_INACTIVOS = ('ANULADO', 'CERRADO')


def compromisos_por_codigo(codigos):
    """Cantidad comprometida por pedidos activos, por código de producto.

    Args:
        codigos: lista de códigos de producto (SKU) a consultar.

    Returns:
        dict {codigo: {'comprometido': int, 'pedidos': [numero_pedido, ...]}}.
        Los códigos sin compromiso no aparecen en el dict. `pedidos` está
        ordenado de más antiguo a más reciente.
    """
    if not codigos:
        return {}

    filas = (
        PedidoItem.objects
        .filter(codigo__in=codigos, estado__in=ESTADOS_ITEM_COMPROMETIDOS)
        .exclude(pedido__estado__in=ESTADOS_PEDIDO_INACTIVOS)
        .annotate(pendiente=Greatest(
            F('cantidad_solicitada') - F('cantidad_despachada'), Value(0)))
        .values('codigo', 'pedido__numero_pedido', 'pendiente')
        .order_by('pedido__numero_pedido')
    )

    resultado = {}
    for fila in filas:
        if fila['pendiente'] <= 0:
            continue
        entrada = resultado.setdefault(fila['codigo'], {'comprometido': 0, 'pedidos': []})
        entrada['comprometido'] += fila['pendiente']
        entrada['pedidos'].append(fila['pedido__numero_pedido'])

    return resultado


def calcular_disponibilidad(codigos, existencias):
    """Cruza existencia física con lo comprometido por pedidos activos.

    Args:
        codigos: lista de códigos de producto a evaluar.
        existencias: dict {codigo: existencia_fisica} (p.ej. de
            PedidosDBISAM.consultar_stock_multiple). Códigos ausentes se
            tratan como existencia 0.

    Returns:
        dict {codigo: {'existencia': int, 'comprometido': int,
                        'disponible': int, 'pedidos': [numero_pedido, ...]}}
        para cada código en `codigos`. `disponible` nunca es negativo.
    """
    compromisos = compromisos_por_codigo(codigos)

    resultado = {}
    for codigo in codigos:
        existencia = existencias.get(codigo, 0)
        info = compromisos.get(codigo, {'comprometido': 0, 'pedidos': []})
        comprometido = info['comprometido']
        resultado[codigo] = {
            'existencia': existencia,
            'comprometido': comprometido,
            'disponible': max(0, existencia - comprometido),
            'pedidos': info['pedidos'],
        }
    return resultado
