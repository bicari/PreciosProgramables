from django.http import HttpResponse
from django.template.response import TemplateResponse 
from functools import wraps
import io

def handle_duplicate_products(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        
        # Si la vista devuelve un HttpResponse (caso normal), retórnalo sin cambios
        if isinstance(response, list):
            print('response', response.context_data)
            # buffer = io.StringIO()
            # buffer.write("Productos duplicados encontrados:\n\n")
            # for producto in response:
            #     buffer.write(f"- ID: {producto.id}, Nombre: {producto.nombre}\n")  # Ajusta campos
            
            # # Genera el .txt descargable
            # response = HttpResponse(buffer.getvalue(), content_type='text/plain')
            # response['Content-Disposition'] = 'attachment; filename="productos_duplicados.txt"'
            # return response
        
        # Si la respuesta es una lista de duplicados (ej: desde read_excel_now)
        
        return response  # Retorna la respuesta original si no hay duplicados
    return wrapper