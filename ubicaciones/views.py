import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .forms import GalponForm, RackForm
from .models import Galpon, Rack
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
