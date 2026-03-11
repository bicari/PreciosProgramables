from django.shortcuts import render
from django.http import request
from django.contrib.auth.decorators import login_required, user_passes_test
from tasks.dbisam import DBISAMDatabase
from django.http import HttpResponse, JsonResponse
import json
from django.views.decorators.csrf import csrf_exempt
from .utils import send_notification, calcular_totales
from .pdf import generar_factura
import logging
import base64

logger = logging.getLogger(__name__)
# Create your views here.

def render_notas_entrega(request):
    return render(request, 'notas-entrega.html')

def search_product_by_code(request):
    try:
        sku = request.GET.get('sku', '')
        dbisam = DBISAMDatabase()
        result = dbisam.search_product(sku)
        if not result:
            return HttpResponse(content='Producto no encontrado o inactivo', status=404)
        return render(request, 'search_product.html', {'Codigo': result[0], 'Descripcion': result[1], 'CostoBs': result[2], 'CostoUsd': result[3], 'Iva': result[4], 'Puesto':result[5], 'Referencia': result[6], 'Ref_proveedor': result[7]})
    except Exception as e:
        return HttpResponse(content=str(e), status=500)

def search_product_by_description(request):
    try:
        print(request)
        description = request.GET.get('description', '').upper()
        dbisam = DBISAMDatabase()
        result = dbisam.search_product_by_description(description)
        json_result = [{'Codigo': row[0], 'Descripcion': row[1], 'Departamento': row[2], 'CostoBS':row[3], 'CostoUS': row[4],
                        'Iva':row[5], 'Puesto':[6], 'Referencia': result[7], 'Ref_proveedor': result[8]} for row in result]
        
        return render(request, 'search_description.html', {'products': json_result})
    except Exception as e:
        return HttpResponse(content=f"Error al procesar la solicitud {e}", status=500)

def search_proveedor_by_description(request):
    try:
        description = request.GET.get('description_proveedor', '').upper()
        dbisam = DBISAMDatabase()
        result = dbisam.search_proveedor_by_description(description)
        json_result = [{'Codigo': row[0], 'Descripcion': row[1], 'Direccion': row[2]} for row in result]
        print(json_result)
        return render(request, 'search_description_proveedor.html', {'proveedores': json_result})
    except Exception as e:
        print(e)
        return HttpResponse(content=f"Error al procesar la solicitud {e}", status=500)    

def modal_search(request):
    return render(request, 'modal_search.html')


def modal_search_proveedor(request):
    return render(request, 'modal_search_proveedor.html')

def search_order(request):
    try:
        print(request)
        data = request.GET.get('data', '').upper()
        proveedor = request.GET.get('proveedor', '').upper()
        order_number = data.split(',')
        print('numero de orden', order_number, 'codigo proveedor', proveedor)
        dbisam = DBISAMDatabase()
        result = dbisam.search_order(order_number, proveedor)
        if len(result) > 0:
            json_result = [{'Codigo': row[0], 'Documento': row[2], 
                            'Cantidad': row[1], 'Costo': row[3], 
                            'Iva': row[4], 'Moneda':row[5],
                            'Deposito': row[6], 'Descripcion':row[7],
                            'Autoincrement': row[8],
                            'Puesto': row[9],
                            'Referencia': row[10],
                            'Ref_proveedor': row[11],
                            'Iva_16_monto': row[12],
                            'Comentario': row[13]}  for row in result]
            return render(request, 'search_description.html', {'products': json_result, 'is_order': True})
        else:
            return HttpResponse(content='No se encontraron resultados', status=404)
            #return HttpResponse("No se encontraron resultados", status=404)
    except Exception as e:
        logger.error(e)
        return HttpResponse(content=f"Error al procesar la solicitud {e}", status=500)

def search_proveedor(request: request ):
    try:
        data = request.GET.get('proveedor', '').upper()
        dbisam = DBISAMDatabase()
        result = dbisam.search_proveedor(data)
        print(result)
        if result:
           return render(request, 'card-proveedor.html',{"proveedor": f"{result[0]}-{result[1]}", "direccion_proveedor": result[2]})
        return HttpResponse(content=f"Código Proveedor '{data}' no encontrado", status=404)
    except Exception as e:
        logger.error(e)
        return HttpResponse(content=f"Error al procesar la solicitud {e}")    

def procesar_recepcion(request):
    try:
        if request.method == 'POST':
            request_frontend = json.loads(request.body)
            request_frontend['usuario'] = request.user.username
            print(request_frontend)
            dbisam = DBISAMDatabase()
            nro_nota_entrega = dbisam.notas_entrega_correlativo()
            request.session['nota_entrega'] = nro_nota_entrega
            request_frontend['id'] = nro_nota_entrega
            dict_nota_entrega = calcular_totales(request_frontend)
            result = dbisam.insert_notas_entrega(dict_nota_entrega, nro_nota_entrega)
            if not isinstance(result, Exception):
                nota_pdf = generar_factura('factura.pdf', dict_nota_entrega, 'static/KsaHome.png', preliminar=True)
                send_notification(dict_nota_entrega, nro_nota_entrega, nota_pdf)
                pdf_64 = base64.b64encode(nota_pdf).decode('utf-8')
                return JsonResponse({'status': True, 'redirect_url': '/confirmar-nota-entrega/', 'document': pdf_64}, status=200)
            return JsonResponse({'status': False, 'error': str(result)}, status=500)
    except Exception as e:
        print('Error en la solicitud',e)    
        return JsonResponse({'status': False, 'error': str(result)}, status=500)

def obtener_confirmacion(request):
    nro_nota_entrega=request.session.pop('nota_entrega', {})
    return render(request, 'confirm-nota.html', context={'document': nro_nota_entrega})

@csrf_exempt
def delete_product(request):
    if request.method == 'POST':
        print("Recibiendo delete request")
        return HttpResponse(status=200)