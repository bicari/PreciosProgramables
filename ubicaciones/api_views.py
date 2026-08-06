import logging

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM

from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack
from .serializers import (
    CuerpoSerializer,
    GalponSerializer,
    MovimientoSerializer,
    NivelSerializer,
    ProductoUbicacionSerializer,
    RackSerializer,
)
from .services import UbicacionesService

logger = logging.getLogger(__name__)

_AUTH = [SessionAuthentication, TokenAuthentication]
_PERM = [IsAuthenticated]


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_galpones_list(request):
    qs = Galpon.objects.all()
    activo = request.query_params.get('activo')
    if activo is not None:
        qs = qs.filter(activo=activo == '1')
    return Response(GalponSerializer(qs, many=True).data)


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_galpon_detail(request, pk: int):
    try:
        galpon = Galpon.objects.get(pk=pk)
    except Galpon.DoesNotExist:
        return Response({'error': 'Galpón no encontrado.'}, status=404)
    racks = Rack.objects.filter(galpon=galpon)
    return Response({
        'galpon': GalponSerializer(galpon).data,
        'racks': RackSerializer(racks, many=True).data,
    })


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_rack_detail(request, pk: int):
    try:
        rack = Rack.objects.get(pk=pk)
    except Rack.DoesNotExist:
        return Response({'error': 'Rack no encontrado.'}, status=404)
    cuerpos = Cuerpo.objects.filter(rack=rack)
    return Response({
        'rack': RackSerializer(rack).data,
        'cuerpos': CuerpoSerializer(cuerpos, many=True).data,
    })


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_cuerpo_detail(request, pk: int):
    try:
        cuerpo = Cuerpo.objects.select_related('rack').get(pk=pk)
    except Cuerpo.DoesNotExist:
        return Response({'error': 'Cuerpo no encontrado.'}, status=404)
    niveles = Nivel.objects.filter(ubicacion__cuerpo=cuerpo).select_related('ubicacion')
    return Response({
        'cuerpo': CuerpoSerializer(cuerpo).data,
        'niveles': NivelSerializer(niveles, many=True).data,
    })


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_asignar_producto(request, pk: int):
    try:
        nivel = Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon').get(pk=pk)
    except Nivel.DoesNotExist:
        return Response({'error': 'Nivel no encontrado.'}, status=404)
    codigo = (request.data.get('codigo_producto') or '').strip()
    cantidad = request.data.get('cantidad')
    stock_minimo = request.data.get('stock_minimo') or None
    if not codigo or cantidad is None:
        return Response({'error': 'Se requieren codigo_producto y cantidad.'}, status=400)
    try:
        pu = UbicacionesService.asignar_producto(codigo, nivel, int(cantidad), stock_minimo, request.user)
        return Response(ProductoUbicacionSerializer(pu).data, status=201)
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_editar_cantidad(request, pk: int):
    try:
        pu = ProductoUbicacion.objects.select_related('nivel').get(pk=pk)
    except ProductoUbicacion.DoesNotExist:
        return Response({'error': 'Asignación no encontrada.'}, status=404)
    cantidad = request.data.get('cantidad')
    stock_minimo = request.data.get('stock_minimo') or None
    if cantidad is None:
        return Response({'error': 'Se requiere cantidad.'}, status=400)
    try:
        pu = UbicacionesService.editar_cantidad(pu, int(cantidad), stock_minimo, request.user)
        return Response(ProductoUbicacionSerializer(pu).data)
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_quitar_producto(request, pk: int):
    try:
        UbicacionesService.quitar_producto(pk, request.user)
        return Response({'ok': True})
    except ProductoUbicacion.DoesNotExist:
        return Response({'error': 'Asignación no encontrada.'}, status=404)
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_trasladar(request):
    codigo = (request.data.get('codigo_producto') or '').strip()
    origen_id = request.data.get('nivel_origen')
    destino_id = request.data.get('nivel_destino')
    notas = request.data.get('notas', '')
    if not all([codigo, origen_id, destino_id]):
        return Response({'error': 'Se requieren: codigo_producto, nivel_origen, nivel_destino.'}, status=400)
    try:
        nivel_origen = Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon').get(pk=origen_id)
        nivel_destino = Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon').get(pk=destino_id)
    except Nivel.DoesNotExist:
        return Response({'error': 'Uno de los niveles no existe.'}, status=404)
    try:
        UbicacionesService.trasladar_producto(codigo, nivel_origen, nivel_destino, request.user, notas)
        return Response({'ok': True, 'mensaje': 'Traslado realizado.'})
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_fusionar(request):
    ids = request.data.get('niveles') or []
    maestro_id = request.data.get('maestro')
    notas = request.data.get('notas', '')
    if not ids or not maestro_id:
        return Response({'error': 'Se requieren: niveles (lista), maestro.'}, status=400)
    niveles = list(Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon').filter(pk__in=ids))
    if len(niveles) != len(set(ids)):
        return Response({'error': 'Uno o más niveles no existen.'}, status=404)
    maestro = next((n for n in niveles if n.pk == int(maestro_id)), None)
    if maestro is None:
        return Response({'error': 'El maestro no existe.'}, status=404)
    try:
        transferidos = UbicacionesService.fusionar_niveles(niveles, maestro, request.user, notas)
        return Response({'ok': True, 'transferidos': transferidos})
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_desfusionar(request, pk: int):
    try:
        nivel = Nivel.objects.get(pk=pk)
    except Nivel.DoesNotExist:
        return Response({'error': 'Nivel no encontrado.'}, status=404)
    try:
        UbicacionesService.desfusionar_nivel(nivel, request.user)
        return Response({'ok': True})
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_movimientos(request):
    qs = MovimientoUbicacion.objects.select_related('usuario', 'rack', 'nivel_origen', 'nivel_destino')
    tipo = request.query_params.get('tipo')
    codigo = request.query_params.get('codigo')
    if tipo:
        qs = qs.filter(tipo=tipo)
    if codigo:
        qs = qs.filter(codigo_producto__icontains=codigo)
    return Response(MovimientoSerializer(qs[:200], many=True).data)


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_producto_ubicaciones(request, codigo: str):
    codigo = codigo.strip().upper()
    asignaciones = (
        ProductoUbicacion.objects
        .filter(codigo_producto=codigo)
        .select_related('nivel__ubicacion__cuerpo__rack__galpon')
    )
    existencia = 0
    try:
        existencia = PedidosDBISAM().consultar_stock(codigo, deposito=DEPOSITO_ALMACEN)
    except Exception:
        logger.exception("Error al consultar DBISAM en api_producto_ubicaciones")

    return Response({
        'codigo': codigo,
        'existencia_dbisam': existencia,
        'ubicaciones': ProductoUbicacionSerializer(asignaciones, many=True).data,
    })
