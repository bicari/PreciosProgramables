import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM

from .forms import (
    AsignarProductoForm,
    FusionarForm,
    NivelForm,
    RackForm,
    TrasladarForm,
    UbicacionForm,
)
from .models import MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion
from .services import UbicacionesService

logger = logging.getLogger(__name__)

GROUP_UBICACIONES = 'Pedidos Ubicaciones'


def is_ubicaciones(user) -> bool:
    return user.groups.filter(name=GROUP_UBICACIONES).exists() or user.is_superuser


# ------------------------------------------------------------------ Racks

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def lista_racks(request):
    solo_activos = request.GET.get('activo', '1')
    qs = Rack.objects.prefetch_related('niveles')
    if solo_activos == '1':
        qs = qs.filter(activo=True)
    return render(request, 'ubicaciones-racks-lista.html', {
        'racks': qs,
        'solo_activos': solo_activos,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def crear_rack(request):
    if request.method == 'POST':
        form = RackForm(request.POST)
        if form.is_valid():
            try:
                rack = UbicacionesService.crear_rack(
                    codigo=form.cleaned_data['codigo'],
                    descripcion=form.cleaned_data['descripcion'],
                    max_niveles=form.cleaned_data['max_niveles'],
                    usuario=request.user,
                )
                messages.success(request, f"Rack '{rack.codigo}' creado correctamente.")
                return redirect('ubicaciones-racks-detalle', pk=rack.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = RackForm()
    return render(request, 'ubicaciones-racks-crear.html', {'form': form})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_rack(request, pk: int):
    rack = get_object_or_404(Rack, pk=pk)
    niveles = Nivel.objects.filter(rack=rack).prefetch_related('ubicaciones')
    return render(request, 'ubicaciones-racks-detalle.html', {
        'rack': rack,
        'niveles': niveles,
        'tope_alcanzado': rack.tope_alcanzado,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_rack(request, pk: int):
    rack = get_object_or_404(Rack, pk=pk)
    if request.method == 'POST':
        form = RackForm(request.POST, instance=rack)
        if form.is_valid():
            try:
                UbicacionesService.editar_rack(
                    rack=rack,
                    descripcion=form.cleaned_data['descripcion'],
                    max_niveles=form.cleaned_data['max_niveles'],
                    usuario=request.user,
                )
                messages.success(request, f"Rack '{rack.codigo}' actualizado.")
                return redirect('ubicaciones-racks-detalle', pk=rack.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = RackForm(instance=rack)
    return render(request, 'ubicaciones-racks-editar.html', {'form': form, 'rack': rack})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_rack(request, pk: int):
    rack = get_object_or_404(Rack, pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_rack(rack, request.user)
            messages.success(request, f"Rack '{rack.codigo}' desactivado.")
            return redirect('ubicaciones-racks-lista')
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-racks-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': rack,
        'tipo': 'rack',
        'nombre': rack.codigo,
    })


# ------------------------------------------------------------------ Niveles

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def crear_nivel(request):
    rack_pk = request.GET.get('rack') or request.POST.get('rack')
    rack_fijo = Rack.objects.filter(pk=rack_pk).first() if rack_pk else None

    if request.method == 'POST':
        form = NivelForm(request.POST, rack_fijo=rack_fijo)
        if form.is_valid():
            rack_obj = form.cleaned_data['rack'] if not rack_fijo else rack_fijo
            try:
                nivel = UbicacionesService.crear_nivel(
                    rack=rack_obj,
                    codigo=form.cleaned_data['codigo'],
                    tipo=form.cleaned_data['tipo'],
                    descripcion=form.cleaned_data['descripcion'],
                    usuario=request.user,
                )
                messages.success(request, f"Nivel '{nivel.codigo}' creado en rack '{rack_obj.codigo}'.")
                return redirect('ubicaciones-racks-detalle', pk=rack_obj.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = NivelForm(rack_fijo=rack_fijo)
    return render(request, 'ubicaciones-niveles-crear.html', {
        'form': form,
        'rack_fijo': rack_fijo,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_nivel(request, pk: int):
    nivel = get_object_or_404(Nivel.objects.select_related('rack'), pk=pk)
    ubicaciones = Ubicacion.objects.filter(nivel=nivel).prefetch_related('productos')
    return render(request, 'ubicaciones-niveles-detalle.html', {
        'nivel': nivel,
        'ubicaciones': ubicaciones,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_nivel(request, pk: int):
    nivel = get_object_or_404(Nivel.objects.select_related('rack'), pk=pk)
    if request.method == 'POST':
        form = NivelForm(request.POST, instance=nivel, rack_fijo=nivel.rack)
        if form.is_valid():
            try:
                UbicacionesService.editar_nivel(
                    nivel=nivel,
                    tipo=form.cleaned_data['tipo'],
                    descripcion=form.cleaned_data['descripcion'],
                    usuario=request.user,
                )
                messages.success(request, f"Nivel '{nivel.codigo}' actualizado.")
                return redirect('ubicaciones-niveles-detalle', pk=nivel.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = NivelForm(instance=nivel, rack_fijo=nivel.rack)
    return render(request, 'ubicaciones-niveles-editar.html', {'form': form, 'nivel': nivel})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_nivel(request, pk: int):
    nivel = get_object_or_404(Nivel.objects.select_related('rack'), pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_nivel(nivel, request.user)
            messages.success(request, f"Nivel '{nivel.codigo}' desactivado.")
            return redirect('ubicaciones-racks-detalle', pk=nivel.rack.pk)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-niveles-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': nivel,
        'tipo': 'nivel',
        'nombre': str(nivel),
    })


# ------------------------------------------------------------------ Ubicaciones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def crear_ubicacion(request):
    nivel_pk = request.GET.get('nivel') or request.POST.get('nivel')
    nivel_fijo = Nivel.objects.select_related('rack').filter(pk=nivel_pk).first() if nivel_pk else None

    if request.method == 'POST':
        form = UbicacionForm(request.POST, nivel_fijo=nivel_fijo)
        if form.is_valid():
            nivel_obj = form.cleaned_data['nivel'] if not nivel_fijo else nivel_fijo
            try:
                ubic = UbicacionesService.crear_ubicacion(
                    nivel=nivel_obj,
                    codigo=form.cleaned_data['codigo'],
                    descripcion=form.cleaned_data['descripcion'],
                    usuario=request.user,
                )
                messages.success(request, f"Ubicación '{ubic.codigo_completo}' creada.")
                return redirect('ubicaciones-niveles-detalle', pk=nivel_obj.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = UbicacionForm(nivel_fijo=nivel_fijo)
    return render(request, 'ubicaciones-ubicaciones-crear.html', {
        'form': form,
        'nivel_fijo': nivel_fijo,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_ubicacion(request, pk: int):
    ubic = get_object_or_404(
        Ubicacion.objects.select_related('nivel__rack'), pk=pk
    )
    asignaciones = ProductoUbicacion.objects.filter(ubicacion=ubic).select_related('asignado_por')

    # Consultar existencias DBISAM en vivo
    codigos = list(asignaciones.values_list('codigo_producto', flat=True))
    existencias: dict = {}
    descripciones: dict = {}
    if codigos:
        try:
            db = PedidosDBISAM()
            existencias = db.consultar_stock_multiple(codigos, deposito=DEPOSITO_ALMACEN)
            for c in codigos:
                prod = db.buscar_producto(c)
                if prod:
                    descripciones[c] = prod[1]
        except Exception:
            logger.exception("Error al consultar DBISAM en detalle_ubicacion")

    productos_info = [
        {
            'pu': pu,
            'existencia': existencias.get(pu.codigo_producto, 0),
            'descripcion': descripciones.get(pu.codigo_producto, ''),
        }
        for pu in asignaciones
    ]

    return render(request, 'ubicaciones-ubicaciones-detalle.html', {
        'ubicacion': ubic,
        'productos_info': productos_info,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_ubicacion(request, pk: int):
    ubic = get_object_or_404(Ubicacion.objects.select_related('nivel__rack'), pk=pk)
    if request.method == 'POST':
        form = UbicacionForm(request.POST, instance=ubic, nivel_fijo=ubic.nivel)
        if form.is_valid():
            try:
                UbicacionesService.editar_ubicacion(
                    ubicacion=ubic,
                    descripcion=form.cleaned_data['descripcion'],
                    usuario=request.user,
                )
                messages.success(request, f"Ubicación '{ubic.codigo_completo}' actualizada.")
                return redirect('ubicaciones-ubicaciones-detalle', pk=ubic.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = UbicacionForm(instance=ubic, nivel_fijo=ubic.nivel)
    return render(request, 'ubicaciones-ubicaciones-editar.html', {'form': form, 'ubicacion': ubic})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_ubicacion(request, pk: int):
    ubic = get_object_or_404(Ubicacion.objects.select_related('nivel__rack'), pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_ubicacion(ubic, request.user)
            messages.success(request, f"Ubicación '{ubic.codigo_completo}' desactivada.")
            return redirect('ubicaciones-niveles-detalle', pk=ubic.nivel.pk)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-ubicaciones-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': ubic,
        'tipo': 'ubicación',
        'nombre': ubic.codigo_completo,
    })


# ------------------------------------------------------------------ Asignaciones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def asignar_producto(request, pk: int):
    ubic = get_object_or_404(Ubicacion.objects.select_related('nivel__rack'), pk=pk)
    form = AsignarProductoForm(request.POST or None)
    resultados_busqueda = []
    query = ''

    if request.method == 'POST' and 'buscar' in request.POST:
        query = request.POST.get('codigo_producto', '').strip()
        if query:
            try:
                db = PedidosDBISAM()
                prod = db.buscar_producto(query.upper())
                if prod:
                    existencia = db.consultar_stock(query.upper(), deposito=DEPOSITO_ALMACEN)
                    resultados_busqueda = [{
                        'codigo': prod[0],
                        'descripcion': prod[1],
                        'referencia': prod[2],
                        'puesto': prod[3],
                        'existencia': existencia,
                    }]
                else:
                    # búsqueda por descripción
                    prods = db.buscar_por_descripcion(query)
                    codigos = [p[0] for p in prods]
                    stocks = db.consultar_stock_multiple(codigos, deposito=DEPOSITO_ALMACEN) if codigos else {}
                    resultados_busqueda = [
                        {
                            'codigo': p[0], 'descripcion': p[1],
                            'referencia': p[2], 'puesto': p[3],
                            'existencia': stocks.get(p[0], 0),
                        }
                        for p in prods
                    ]
            except Exception:
                logger.exception("Error al buscar producto en DBISAM")
                messages.error(request, "Error al conectar con DBISAM.")

    elif request.method == 'POST' and 'asignar' in request.POST:
        codigo = request.POST.get('codigo_asignar', '').strip()
        if codigo:
            try:
                UbicacionesService.asignar_producto(codigo, ubic, request.user)
                messages.success(request, f"Producto '{codigo}' asignado a '{ubic.codigo_completo}'.")
                return redirect('ubicaciones-ubicaciones-detalle', pk=ubic.pk)
            except ValidationError as e:
                messages.error(request, e.message)

    return render(request, 'ubicaciones-asignar.html', {
        'ubicacion': ubic,
        'form': form,
        'resultados_busqueda': resultados_busqueda,
        'query': query,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def quitar_producto(request, pk: int, pu_id: int):
    ubic = get_object_or_404(Ubicacion, pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.quitar_producto(pu_id, request.user)
            messages.success(request, "Producto desasignado correctamente.")
        except Exception as e:
            messages.error(request, str(e))
    return redirect('ubicaciones-ubicaciones-detalle', pk=ubic.pk)


# ------------------------------------------------------------------ Traslado / Fusión

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def trasladar(request):
    form = TrasladarForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            UbicacionesService.trasladar_producto(
                codigo=form.cleaned_data['codigo_producto'],
                ubic_origen=form.cleaned_data['ubicacion_origen'],
                ubic_destino=form.cleaned_data['ubicacion_destino'],
                usuario=request.user,
                notas=form.cleaned_data.get('notas', ''),
            )
            messages.success(request, "Traslado realizado correctamente.")
            return redirect('ubicaciones-movimientos')
        except ValidationError as e:
            messages.error(request, e.message)
    return render(request, 'ubicaciones-trasladar.html', {'form': form})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def fusionar(request):
    form = FusionarForm(request.POST or None)
    preview = None

    if request.method == 'POST':
        if 'preview' in request.POST and form.is_valid():
            ubic_a = form.cleaned_data['ubicacion_a']
            items_a = ProductoUbicacion.objects.filter(ubicacion=ubic_a).count()
            preview = {'ubicacion_a': ubic_a, 'total_productos': items_a}
        elif 'confirmar' in request.POST and form.is_valid():
            try:
                transferidos = UbicacionesService.fusionar_ubicaciones(
                    ubic_a=form.cleaned_data['ubicacion_a'],
                    ubic_b=form.cleaned_data['ubicacion_b'],
                    usuario=request.user,
                    notas=form.cleaned_data.get('notas', ''),
                )
                messages.success(request, f"Fusión completada: {transferidos} producto(s) transferidos.")
                return redirect('ubicaciones-movimientos')
            except ValidationError as e:
                messages.error(request, e.message)

    return render(request, 'ubicaciones-fusionar.html', {'form': form, 'preview': preview})


# ------------------------------------------------------------------ Histórico

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def lista_movimientos(request):
    qs = MovimientoUbicacion.objects.select_related(
        'usuario', 'rack', 'nivel', 'ubicacion_origen', 'ubicacion_destino'
    )
    tipo = request.GET.get('tipo', '')
    codigo = request.GET.get('codigo', '').strip()
    if tipo:
        qs = qs.filter(tipo=tipo)
    if codigo:
        qs = qs.filter(codigo_producto__icontains=codigo)
    return render(request, 'ubicaciones-movimientos.html', {
        'movimientos': qs[:500],
        'tipo_filter': tipo,
        'codigo_filter': codigo,
        'tipos': MovimientoUbicacion.TIPO_CHOICES,
    })


# ------------------------------------------------------------------ Producto → Ubicaciones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def producto_ubicaciones(request, codigo: str):
    codigo = codigo.strip().upper()
    asignaciones = (
        ProductoUbicacion.objects
        .filter(codigo_producto=codigo)
        .select_related('ubicacion__nivel__rack')
    )
    existencia = 0
    descripcion = ''
    try:
        db = PedidosDBISAM()
        prod = db.buscar_producto(codigo)
        if prod:
            descripcion = prod[1]
            existencia = db.consultar_stock(codigo, deposito=DEPOSITO_ALMACEN)
    except Exception:
        logger.exception("Error al consultar DBISAM en producto_ubicaciones")

    return render(request, 'ubicaciones-producto-detalle.html', {
        'codigo': codigo,
        'descripcion': descripcion,
        'existencia': existencia,
        'asignaciones': asignaciones,
    })


# ------------------------------------------------------------------ Fragmentos htmx

@login_required(login_url='/login/')
def buscar_ubicacion_fragment(request):
    """Autocomplete de ubicaciones para formularios de traslado/fusión."""
    q = request.GET.get('q', '').strip()
    qs = Ubicacion.objects.filter(activo=True).select_related('nivel__rack')
    if q:
        qs = qs.filter(codigo__icontains=q) | qs.filter(nivel__rack__codigo__icontains=q)
    return render(request, '_ubicaciones-buscar-ubicacion-fragment.html', {
        'ubicaciones': qs[:20],
    })


@login_required(login_url='/login/')
def buscar_producto_dbisam_fragment(request):
    """Búsqueda de producto en DBISAM para el modal de asignación."""
    q = request.GET.get('q', '').strip()
    resultados = []
    if len(q) >= 2:
        try:
            db = PedidosDBISAM()
            prods = db.buscar_por_descripcion(q)
            codigos = [p[0] for p in prods]
            stocks = db.consultar_stock_multiple(codigos, deposito=DEPOSITO_ALMACEN) if codigos else {}
            resultados = [
                {
                    'codigo': p[0], 'descripcion': p[1],
                    'referencia': p[2], 'puesto': p[3],
                    'existencia': stocks.get(p[0], 0),
                }
                for p in prods
            ]
        except Exception:
            logger.exception("Error en buscar_producto_dbisam_fragment")
    return render(request, '_ubicaciones-buscar-producto-fragment.html', {
        'resultados': resultados,
    })
