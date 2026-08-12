import logging
import pyodbc
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Pedido, PedidoItem, Despacho, DespachoItem
from .serializers import (
    PedidoListSerializer, PedidoDetailSerializer,
    PedidoItemSerializer, DespachoSerializer, DespachoCreateSerializer,
)
from .dbisam import PedidosDBISAM, DEPOSITO_ALMACEN
from .views import is_pedidos_almacen, is_pedidos_supervisor, is_pedidos_picker, _solo_tienda, _solo_picker

logger = logging.getLogger(__name__)

_CAMPOS_VALIDOS = {'sku', 'codBarra', 'refProveedor'}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_pedidos_list(request):
    print('despachos', request)
    if is_pedidos_supervisor(request.user):
        qs = Pedido.objects.select_related('solicitante', 'picker').prefetch_related('items')
    elif is_pedidos_almacen(request.user):
        qs = Pedido.objects.exclude(estado='CERRADO').select_related('solicitante', 'picker').prefetch_related('items')
    else:
        qs = Pedido.objects.filter(picker=request.user).select_related('picker').prefetch_related('items')

    estado = request.query_params.get('estado', '')
    if estado:
        qs = qs.filter(estado=estado)

    if _solo_picker(request.user):
        orden = ('fecha_asignacion', 'fecha_creacion')
    else:
        orden = ('-fecha_creacion',)

    print(PedidoListSerializer(qs.order_by(*orden), many=True).data)
    return Response(PedidoListSerializer(qs.order_by(*orden), many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_pedido_detail(request, pk):
    pedido = get_object_or_404(
        Pedido.objects.select_related('solicitante', 'picker').prefetch_related('items'),
        numero_pedido=pk,
    )
    print(pedido)
    #if _solo_tienda(request.user) and pedido.solicitante != request.user:
    #    return Response({'error': 'Sin permiso para ver este pedido'}, status=403)
    if _solo_picker(request.user) and pedido.picker != request.user:
        return Response({'error': 'Sin permiso para ver este pedido'}, status=403)
    print(PedidoDetailSerializer(pedido).data)
    return Response(PedidoDetailSerializer(pedido).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def api_update_pedido(request, pk):
    print(request)
    pedido = get_object_or_404(Pedido, numero_pedido=pk)
    nuevo_estado = request.data.get('estado')
    if nuevo_estado and nuevo_estado in dict(Pedido.ESTADO_CHOICES):
        pedido.estado = nuevo_estado
        if nuevo_estado == 'EN_PREPARACION' and not pedido.despachador:
            pedido.despachador = request.user
        pedido.save()
    pedido.refresh_from_db()
    return Response(PedidoDetailSerializer(
        Pedido.objects.prefetch_related('items').get(pk=pk)
    ).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def api_update_item(request, pedido_pk, item_pk):
    item = get_object_or_404(PedidoItem, id=item_pk, pedido__numero_pedido=pedido_pk)
    cantidad = request.data.get('cantidad_preparada')
    if cantidad is not None:
        item.cantidad_preparada = int(cantidad)
        item.save(update_fields=['cantidad_preparada'])
    return Response(PedidoItemSerializer(item).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_despachos_list(request):
   
    if is_pedidos_supervisor(request.user):
        qs = Despacho.objects.select_related('pedido', 'despachador', 'receptor').prefetch_related('items__pedido_item')
    elif is_pedidos_almacen(request.user):
        qs = Despacho.objects.filter(despachador=request.user).select_related('pedido', 'despachador', 'receptor').prefetch_related('items__pedido_item')
    else:
        qs = Despacho.objects.filter(pedido__solicitante=request.user).select_related('pedido', 'despachador', 'receptor').prefetch_related('items__pedido_item')
    return Response(DespachoSerializer(qs.order_by('-fecha_despacho'), many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_preparar_pedido(request, pk):
    """
    Actualiza el estado de preparación de un pedido.

    Acciones:
      { "accion": "iniciar" }
          ASIGNADO → PICKING (picker comienza a trabajar)
      { "accion": "finalizar", "cantidades": {"<item_id>": <cantidad>, ...} }
          PICKING / EN_PREPARACION → EN_PREPARACION (picker registra cantidades y termina)
    """
    pedido = get_object_or_404(
        Pedido.objects.select_related('picker').prefetch_related('items'),
        numero_pedido=pk,
    )
    es_supervisor = is_pedidos_supervisor(request.user)
    es_picker_asignado = is_pedidos_picker(request.user) and pedido.picker == request.user

    if not es_supervisor and not es_picker_asignado:
        return Response({'error': 'No tienes permiso para preparar este pedido'}, status=403)

    if pedido.estado not in ('ASIGNADO', 'PICKING', 'EN_PREPARACION'):
        return Response(
            {'error': f'El pedido está en estado {pedido.estado} y no puede prepararse'},
            status=400,
        )

    accion = request.data.get('accion')

    if accion == 'iniciar':
        if pedido.estado != 'ASIGNADO':
            return Response(
                {'error': 'Solo se puede iniciar un pedido en estado ASIGNADO'},
                status=400,
            )
        if pedido.condicion not in ('URGENTE', 'CLIENTE_RETIRA'):
            otro_en_picking = Pedido.objects.filter(
                picker=pedido.picker, estado='PICKING'
            ).exclude(pk=pedido.pk).exists()
            if otro_en_picking:
                return Response(
                    {'error': 'Ya tienes otro pedido en Picking. Finalízalo antes de iniciar este.'},
                    status=409,
                )
        pedido.estado = 'PICKING'
        pedido.fecha_inicio_picking = timezone.now()
        pedido.fecha_fin_picking = None
        pedido.save(update_fields=['estado', 'fecha_inicio_picking', 'fecha_fin_picking'])

    elif accion == 'finalizar':
        cantidades = request.data.get('cantidades', {})
        items = pedido.items.filter(estado__in=['PENDIENTE', 'BACK_ORDER', 'PARCIAL'])
        for item in items:
            cantidad = cantidades.get(str(item.id))
            if cantidad is not None:
                item.cantidad_preparada = int(cantidad)
                item.save(update_fields=['cantidad_preparada'])
        if pedido.estado == 'PICKING':
            pedido.fecha_fin_picking = timezone.now()
        pedido.estado = 'EN_PREPARACION'
        pedido.save(update_fields=['estado', 'fecha_fin_picking'])

    else:
        return Response(
            {'error': 'Acción inválida. Use "iniciar" o "finalizar"'},
            status=400,
        )

    return Response(PedidoDetailSerializer(
        Pedido.objects.prefetch_related('items').get(pk=pk)
    ).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_crear_despacho(request):
    """
    Crea un despacho en estado PENDIENTE_APROBACION.
    El picker se asigna automáticamente desde el pedido.
    La aprobación se gestiona desde el back office Django.
    """
    if not (is_pedidos_almacen(request.user) or is_pedidos_supervisor(request.user) or is_pedidos_picker(request.user) ):
        return Response({'error': 'Solo almacén, supervisor o picker puede crear despachos'}, status=403)

    serializer = DespachoCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    data = serializer.validated_data
    pedido = get_object_or_404(
        Pedido.objects.select_related('picker').prefetch_related('items'),
        numero_pedido=data['pedido_id'],
    )

    if pedido.estado not in ['PICKING', 'PENDIENTE', 'PARCIAL', 'EN_PREPARACION']:
        return Response(
            {'error': f'El pedido está en estado {pedido.estado}. Solo pedidos PENDIENTE, PARCIAL, PICKING o EN_PREPARACION pueden despacharse'},
            status=400,
        )

    items_data = data.get('items', [])
    if not items_data:
        return Response({'error': 'Debe incluir al menos un ítem en el despacho'}, status=400)

    # Misma lógica de elegibilidad que despachar_pedido
    if pedido.estado == 'PARCIAL':
        items_elegibles = list(pedido.items.filter(estado__in=['BACK_ORDER', 'PARCIAL']))
    else:
        items_elegibles = list(pedido.items.filter(estado__in=['PENDIENTE', 'BACK_ORDER', 'PARCIAL']))

    # Validar existencia en depósito 1 (Almacén) antes de crear el despacho.
    # Solo se validan items con pedido_item vinculado (los de tipo_incidencia
    # SKU_NO_CONTEMPLADO / PRODUCTO_ERRONEO no tienen pedido_item y se omiten).
    pedido_item_map = {item.id: item for item in pedido.items.all()}
    codigo_a_cantidad: dict = {}
    for item_data in items_data:
        pid = item_data.get('pedido_item_id')
        if pid and pid in pedido_item_map:
            codigo = pedido_item_map[pid].codigo
            codigo_a_cantidad[codigo] = codigo_a_cantidad.get(codigo, 0) + item_data['cantidad_despachada']

    if codigo_a_cantidad:
        try:
            stock_despacho = PedidosDBISAM().consultar_stock_multiple(
                list(codigo_a_cantidad.keys()), deposito=DEPOSITO_ALMACEN
            )
        except Exception as e:
            return Response({'error': f'Error consultando DBISAM: {e}'}, status=502)

        excesos_despacho = [
            f"{codigo} (despachando {qty}, stock disponible: {stock_despacho.get(codigo, 0)})"
            for codigo, qty in codigo_a_cantidad.items()
            if qty > stock_despacho.get(codigo, 0)
        ]
        if excesos_despacho:
            return Response(
                {'error': f"No se puede despachar más del stock disponible en almacén: {'; '.join(excesos_despacho)}"},
                status=400,
            )

    despacho = Despacho.objects.create(
        pedido=pedido,
        picker=pedido.picker or request.user,
        fecha_inicio_picking=pedido.fecha_inicio_picking,
        fecha_fin_picking=pedido.fecha_fin_picking,
        estado='PENDIENTE_APROBACION',
        fecha_despacho=timezone.now(),
        observaciones=data.get('observaciones', ''),
    )

    ids_despachados = set()
    for item_data in items_data:
        pedido_item = None
        if item_data.get('pedido_item_id'):
            pedido_item = get_object_or_404(PedidoItem, id=item_data['pedido_item_id'], pedido=pedido)

        DespachoItem.objects.create(
            despacho=despacho,
            pedido_item=pedido_item,
            cantidad_despachada=item_data['cantidad_despachada'],
            observacion=item_data.get('observacion', ''),
            tipo_incidencia=item_data.get('tipo_incidencia', ''),
            codigo_real=item_data.get('codigo_real', ''),
            descripcion_real=item_data.get('descripcion_real', ''),
        )

        if pedido_item:
            cantidad_enviar = item_data['cantidad_despachada']
            pedido_item.cantidad_despachada = (pedido_item.cantidad_despachada or 0) + cantidad_enviar
            pedido_item.cantidad_back_order = max(0, pedido_item.cantidad_solicitada - pedido_item.cantidad_despachada)
            pedido_item.cantidad_preparada = None
            pedido_item.estado = 'DESPACHADO' if pedido_item.cantidad_back_order == 0 else 'PARCIAL'
            pedido_item.save()
            ids_despachados.add(pedido_item.id)

    # Items elegibles no incluidos en el despacho → BACK_ORDER
    for item in items_elegibles:
        if item.id not in ids_despachados:
            item.cantidad_back_order = item.cantidad_solicitada - (item.cantidad_despachada or 0)
            item.cantidad_preparada = None
            item.estado = 'BACK_ORDER'
            item.save()

    # Actualizar estado del pedido
    if not pedido.fecha_despacho:
        pedido.fecha_despacho = timezone.now()
    pedido.estado = 'EN_PREPARACION'
    pedido.save()

    return Response(
        DespachoSerializer(
            Despacho.objects.select_related('pedido', 'despachador', 'picker', 'receptor')
                            .prefetch_related('items__pedido_item')
                            .get(pk=despacho.pk)
        ).data,
        status=201,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_alerts_list(request):
    qs = Pedido.objects.filter(
        picker=request.user,
        estado__in=['ASIGNADO', 'PICKING'],
    ).select_related('solicitante').order_by('-fecha_creacion')

    alerts = []
    for p in qs:
        ts = p.fecha_creacion.strftime('%d/%m %H:%M') if p.fecha_creacion else ''
        alerts.append({
            'id': f'{p.numero_pedido}',
            'type': 'asignado',
            'msg': f'Pedido #{p.numero_pedido} — {p.solicitante.username}',
            'orderId': str(p.numero_pedido),
            'estado': p.estado,
            'condicion': p.condicion,
            'ts': ts,
        })
    
    return Response(alerts)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_buscar_producto(request, codigo):
    """GET /api/productos/<codigo>/ — busca producto en DBISAM.

    Requiere header X-Campo: sku | codBarra | refProveedor.
    """
    campo = request.headers.get('X-Campo')
    if not campo:
        return Response({'error': 'Header X-Campo requerido'}, status=400)
    if campo not in _CAMPOS_VALIDOS:
        return Response(
            {'error': 'X-Campo inválido. Use: sku, codBarra, refProveedor'},
            status=400,
        )

    try:
        row = PedidosDBISAM().buscar_producto_por_campo(codigo, campo)
    except pyodbc.DatabaseError as e:
        return Response({'error': f'Error consultando DBISAM: {e}'}, status=502)

    if row is None:
        return Response({'error': 'Producto no encontrado'}, status=404)

    codigo_prod, descripcion, referencia, puesto, ref_proveedor = row

    from ubicaciones.models import ProductoUbicacion
    ubicaciones_internas = []
    try:
        qs = (
            ProductoUbicacion.objects
            .filter(
                codigo_producto=codigo_prod,
                nivel__activo=True,
                nivel__ubicacion__activo=True,
                nivel__ubicacion__cuerpo__activo=True,
                nivel__ubicacion__cuerpo__rack__activo=True,
            )
            .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        )
        ubicaciones_internas = [
            {
                'codigo': pu.nivel.codigo_completo,
                'tipo_nivel': pu.nivel.tipo,
                'tipo_nivel_display': pu.nivel.get_tipo_display(),
            }
            for pu in qs
        ]
    except Exception:
        logger.exception("Error al consultar ubicaciones internas en api_buscar_producto")

    return Response({
        'codigo': codigo_prod,
        'descripcion': descripcion,
        'referencia': referencia,
        'puesto': puesto,
        'ref_proveedor': ref_proveedor,
        'ubicaciones_internas': ubicaciones_internas,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_ficha_producto(request, codigo):
    """GET /api/productos/<codigo>/ficha/ — ficha completa bajo demanda (botón "ojito").

    A diferencia de api_buscar_producto (llamado en cada escaneo), este
    endpoint solo se llama cuando el usuario pide ver el detalle: agrega
    existencia del almacén principal y pedidos relacionados en otros pedidos.
    Requiere header X-Campo: sku | codBarra | refProveedor.
    """
    campo = request.headers.get('X-Campo')
    if not campo:
        return Response({'error': 'Header X-Campo requerido'}, status=400)
    if campo not in _CAMPOS_VALIDOS:
        return Response(
            {'error': 'X-Campo inválido. Use: sku, codBarra, refProveedor'},
            status=400,
        )

    try:
        row = PedidosDBISAM().buscar_producto_por_campo(codigo, campo)
    except pyodbc.DatabaseError as e:
        return Response({'error': f'Error consultando DBISAM: {e}'}, status=502)

    if row is None:
        return Response({'error': 'Producto no encontrado'}, status=404)

    codigo_prod, descripcion, referencia, puesto, ref_proveedor = row

    from ubicaciones.models import ProductoUbicacion
    ubicaciones_internas = []
    try:
        qs = (
            ProductoUbicacion.objects
            .filter(
                codigo_producto=codigo_prod,
                nivel__activo=True,
                nivel__ubicacion__activo=True,
                nivel__ubicacion__cuerpo__activo=True,
                nivel__ubicacion__cuerpo__rack__activo=True,
            )
            .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        )
        ubicaciones_internas = [
            {
                'codigo': pu.nivel.codigo_completo,
                'tipo_nivel': pu.nivel.tipo,
                'tipo_nivel_display': pu.nivel.get_tipo_display(),
            }
            for pu in qs
        ]
    except Exception:
        logger.exception("Error al consultar ubicaciones internas en api_ficha_producto")

    try:
        existencia_almacen = PedidosDBISAM().consultar_stock(codigo_prod, deposito=DEPOSITO_ALMACEN)
    except pyodbc.DatabaseError as e:
        return Response({'error': f'Error consultando DBISAM: {e}'}, status=502)

    items_relacionados = (
        PedidoItem.objects
        .filter(codigo=codigo_prod, estado__in=['PENDIENTE', 'PARCIAL', 'BACK_ORDER'])
        .exclude(pedido__estado__in=['ANULADO', 'CERRADO'])
        .select_related('pedido')
        .order_by('pedido__fecha_creacion')
    )

    pedidos_pendientes, pedidos_parciales, pedidos_backorder = [], [], []
    for item in items_relacionados:
        p = item.pedido
        fila = {
            'numero_pedido': p.numero_pedido,
            'deposito': p.deposito,
            'estado_pedido': p.estado,
            'condicion': p.condicion,
            'cantidad_solicitada': item.cantidad_solicitada,
            'fecha_creacion': p.fecha_creacion,
        }
        if item.estado == 'PENDIENTE':
            pedidos_pendientes.append(fila)
        elif item.estado == 'PARCIAL':
            pedidos_parciales.append({
                **fila,
                'cantidad_despachada': item.cantidad_despachada,
                'cantidad_back_order': item.cantidad_back_order,
            })
        else:  # BACK_ORDER
            pedidos_backorder.append({
                **fila,
                'cantidad_back_order': item.cantidad_back_order,
            })

    return Response({
        'codigo': codigo_prod,
        'descripcion': descripcion,
        'referencia': referencia,
        'puesto': puesto,
        'ref_proveedor': ref_proveedor,
        'ubicaciones_internas': ubicaciones_internas,
        'existencia_almacen': existencia_almacen,
        'pedidos_pendientes': pedidos_pendientes,
        'pedidos_parciales': pedidos_parciales,
        'pedidos_backorder': pedidos_backorder,
    })
