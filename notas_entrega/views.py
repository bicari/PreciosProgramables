from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from tasks.dbisam import DBISAMDatabase
from django.http import HttpResponse, JsonResponse, HttpResponseNotAllowed
import json
from .utils import send_notification, calcular_totales
from .pdf import generar_factura, generar_reporte_notas
from .serializers import NotaEntregaSerializer
import logging
import base64

logger = logging.getLogger(__name__)


@login_required(login_url='/login/')
def render_notas_entrega(request):
    return render(request, 'notas-entrega.html')


@login_required(login_url='/login/')
def search_product_by_code(request):
    try:
        sku = request.GET.get('sku', '')
        dbisam = DBISAMDatabase()
        result = dbisam.search_product(sku)
        if not result:
            return HttpResponse(content='Producto no encontrado o inactivo', status=404)
        return render(request, 'search_product.html', {
            'Codigo': result[0], 'Descripcion': result[1], 'CostoBs': result[2],
            'CostoUsd': result[3], 'Iva': result[4], 'Puesto': result[5],
            'Referencia': result[6], 'Ref_proveedor': result[7],
        })
    except Exception as e:
        logger.exception('search_product_by_code error')
        return HttpResponse(content=str(e), status=500)


@login_required(login_url='/login/')
def search_product_by_description(request):
    try:
        description = request.GET.get('description', '').upper()
        dbisam = DBISAMDatabase()
        result = dbisam.search_product_by_description(description)
        json_result = [
            {
                'Codigo': row[0], 'Descripcion': row[1], 'Departamento': row[2],
                'CostoBS': row[3], 'CostoUS': row[4], 'Iva': row[5],
                'Puesto': row[6], 'Referencia': row[7], 'Ref_proveedor': row[8],
            }
            for row in result
        ]
        return render(request, 'search_description.html', {'products': json_result})
    except Exception as e:
        logger.exception('search_product_by_description error')
        return HttpResponse(content=f"Error al procesar la solicitud {e}", status=500)


@login_required(login_url='/login/')
def search_proveedor_by_description(request):
    try:
        description = request.GET.get('description_proveedor', '').upper()
        dbisam = DBISAMDatabase()
        result = dbisam.search_proveedor_by_description(description)
        json_result = [{'Codigo': row[0], 'Descripcion': row[1], 'Direccion': row[2]} for row in result]
        return render(request, 'search_description_proveedor.html', {'proveedores': json_result})
    except Exception as e:
        logger.exception('search_proveedor_by_description error')
        return HttpResponse(content=f"Error al procesar la solicitud {e}", status=500)


@login_required(login_url='/login/')
def modal_search(request):
    return render(request, 'modal_search.html')


@login_required(login_url='/login/')
def modal_search_proveedor(request):
    return render(request, 'modal_search_proveedor.html')


@login_required(login_url='/login/')
def search_order(request):
    try:
        data = request.GET.get('data', '').upper()
        proveedor = request.GET.get('proveedor', '').upper()
        order_number = data.split(',')
        dbisam = DBISAMDatabase()
        result = dbisam.search_order(order_number, proveedor)
        if len(result) > 0:
            json_result = [
                {
                    'Codigo': row[0], 'Documento': row[2], 'Cantidad': row[1],
                    'Costo': row[3], 'Iva': row[4], 'Moneda': row[5],
                    'Deposito': row[6], 'Descripcion': row[7], 'Autoincrement': row[8],
                    'Puesto': row[9], 'Referencia': row[10], 'Ref_proveedor': row[11],
                    'Iva_16_monto': row[12], 'Comentario': row[13],
                }
                for row in result
            ]
            return render(request, 'search_description.html', {'products': json_result, 'is_order': True})
        return HttpResponse(content='No se encontraron resultados', status=404)
    except Exception as e:
        logger.error('search_order error: %s', e)
        return HttpResponse(content=f"Error al procesar la solicitud {e}", status=500)


@login_required(login_url='/login/')
def search_proveedor(request):
    try:
        data = request.GET.get('proveedor', '').upper()
        dbisam = DBISAMDatabase()
        result = dbisam.search_proveedor(data)
        if result:
            return render(request, 'card-proveedor.html', {
                'proveedor': f"{result[0]}-{result[1]}",
                'direccion_proveedor': result[2],
            })
        return HttpResponse(content=f"Código Proveedor '{data}' no encontrado", status=404)
    except Exception as e:
        logger.error('search_proveedor error: %s', e)
        return HttpResponse(content=f"Error al procesar la solicitud {e}")


@login_required(login_url='/login/')
def procesar_recepcion(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({'status': False, 'error': 'JSON inválido'}, status=400)

    serializer = NotaEntregaSerializer(data=payload)
    if not serializer.is_valid():
        return JsonResponse({'status': False, 'errors': serializer.errors}, status=400)

    try:
        data = dict(serializer.validated_data)
        data['usuario'] = request.user.username
        dbisam = DBISAMDatabase()
        dict_nota_entrega = calcular_totales(data)
        result = dbisam.insert_notas_entrega(dict_nota_entrega)
        nro_nota_entrega = result['nro_nota']
        dict_nota_entrega['id'] = nro_nota_entrega
        request.session['nota_entrega'] = nro_nota_entrega
        nota_pdf = generar_factura('factura.pdf', dict_nota_entrega, 'static/KsaHome.png', preliminar=True)
        email_enviado = True
        try:
            send_notification(dict_nota_entrega, nro_nota_entrega, nota_pdf)
        except Exception:
            email_enviado = False
            logger.exception('send_notification failed (nota %s ya insertada en a2)',
                             nro_nota_entrega, extra={'user': request.user.username})
        request.session['nota_entrega_email_ok'] = email_enviado
        pdf_64 = base64.b64encode(nota_pdf).decode('utf-8')
        return JsonResponse({'status': True, 'redirect_url': '/confirmar-nota-entrega/', 'document': pdf_64}, status=200)
    except ValueError as e:
        logger.warning('validacion payload procesar_recepcion: %s', e, extra={'user': request.user.username})
        return JsonResponse({'status': False, 'error': str(e)}, status=400)
    except Exception as e:
        logger.exception('procesar_recepcion failed', extra={'user': request.user.username})
        return JsonResponse({'status': False, 'error': 'Error interno al procesar la nota'}, status=500)


@login_required(login_url='/login/')
def preliminar_recepcion(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': False, 'error': 'JSON inválido'}, status=400)

    serializer = NotaEntregaSerializer(data=payload)
    if not serializer.is_valid():
        return JsonResponse({'status': False, 'errors': serializer.errors}, status=400)

    try:
        data = dict(serializer.validated_data)
        data['usuario'] = request.user.username
        data['id'] = 'PRELIMINAR'
        dict_nota = calcular_totales(data)
        pdf_bytes = generar_factura('preliminar.pdf', dict_nota, 'static/KsaHome.png', preliminar=True)
        pdf_64 = base64.b64encode(pdf_bytes).decode('utf-8')
        return JsonResponse({'status': True, 'total_neto': dict_nota['total_neto'], 'document': pdf_64}, status=200)
    except Exception as e:
        logger.exception('preliminar_recepcion failed', extra={'user': request.user.username})
        return JsonResponse({'status': False, 'error': 'Error al generar el preliminar'}, status=500)


@login_required(login_url='/login/')
def obtener_confirmacion(request):
    nro_nota_entrega = request.session.pop('nota_entrega', {})
    email_ok = request.session.pop('nota_entrega_email_ok', True)
    return render(request, 'confirm-nota.html', context={'document': nro_nota_entrega, 'email_ok': email_ok})


@login_required(login_url='/login/')
def consultar_notas(request):
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    notas = []

    if fecha_desde and fecha_hasta:
        try:
            dbisam = DBISAMDatabase()
            rows = dbisam.consultar_notas_entrega(fecha_desde, fecha_hasta)
            notas = [
                {
                    'documento': row[0],
                    'total_items': int(row[1]) if row[1] else 0,
                    'fecha': row[2].strftime('%d/%m/%Y') if row[2] else '',
                    'rif': row[3] or '',
                    'proveedor': row[4] or 'Sin proveedor',
                    'total_neto': float(row[5]) if row[5] else 0,
                    'moneda': 'Bs' if str(row[6]) == '1' else 'USD',
                }
                for row in rows
            ]
        except Exception as e:
            logger.error('consultar_notas error: %s', e)

    if request.GET.get('formato') == 'pdf' and notas:
        pdf_bytes = generar_reporte_notas(notas, fecha_desde, fecha_hasta)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="reporte_notas_{fecha_desde}_{fecha_hasta}.pdf"'
        return response

    return render(request, 'consultar-notas.html', {
        'notas': notas,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    })


@login_required(login_url='/login/')
def delete_product(request):
    if request.method == 'POST':
        return HttpResponse(status=200)
