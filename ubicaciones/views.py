import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db.models import Exists, F, OuterRef
from django.shortcuts import get_object_or_404, redirect, render

from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM

from .forms import (
    AsignarProductoAccionForm,
    CuerpoForm,
    EditarCantidadForm,
    FusionarForm,
    GalponForm,
    NivelForm,
    RackForm,
    TrasladarForm,
    UbicacionForm,
)
from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion
from .services import UbicacionesService

logger = logging.getLogger(__name__)

GROUP_UBICACIONES = 'Pedidos Ubicaciones'


def is_ubicaciones(user) -> bool:
    return user.groups.filter(name=GROUP_UBICACIONES).exists() or user.is_superuser


# ------------------------------------------------------------------ Galpones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def lista_galpones(request):
    solo_activos = request.GET.get('activo', '1')
    qs = Galpon.objects.prefetch_related('racks')
    if solo_activos == '1':
        qs = qs.filter(activo=True)
    return render(request, 'ubicaciones-galpones-lista.html', {
        'galpones': qs,
        'solo_activos': solo_activos,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def crear_galpon(request):
    if request.method == 'POST':
        form = GalponForm(request.POST)
        if form.is_valid():
            try:
                galpon = UbicacionesService.crear_galpon(
                    codigo=form.cleaned_data['codigo'],
                    nombre=form.cleaned_data['nombre'],
                    grid_filas=form.cleaned_data['grid_filas'],
                    grid_columnas=form.cleaned_data['grid_columnas'],
                    usuario=request.user,
                )
                messages.success(request, f"Galpón '{galpon.codigo}' creado correctamente.")
                return redirect('ubicaciones-galpones-detalle', pk=galpon.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = GalponForm()
    return render(request, 'ubicaciones-galpones-crear.html', {'form': form})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_galpon(request, pk: int):
    galpon = get_object_or_404(Galpon, pk=pk)
    racks = Rack.objects.filter(galpon=galpon).prefetch_related('cuerpos')
    return render(request, 'ubicaciones-galpones-detalle.html', {
        'galpon': galpon,
        'racks': racks,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_galpon(request, pk: int):
    galpon = get_object_or_404(Galpon, pk=pk)
    if request.method == 'POST':
        form = GalponForm(request.POST, instance=galpon)
        if form.is_valid():
            try:
                UbicacionesService.editar_galpon(
                    galpon=galpon,
                    nombre=form.cleaned_data['nombre'],
                    grid_filas=form.cleaned_data['grid_filas'],
                    grid_columnas=form.cleaned_data['grid_columnas'],
                    usuario=request.user,
                )
                messages.success(request, f"Galpón '{galpon.codigo}' actualizado.")
                return redirect('ubicaciones-galpones-detalle', pk=galpon.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = GalponForm(instance=galpon)
    return render(request, 'ubicaciones-galpones-editar.html', {'form': form, 'galpon': galpon})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_galpon(request, pk: int):
    galpon = get_object_or_404(Galpon, pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_galpon(galpon, request.user)
            messages.success(request, f"Galpón '{galpon.codigo}' desactivado.")
            return redirect('ubicaciones-galpones-lista')
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-galpones-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': galpon, 'tipo': 'galpón', 'nombre': galpon.codigo,
    })


# ------------------------------------------------------------------ Racks

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def crear_rack(request, galpon_pk: int):
    galpon = get_object_or_404(Galpon, pk=galpon_pk)
    if request.method == 'POST':
        form = RackForm(request.POST)
        if form.is_valid():
            try:
                rack = UbicacionesService.crear_rack(
                    galpon=galpon,
                    codigo=form.cleaned_data['codigo'],
                    descripcion=form.cleaned_data['descripcion'],
                    grid_fila=form.cleaned_data['grid_fila'],
                    grid_columna=form.cleaned_data['grid_columna'],
                    ancho=form.cleaned_data['ancho'],
                    alto=form.cleaned_data['alto'],
                    max_niveles=form.cleaned_data['max_niveles'],
                    usuario=request.user,
                )
                messages.success(request, f"Rack '{rack.codigo}' creado correctamente.")
                return redirect('ubicaciones-racks-detalle', pk=rack.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = RackForm()
    return render(request, 'ubicaciones-racks-crear.html', {'form': form, 'galpon': galpon})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_rack(request, pk: int):
    rack = get_object_or_404(Rack.objects.select_related('galpon'), pk=pk)
    cuerpos = rack.cuerpos.prefetch_related('ubicaciones__niveles')
    return render(request, 'ubicaciones-racks-detalle.html', {
        'rack': rack,
        'cuerpos': cuerpos,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_rack(request, pk: int):
    rack = get_object_or_404(Rack.objects.select_related('galpon'), pk=pk)
    bloquear = rack.cuerpos.exists()
    if request.method == 'POST':
        form = RackForm(request.POST, instance=rack, bloquear_max_niveles=bloquear)
        if form.is_valid():
            try:
                UbicacionesService.editar_rack(
                    rack=rack,
                    descripcion=form.cleaned_data['descripcion'],
                    grid_fila=form.cleaned_data['grid_fila'],
                    grid_columna=form.cleaned_data['grid_columna'],
                    ancho=form.cleaned_data['ancho'],
                    alto=form.cleaned_data['alto'],
                    max_niveles=form.cleaned_data['max_niveles'],
                    usuario=request.user,
                )
                messages.success(request, f"Rack '{rack.codigo}' actualizado.")
                return redirect('ubicaciones-racks-detalle', pk=rack.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = RackForm(instance=rack, bloquear_max_niveles=bloquear)
    return render(request, 'ubicaciones-racks-editar.html', {'form': form, 'rack': rack})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_rack(request, pk: int):
    rack = get_object_or_404(Rack, pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_rack(rack, request.user)
            messages.success(request, f"Rack '{rack.codigo}' desactivado.")
            return redirect('ubicaciones-galpones-detalle', pk=rack.galpon_id)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-racks-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': rack, 'tipo': 'rack', 'nombre': rack.codigo,
    })


# ------------------------------------------------------------------ Cuerpos

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def crear_cuerpo(request, rack_pk: int):
    rack = get_object_or_404(Rack, pk=rack_pk)
    if request.method == 'POST':
        form = CuerpoForm(request.POST)
        if form.is_valid():
            try:
                cuerpo = UbicacionesService.crear_cuerpo(
                    rack=rack, descripcion=form.cleaned_data['descripcion'], usuario=request.user,
                )
                messages.success(request, f"Cuerpo '{cuerpo.codigo}' creado con sus ubicaciones y niveles.")
                return redirect('ubicaciones-racks-detalle', pk=rack.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = CuerpoForm()
    return render(request, 'ubicaciones-cuerpos-crear.html', {'form': form, 'rack': rack})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_cuerpo(request, pk: int):
    cuerpo = get_object_or_404(Cuerpo.objects.select_related('rack__galpon'), pk=pk)
    ubicaciones = cuerpo.ubicaciones.prefetch_related('niveles')
    return render(request, 'ubicaciones-cuerpos-detalle.html', {
        'cuerpo': cuerpo,
        'ubicaciones': ubicaciones,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_cuerpo(request, pk: int):
    cuerpo = get_object_or_404(Cuerpo.objects.select_related('rack__galpon'), pk=pk)
    if request.method == 'POST':
        form = CuerpoForm(request.POST, instance=cuerpo)
        if form.is_valid():
            cuerpo.descripcion = form.cleaned_data['descripcion']
            cuerpo.save(update_fields=['descripcion', 'fecha_modificacion'])
            messages.success(request, f"Cuerpo '{cuerpo.codigo}' actualizado.")
            return redirect('ubicaciones-cuerpos-detalle', pk=cuerpo.pk)
    else:
        form = CuerpoForm(instance=cuerpo)
    return render(request, 'ubicaciones-cuerpos-editar.html', {'form': form, 'cuerpo': cuerpo})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_cuerpo(request, pk: int):
    cuerpo = get_object_or_404(Cuerpo.objects.select_related('rack__galpon'), pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_cuerpo(cuerpo, request.user)
            messages.success(request, f"Cuerpo '{cuerpo.codigo}' desactivado.")
            return redirect('ubicaciones-racks-detalle', pk=cuerpo.rack_id)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-cuerpos-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': cuerpo, 'tipo': 'cuerpo', 'nombre': cuerpo.codigo,
    })


# ------------------------------------------------------------------ Ubicaciones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_ubicacion(request, pk: int):
    ubicacion = get_object_or_404(Ubicacion.objects.select_related('cuerpo__rack__galpon'), pk=pk)
    niveles = ubicacion.niveles.select_related('fusionado_en').prefetch_related('productos')
    return render(request, 'ubicaciones-ubicaciones-detalle.html', {
        'ubicacion': ubicacion,
        'niveles': niveles,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_ubicacion(request, pk: int):
    ubicacion = get_object_or_404(Ubicacion.objects.select_related('cuerpo__rack__galpon'), pk=pk)
    if request.method == 'POST':
        form = UbicacionForm(request.POST, instance=ubicacion)
        if form.is_valid():
            ubicacion.descripcion = form.cleaned_data['descripcion']
            ubicacion.save(update_fields=['descripcion', 'fecha_modificacion'])
            messages.success(request, f"Ubicación '{ubicacion.codigo}' actualizada.")
            return redirect('ubicaciones-ubicaciones-detalle', pk=ubicacion.pk)
    else:
        form = UbicacionForm(instance=ubicacion)
    return render(request, 'ubicaciones-ubicaciones-editar.html', {'form': form, 'ubicacion': ubicacion})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_ubicacion(request, pk: int):
    ubicacion = get_object_or_404(Ubicacion.objects.select_related('cuerpo__rack__galpon'), pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_ubicacion(ubicacion, request.user)
            messages.success(request, f"Ubicación '{ubicacion.codigo}' desactivada.")
            return redirect('ubicaciones-cuerpos-detalle', pk=ubicacion.cuerpo_id)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-ubicaciones-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': ubicacion, 'tipo': 'ubicación', 'nombre': ubicacion.codigo,
    })


# ------------------------------------------------------------------ Niveles

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_nivel(request, pk: int):
    nivel = get_object_or_404(
        Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon', 'fusionado_en'), pk=pk,
    )
    productos = nivel.productos.all()
    return render(request, 'ubicaciones-niveles-detalle.html', {
        'nivel': nivel,
        'productos': productos,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_nivel(request, pk: int):
    nivel = get_object_or_404(Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon'), pk=pk)
    if request.method == 'POST':
        form = NivelForm(request.POST, instance=nivel)
        if form.is_valid():
            try:
                UbicacionesService.editar_nivel(
                    nivel=nivel, tipo=form.cleaned_data['tipo'],
                    descripcion=form.cleaned_data['descripcion'], usuario=request.user,
                )
                messages.success(request, f"Nivel '{nivel.codigo_completo}' actualizado.")
                return redirect('ubicaciones-niveles-detalle', pk=nivel.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = NivelForm(instance=nivel)
    return render(request, 'ubicaciones-niveles-editar.html', {'form': form, 'nivel': nivel})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_nivel(request, pk: int):
    nivel = get_object_or_404(Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon'), pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_nivel(nivel, request.user)
            messages.success(request, f"Nivel '{nivel.codigo_completo}' desactivado.")
            return redirect('ubicaciones-ubicaciones-detalle', pk=nivel.ubicacion_id)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-niveles-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': nivel, 'tipo': 'nivel', 'nombre': nivel.codigo_completo,
    })


# ------------------------------------------------------------------ Asignaciones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def asignar_producto(request, pk: int):
    nivel = get_object_or_404(Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon'), pk=pk)
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
                        'codigo': prod[0], 'descripcion': prod[1],
                        'referencia': prod[2], 'puesto': prod[3], 'existencia': existencia,
                    }]
                else:
                    prods = db.buscar_por_descripcion(query)
                    codigos = [p[0] for p in prods]
                    stocks = db.consultar_stock_multiple(codigos, deposito=DEPOSITO_ALMACEN) if codigos else {}
                    resultados_busqueda = [
                        {'codigo': p[0], 'descripcion': p[1], 'referencia': p[2], 'puesto': p[3],
                         'existencia': stocks.get(p[0], 0)}
                        for p in prods
                    ]
            except Exception:
                logger.exception("Error al buscar producto en DBISAM")
                messages.error(request, "Error al conectar con DBISAM.")

    elif request.method == 'POST' and 'asignar' in request.POST:
        form = AsignarProductoAccionForm(request.POST)
        if form.is_valid():
            try:
                UbicacionesService.asignar_producto(
                    codigo=form.cleaned_data['codigo_producto'],
                    nivel=nivel,
                    cantidad=form.cleaned_data['cantidad'],
                    stock_minimo=form.cleaned_data.get('stock_minimo'),
                    usuario=request.user,
                )
                messages.success(request, f"Producto asignado a '{nivel.codigo_completo}'.")
                return redirect('ubicaciones-niveles-detalle', pk=nivel.pk)
            except ValidationError as e:
                messages.error(request, e.message)

    return render(request, 'ubicaciones-asignar.html', {
        'nivel': nivel,
        'resultados_busqueda': resultados_busqueda,
        'query': query,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_cantidad(request, pu_id: int):
    pu = get_object_or_404(ProductoUbicacion.objects.select_related('nivel'), pk=pu_id)
    if request.method == 'POST':
        form = EditarCantidadForm(request.POST)
        if form.is_valid():
            try:
                UbicacionesService.editar_cantidad(
                    pu, form.cleaned_data['cantidad'], form.cleaned_data.get('stock_minimo'), request.user,
                )
                messages.success(request, "Cantidad actualizada.")
            except ValidationError as e:
                messages.error(request, e.message)
    return redirect('ubicaciones-niveles-detalle', pk=pu.nivel_id)


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def quitar_producto(request, pu_id: int):
    pu = get_object_or_404(ProductoUbicacion, pk=pu_id)
    nivel_id = pu.nivel_id
    if request.method == 'POST':
        try:
            UbicacionesService.quitar_producto(pu_id, request.user)
            messages.success(request, "Producto desasignado correctamente.")
        except Exception as e:
            messages.error(request, str(e))
    return redirect('ubicaciones-niveles-detalle', pk=nivel_id)


# ------------------------------------------------------------------ Traslado / Fusión

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def trasladar(request):
    form = TrasladarForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            UbicacionesService.trasladar_producto(
                codigo=form.cleaned_data['codigo_producto'],
                nivel_origen=form.cleaned_data['nivel_origen'],
                nivel_destino=form.cleaned_data['nivel_destino'],
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
    if request.method == 'POST' and form.is_valid():
        try:
            transferidos = UbicacionesService.fusionar_niveles(
                niveles=list(form.cleaned_data['niveles']),
                maestro=form.cleaned_data['maestro'],
                usuario=request.user,
                notas=form.cleaned_data.get('notas', ''),
            )
            messages.success(request, f"Fusión completada: {transferidos} asignación(es) consolidadas.")
            return redirect('ubicaciones-movimientos')
        except ValidationError as e:
            messages.error(request, e.message)
    return render(request, 'ubicaciones-fusionar.html', {'form': form})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desfusionar(request, pk: int):
    nivel = get_object_or_404(Nivel, pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desfusionar_nivel(nivel, request.user)
            messages.success(request, f"Nivel '{nivel.codigo_completo}' desfusionado.")
        except ValidationError as e:
            messages.error(request, e.message)
    return redirect('ubicaciones-niveles-detalle', pk=pk)


# ------------------------------------------------------------------ Histórico

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def lista_movimientos(request):
    qs = MovimientoUbicacion.objects.select_related('usuario', 'rack', 'nivel_origen', 'nivel_destino')
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
        .select_related('nivel__ubicacion__cuerpo__rack__galpon')
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
        'codigo': codigo, 'descripcion': descripcion, 'existencia': existencia,
        'asignaciones': asignaciones,
    })


# ------------------------------------------------------------------ Fragmentos htmx

@login_required(login_url='/login/')
def buscar_nivel_fragment(request):
    """Autocomplete de niveles para formularios de traslado/fusión."""
    q = request.GET.get('q', '').strip()
    qs = Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack')
    if q:
        qs = qs.filter(ubicacion__cuerpo__rack__codigo__icontains=q)
    return render(request, '_ubicaciones-buscar-nivel-fragment.html', {'niveles': qs[:20]})


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
                {'codigo': p[0], 'descripcion': p[1], 'referencia': p[2], 'puesto': p[3],
                 'existencia': stocks.get(p[0], 0)}
                for p in prods
            ]
        except Exception:
            logger.exception("Error en buscar_producto_dbisam_fragment")
    return render(request, '_ubicaciones-buscar-producto-fragment.html', {'resultados': resultados})


# ------------------------------------------------------------------ Alertas

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def alertas_stock(request):
    alertas = (
        ProductoUbicacion.objects
        .filter(nivel__tipo=Nivel.PICKING, nivel__activo=True, stock_minimo__isnull=False)
        .filter(cantidad__lt=F('stock_minimo'))
        .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        .order_by('nivel__ubicacion__cuerpo__rack__galpon__codigo', 'nivel__ubicacion__cuerpo__rack__codigo')
    )
    return render(request, 'ubicaciones-alertas.html', {'alertas': alertas})


# ------------------------------------------------------------------ Mapa

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def mapa_galpon(request, pk: int):
    galpon = get_object_or_404(Galpon, pk=pk)
    alerta_qs = ProductoUbicacion.objects.filter(
        nivel__ubicacion__cuerpo__rack=OuterRef('pk'),
        nivel__tipo=Nivel.PICKING, stock_minimo__isnull=False, cantidad__lt=F('stock_minimo'),
    )
    fusion_qs = Nivel.objects.filter(ubicacion__cuerpo__rack=OuterRef('pk'), fusionado_en__isnull=False)
    racks = galpon.racks.filter(activo=True).annotate(
        tiene_alertas=Exists(alerta_qs), tiene_fusion=Exists(fusion_qs),
    )
    return render(request, 'ubicaciones-mapa-galpon.html', {'galpon': galpon, 'racks': racks})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def mapa_rack(request, pk: int):
    rack = get_object_or_404(Rack.objects.select_related('galpon'), pk=pk)
    cuerpos = rack.cuerpos.filter(activo=True).prefetch_related('ubicaciones__niveles')
    return render(request, 'ubicaciones-mapa-rack.html', {'rack': rack, 'cuerpos': cuerpos})
