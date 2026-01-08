from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from tasks.dbisam import DBISAMDatabase
from django.http import HttpResponse, JsonResponse
import json
from django.views.decorators.csrf import csrf_exempt
from .utils import send_notification
from .pdf import generar_factura
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
        return render(request, 'search_product.html', {'Codigo': result[0], 'Descripcion': result[1], 'CostoBs': result[2], 'CostoUsd': result[3], 'Iva': result[4]})
    except Exception as e:
        return HttpResponse(content=str(e), status=500)

def search_product_by_description(request):
    try:
        print(request)
        description = request.GET.get('description', '').upper()
        dbisam = DBISAMDatabase()
        result = dbisam.search_product_by_description(description)
        json_result = [{'Codigo': row[0], 'Descripcion': row[1], 'Departamento': row[2], 'CostoBS':row[3], 'CostoUS': row[4],
                        'Iva':row[5]} for row in result]
        
        return render(request, 'search_description.html', {'products': json_result})
    except Exception as e:
        return HttpResponse(content=f"Error al procesar la solicitud {e}", status=500)

def modal_search(request):
    return render(request, 'modal_search.html')

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
                            'Autoincrement': row[8]}  for row in result]
            return render(request, 'search_description.html', {'products': json_result, 'is_order': True})
        else:
            return HttpResponse(content='No se encontraron resultados', status=404)
            #return HttpResponse("No se encontraron resultados", status=404)
    except Exception as e:
        print(e)
        return HttpResponse(content=f"Error al procesar la solicitud {e}", status=500)

def search_proveedor(request):
    try:
        
        data = request.GET.get('proveedor', '').upper()
        dbisam = DBISAMDatabase()
        result = dbisam.search_proveedor(data)
        print(result)
        if result:
           return render(request, 'card-proveedor.html',{"proveedor": f"{result[0]}-{result[1]}"})
        return HttpResponse(content=f"Código Proveedor '{data}' no encontrado", status=404)
    except Exception as e:
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
            result = dbisam.insert_notas_entrega(request_frontend, nro_nota_entrega)
            if not isinstance(result, Exception):
                nota_pdf = generar_factura('factura.pdf', request_frontend, 'static/KsaHome.png', preliminar=True)
                send_notification(request_frontend, nro_nota_entrega, nota_pdf)
                return JsonResponse({'status': True, 'redirect_url': '/confirmar-nota-entrega/'}, status=200)
            return JsonResponse({'status': False, 'error': str(result)}, status=500)
    except Exception as e:
        print('Error en la solicitud',e)    
        return HttpResponse(content=f"Error al procesar la solicitud {e}", status=500)

def obtener_confirmacion(request):
    nro_nota_entrega=request.session.pop('nota_entrega', {})
    return render(request, 'confirm-nota.html', context={'document': nro_nota_entrega})

@csrf_exempt
def delete_product(request):
    if request.method == 'DELETE':
        print("Recibiendo delete request")
        return HttpResponse(status=200)