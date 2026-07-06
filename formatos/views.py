"""Vistas de gestión de plantillas de impresión (solo superusuarios)."""
import json
import logging
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.safestring import SafeString
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from reportbro import Report, ReportBroError

from .contratos import datos_ejemplo
from .generacion import validar_plantilla
from .models import (
    PlantillaImpresion, ReportePreview, TIPOS_VALIDOS, obtener_plantilla,
)

logger = logging.getLogger(__name__)

_es_superusuario = user_passes_test(lambda u: u.is_superuser, login_url='dashboard')


def _tipo_valido(tipo: str) -> bool:
    return tipo in TIPOS_VALIDOS


@login_required(login_url='/login/')
@_es_superusuario
def lista_formatos(request):
    plantillas = {p.tipo: p for p in PlantillaImpresion.objects.all()}
    filas = [{
        'tipo': tipo,
        'nombre': dict(PlantillaImpresion.TIPO_CHOICES)[tipo],
        'plantilla': plantillas.get(tipo),
    } for tipo in TIPOS_VALIDOS]
    return render(request, 'formatos-lista.html', {'filas': filas})


@login_required(login_url='/login/')
@_es_superusuario
def disenar(request, tipo):
    if not _tipo_valido(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    plantilla = obtener_plantilla(tipo)
    return render(request, 'formatos-disenar.html', {
        'tipo': tipo,
        'nombre': dict(PlantillaImpresion.TIPO_CHOICES)[tipo],
        'definicion_json': SafeString(json.dumps(plantilla.definicion)),
    })


@csrf_exempt
def report_run(request, tipo):
    """Preview del diseñador (protocolo ReportBro: PUT genera, GET descarga).

    csrf_exempt porque el diseñador hace el PUT internamente sin token;
    el acceso queda protegido por sesión de superusuario.
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return HttpResponseForbidden()
    if not _tipo_valido(tipo):
        return HttpResponseBadRequest('tipo desconocido')

    if request.method == 'PUT':
        try:
            json_data = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return HttpResponseBadRequest('JSON inválido')
        if not isinstance(json_data, dict) or not isinstance(json_data.get('report'), dict):
            return HttpResponseBadRequest('invalid report values')
        if json_data.get('outputFormat') != 'pdf':
            return HttpResponseBadRequest('outputFormat inválido (solo pdf)')

        # Preview siempre con datos reales del último documento (decisión de spec)
        datos = datos_ejemplo(tipo)
        try:
            report = Report(json_data['report'], datos)
        except Exception as exc:  # noqa: BLE001
            return HttpResponseBadRequest(f'failed to initialize report: {exc}')
        if report.errors:
            return HttpResponse(json.dumps({'errors': report.errors}))
        try:
            ReportePreview.objects.filter(
                creado__lt=timezone.now() - timedelta(minutes=10)).delete()
            pdf = report.generate_pdf()
        except ReportBroError as err:
            return HttpResponse(json.dumps({'errors': [err.error]}))
        key = str(uuid.uuid4())
        ReportePreview.objects.create(key=key, pdf=pdf)
        return HttpResponse('key:' + key)

    if request.method == 'GET':
        preview = ReportePreview.objects.filter(key=request.GET.get('key', '')).first()
        if preview is None:
            return HttpResponseBadRequest(
                'preview no encontrado (expiró) — vuelve a generar la vista previa')
        response = HttpResponse(bytes(preview.pdf), content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="preview.pdf"'
        return response

    return HttpResponseBadRequest('método no soportado')


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def guardar(request, tipo):
    if not _tipo_valido(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    try:
        definicion = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest('JSON inválido')
    # Chequeo estructural mínimo (mismo criterio que el demo oficial de ReportBro)
    if not isinstance(definicion, dict) or \
            not isinstance(definicion.get('docElements'), list) or \
            not isinstance(definicion.get('parameters'), list) or \
            not isinstance(definicion.get('styles'), list) or \
            not isinstance(definicion.get('documentProperties'), dict) or \
            not isinstance(definicion.get('version'), int):
        return HttpResponseBadRequest('definición incompleta')
    plantilla = obtener_plantilla(tipo)
    plantilla.actualizar_definicion(definicion, request.user)
    return HttpResponse('ok')


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def activar(request, tipo):
    if not _tipo_valido(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    plantilla = obtener_plantilla(tipo)
    error = validar_plantilla(plantilla.definicion, datos_ejemplo(tipo))
    if error:
        messages.error(
            request,
            f'No se activó: la plantilla no genera un PDF válido. Detalle: {error}')
    else:
        plantilla.activa = True
        plantilla.save(update_fields=['activa'])
        messages.success(request, f'Plantilla de {tipo} activada.')
    return redirect('formatos-lista')


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def desactivar(request, tipo):
    if not _tipo_valido(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    PlantillaImpresion.objects.filter(tipo=tipo).update(activa=False)
    messages.success(request, f'Plantilla de {tipo} desactivada — los PDFs vuelven '
                              f'al formato clásico.')
    return redirect('formatos-lista')


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def restaurar(request, tipo):
    if not _tipo_valido(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    plantilla = obtener_plantilla(tipo)
    if plantilla.restaurar():
        messages.success(request, 'Versión anterior restaurada.')
    else:
        messages.warning(request, 'No hay versión anterior que restaurar.')
    return redirect('formatos-lista')
