import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CuerpoForm, GalponForm, NivelForm, RackForm, UbicacionForm
from .models import Cuerpo, Galpon, Nivel, Rack, Ubicacion
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
