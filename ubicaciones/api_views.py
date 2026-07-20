import logging

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM

from .models import MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion
from .serializers import (
    MovimientoSerializer,
    NivelSerializer,
    ProductoUbicacionesSerializer,
    RackSerializer,
    UbicacionDetailSerializer,
    UbicacionListSerializer,
)
from .services import UbicacionesService

logger = logging.getLogger(__name__)

_AUTH = [SessionAuthentication, TokenAuthentication]
_PERM = [IsAuthenticated]


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_racks_list(request):
    qs = Rack.objects.all()
    activo = request.query_params.get('activo')
    if activo is not None:
        qs = qs.filter(activo=activo == '1')
    return Response(RackSerializer(qs, many=True).data)


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_rack_detail(request, pk: int):
    try:
        rack = Rack.objects.get(pk=pk)
    except Rack.DoesNotExist:
        return Response({'error': 'Rack no encontrado.'}, status=404)
    niveles = Nivel.objects.filter(rack=rack)
    return Response({
        'rack': RackSerializer(rack).data,
        'niveles': NivelSerializer(niveles, many=True).data,
    })


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_nivel_ubicaciones(request, pk: int):
    try:
        nivel = Nivel.objects.select_related('rack').get(pk=pk)
    except Nivel.DoesNotExist:
        return Response({'error': 'Nivel no encontrado.'}, status=404)
    ubicaciones = Ubicacion.objects.filter(nivel=nivel)
    return Response(UbicacionListSerializer(ubicaciones, many=True).data)


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_ubicacion_detail(request, pk: int):
    try:
        ubic = Ubicacion.objects.select_related('nivel__rack').get(pk=pk)
    except Ubicacion.DoesNotExist:
        return Response({'error': 'Ubicación no encontrada.'}, status=404)
    return Response(UbicacionDetailSerializer(ubic).data)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_asignar_producto(request, pk: int):
    try:
        ubic = Ubicacion.objects.select_related('nivel__rack').get(pk=pk)
    except Ubicacion.DoesNotExist:
        return Response({'error': 'Ubicación no encontrada.'}, status=404)
    codigo = (request.data.get('codigo_producto') or '').strip()
    if not codigo:
        return Response({'error': 'Se requiere codigo_producto.'}, status=400)
    try:
        UbicacionesService.asignar_producto(codigo, ubic, request.user)
        return Response({'ok': True, 'mensaje': f"Producto '{codigo}' asignado."})
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_quitar_producto(request, pk: int):
    pu_id = request.data.get('producto_ubicacion_id')
    if not pu_id:
        return Response({'error': 'Se requiere producto_ubicacion_id.'}, status=400)
    try:
        UbicacionesService.quitar_producto(int(pu_id), request.user)
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
    origen_id = request.data.get('ubicacion_origen')
    destino_id = request.data.get('ubicacion_destino')
    notas = request.data.get('notas', '')
    if not all([codigo, origen_id, destino_id]):
        return Response({'error': 'Se requieren: codigo_producto, ubicacion_origen, ubicacion_destino.'}, status=400)
    try:
        ubic_origen = Ubicacion.objects.select_related('nivel__rack').get(pk=origen_id)
        ubic_destino = Ubicacion.objects.select_related('nivel__rack').get(pk=destino_id)
    except Ubicacion.DoesNotExist:
        return Response({'error': 'Una de las ubicaciones no existe.'}, status=404)
    try:
        UbicacionesService.trasladar_producto(codigo, ubic_origen, ubic_destino, request.user, notas)
        return Response({'ok': True, 'mensaje': 'Traslado realizado.'})
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_fusionar(request):
    a_id = request.data.get('ubicacion_a')
    b_id = request.data.get('ubicacion_b')
    notas = request.data.get('notas', '')
    if not all([a_id, b_id]):
        return Response({'error': 'Se requieren: ubicacion_a, ubicacion_b.'}, status=400)
    try:
        ubic_a = Ubicacion.objects.select_related('nivel__rack').get(pk=a_id)
        ubic_b = Ubicacion.objects.select_related('nivel__rack').get(pk=b_id)
    except Ubicacion.DoesNotExist:
        return Response({'error': 'Una de las ubicaciones no existe.'}, status=404)
    try:
        transferidos = UbicacionesService.fusionar_ubicaciones(ubic_a, ubic_b, request.user, notas)
        return Response({'ok': True, 'transferidos': transferidos})
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_movimientos(request):
    qs = MovimientoUbicacion.objects.select_related(
        'usuario', 'rack', 'nivel', 'ubicacion_origen', 'ubicacion_destino',
    )
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
    """Devuelve todas las ubicaciones donde está asignado el código + existencia DBISAM."""
    codigo = codigo.strip().upper()
    asignaciones = (
        ProductoUbicacion.objects
        .filter(codigo_producto=codigo)
        .select_related('ubicacion__nivel__rack')
    )
    existencia = 0
    try:
        db = PedidosDBISAM()
        existencia = db.consultar_stock(codigo, deposito=DEPOSITO_ALMACEN)
    except Exception:
        logger.exception("Error al consultar DBISAM en api_producto_ubicaciones")

    ubicaciones_data = [
        {
            'ubicacion_id': pu.ubicacion.pk,
            'codigo': pu.ubicacion.codigo_completo,
            'rack': pu.ubicacion.rack.codigo,
            'nivel': pu.ubicacion.nivel.codigo,
            'ubicacion': pu.ubicacion.codigo,
            'tipo_nivel': pu.ubicacion.nivel.tipo,
        }
        for pu in asignaciones
    ]
    return Response({
        'codigo': codigo,
        'existencia_dbisam': existencia,
        'ubicaciones': ubicaciones_data,
    })
