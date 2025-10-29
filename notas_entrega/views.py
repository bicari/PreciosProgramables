from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from tasks.dbisam import DBISAMDatabase
from django.http import HttpResponse
import json
from django.views.decorators.csrf import csrf_exempt
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
        return render(request, 'search_product.html', {'Codigo': result[0], 'Descripcion': result[1], 'Departamento': result[2]})
    except Exception as e:
        return render(request, 'error_message.html', {'message': "Error al procesar la solicitud"}, status=500)

def search_product_by_description(request):
    try:
        print(request)
        description = request.GET.get('description', '').upper()
        dbisam = DBISAMDatabase()
        result = dbisam.search_product_by_description(description)
        json_result = [{'Codigo': row[0], 'Descripcion': row[1], 'Departamento': row[2]} for row in result]
        
        return render(request, 'search_description.html', {'products': json_result})
    except Exception as e:
        print(e)

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
            json_result = [{'Codigo': row[0], 'Documento': row[2], 'Cantidad': row[1], 'Costo': row[3], 'Iva': row[4], 'Moneda':row[5]} for row in result]
            return render(request, 'search_description.html', {'products': json_result, 'is_order': True})
        else:
            return HttpResponse(content='No se encontraron resultados', status=404)
            #return HttpResponse("No se encontraron resultados", status=404)
    except Exception as e:
        print(e)
        return HttpResponse(content="Error al procesar la solicitud", status=500)

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
            print(request_frontend)
            dbisam = DBISAMDatabase()
            result = dbisam.insert_notas_entrega(request_frontend)
            print(result)
            return HttpResponse(content='Recibido', status=200)
    except Exception as e:
        print(e)    

@csrf_exempt
def delete_product(request):
    if request.method == 'DELETE':
        print("Recibiendo delete request")
        return HttpResponse(status=200)