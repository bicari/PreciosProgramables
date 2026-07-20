from django.shortcuts import render, redirect
from django.http import HttpResponse, FileResponse, JsonResponse
from django.conf import settings
from .forms import UploadTaskForm, PrintLabelTask
from .models import Tasks, ProductsTasks, ListaEtiquetaDetalle
from users.models import User
from .utils import read_excel_file, print_labels, guardar_orden_lista, previsualizar_lista
import logging

logger = logging.getLogger(__name__)
from .scheduler import programar_tarea
from django.contrib.auth.decorators import login_required, user_passes_test
from uuid import uuid4
from .dbisam import DBISAMDatabase
from django.contrib import messages
from datetime import datetime, time
from .send_mail import notificar_creacion_lista, notificar_creacion_tarea
import os


#from .dbisam import create_table_tmp, insert_data_tmp

def is_in_group_generar_lista(user):
    return user.groups.filter(name='Generar Lista').exists() or user.is_superuser

def is_in_group_consultar_lista(user):
    print(user.groups.filter(name='Generar Lista').exists())
    return user.groups.filter(name='Consultar Lista').exists() or user.is_superuser


@login_required(login_url='/login/')
@user_passes_test(is_in_group_generar_lista, login_url='dashboard')
def ListFormView(request):
    if request.method== 'POST':
        form = UploadTaskForm(request.POST, request.FILES, user= request.user)
       
        
        if form.is_valid():
            user = User.objects.get(id=form.cleaned_data['user_id'])
            check_process = request.POST.get('check_process', 'off')
            is_oferta = request.POST.get('is_oferta', 'off')
            

            if check_process == 'off':
                name_table = str(uuid4()).replace('-', '')
                print(name_table, 'Nombre de la tabla')
                filas = read_excel_file(form, request.FILES['file'],name_table, user, inmediato=False, is_oferta=True if is_oferta == 'on' else False)
                if type(filas) == ValueError:
                    messages.error(request, 'Error al leer o procesar el archivo: %s' % filas)
                    return redirect('list-form')
                        #task.save()
                
                if filas[2] > 0:
                    #Crear tarea si hay productos actualizados
                    task = Tasks.objects.create(
                    user_id = user,
                    #rif_proveedor = form.cleaned_data['rif_proveedor'],
                    file = form.cleaned_data['file'],
                    date_to_execute = datetime.combine(form.cleaned_data['date_time'], time.fromisoformat(settings.HORA_EJECUCION) ),
                    header_file = form.cleaned_data['header'],
                    dbisam_table = name_table,  # Assuming filas is the name of the table created in DBISAM
                    is_oferta = True if is_oferta == 'on' else False
                    )
                    products = [ProductsTasks(task=task, **fila) for fila in filas[0]]
                    ProductsTasks.objects.bulk_create(products)
                    guardar_orden_lista(task, filas[0])
                    #programar_tarea(task)
                    notificar_creacion_tarea(task)
                    if len(filas[1]) > 0:
                        request.session['duplicados_txt'] = ''.join(
                                f"SKU: {sku} \n" for sku in filas[1]
                            )
                    request.session['list_result'] = {
                        'template': 'accept-list.html',
                        'context': {
                            'document': task.task_number,
                            'filas': len(filas[0]),
                            'actualizados': filas[2],
                            'duplicados': len(filas[1]),
                        },
                    }
                    return redirect('list-form-result')
                else:
                    if len(filas[1]) > 0:
                        request.session['duplicados_txt'] = ''.join(
                                f"SKU: {sku} \n" for sku in filas[1]
                            )
                    request.session['list_result'] = {
                        'template': 'abort-list.html',
                        'context': {'filas': len(filas[0]), 'duplicados': len(filas[1]), 'actualizados': filas[2]},
                    }
                    return redirect('list-form-result')
            else:
                name_table = str(uuid4()).replace('-', '')
                filas = read_excel_file(form, request.FILES['file'], name_table, user, inmediato=True, is_oferta=True if is_oferta == 'on' else False)
                if type(filas) == ValueError:
                    messages.error(request, 'Error al leer o procesar el archivo: %s' % filas)
                    return redirect('list-form')
                
                if filas[2] > 0:
                    task = Tasks.objects.create(
                    user_id = user,
                    #rif_proveedor = form.cleaned_data['rif_proveedor'],
                    file = form.cleaned_data['file'],
                    date_to_execute = datetime.combine(form.cleaned_data['date_time'], time.fromisoformat(settings.HORA_EJECUCION) ),
                    header_file = form.cleaned_data['header'],
                    dbisam_table = name_table,  # Assuming filas is the name of the table created in DBISAM
                    is_oferta = True if is_oferta == 'on' else False,
                    check_process = True
                    )
                    #products = [ProductsTasks(task=task, **fila) for fila in filas[0]]
                    #ProductsTasks.objects.bulk_create(products)
                    guardar_orden_lista(task, filas[0])
                    notificar_creacion_lista(task)
                    if len(filas[1]) > 0:
                        request.session['duplicados_txt'] = ''.join(
                            f"-SKU: {sku} \n" for sku in filas[1]
                        )
                    request.session['list_result'] = {
                        'template': 'accept-list.html',
                        'context': {
                            'document': task.task_number,
                            'filas': len(filas[0]),
                            'duplicados': len(filas[1]),
                            'actualizados': filas[2],
                        },
                    }
                    return redirect('list-form-result')
                request.session['list_result'] = {
                    'template': 'abort-list.html',
                    'context': {'filas': len(filas[0]), 'duplicados': len(filas[1]), 'actualizados': filas[2]},
                }
                return redirect('list-form-result')
                 
        else:  

            return render(request, 'form-list.html', context={'form':form})
    else:
        if request.session.get('duplicados_txt'):
            del request.session['duplicados_txt']
        form = UploadTaskForm(user=request.user)
        return render(request, 'form-list.html', context={'form':form})

@login_required(login_url='/login/')
@user_passes_test(is_in_group_consultar_lista, login_url='dashboard')
def ListTaskView(request):
    tasks = Tasks.objects.select_related('user_id').order_by('-task_number')
    print(tasks)
    return render(request, 'list-tasks.html', context={'tasks': tasks})


@login_required(login_url='/login/')
@user_passes_test(is_in_group_consultar_lista, login_url='dashboard')
def ListLabelView(request):
    if request.method == 'POST':
        print(request.POST)
        validar_existencia = request.POST.get('validar_existencia', 'off')
        form = PrintLabelTask(request.POST)
        if form.is_valid():
            try:
                task = Tasks.objects.get(task_number=form.cleaned_data['list_id'])
                dbisam = DBISAMDatabase()
                departamento = form.cleaned_data.get('departamento') or None
                if validar_existencia == 'on':
                    dbisam.update_table_existencia(task.dbisam_table)
                    productos = dbisam.get_table_tmp_con_existencia(task.dbisam_table, departamento)
                else:
                    productos = dbisam.get_table_tmp_sin_existencia(task.dbisam_table, departamento)
                # El rango queda deshabilitado cuando se filtra por departamento
                if departamento:
                    rango_desde = None
                    rango_hasta = None
                else:
                    rango_desde = form.cleaned_data.get('rango_desde')
                    rango_hasta = form.cleaned_data.get('rango_hasta')
                # Reordenar según el orden del Excel (solo listas nuevas con detalle guardado)
                orden_map = dict(
                    ListaEtiquetaDetalle.objects
                    .filter(task=task)
                    .values_list('sku', 'orden')
                )
                if orden_map:
                    productos = sorted(productos, key=lambda p: orden_map.get(p.SKU, 10 ** 9))
                print(productos, len(productos))
                etiquetas_impresas, omitidos = print_labels(productos, request, rango_desde, rango_hasta)
                if omitidos:
                    detalle = '; '.join(f"{sku}: {motivo}" for sku, motivo in omitidos)
                    messages.warning(request, f'{len(omitidos)} producto(s) omitido(s) por datos inválidos: {detalle}')
                if etiquetas_impresas > 0:
                    messages.success(request, f'Impresion de {etiquetas_impresas} etiquetas realizada con éxito')
                    return redirect('print-label')
                else:
                    messages.warning(request, 'No se ha podido completar la impresion, comprueba la impresora o existencia de los items')
                    return redirect('print-label')
            except Tasks.DoesNotExist:
                messages.error(request, 'No existe una tarea con ese ID', extra_tags='danger')
                return redirect('print-label')
            except Exception as e:
                logger.error(f'Error al imprimir etiquetas: {e}')
                messages.error(request, f'Error al imprimir: {e}', extra_tags='danger')
                return redirect('print-label')
        return render(request, 'print-label.html', context={'form': form})

    return render(request, 'print-label.html', context={'form': PrintLabelTask()})


@login_required(login_url='/login/')
@user_passes_test(is_in_group_generar_lista, login_url='dashboard')
def ListFormResultView(request):
    """Vista GET que muestra el resultado de subir una lista (PRG).

    El resultado se guarda en sesión por ListFormView y se consume aquí una
    sola vez: recargar la página redirige al formulario en lugar de reprocesar
    el archivo.
    """
    result = request.session.pop('list_result', None)
    if not result:
        return redirect('list-form')
    return render(request, result['template'], context=result['context'])


@login_required(login_url='/login/')
@user_passes_test(is_in_group_consultar_lista, login_url='dashboard')
def LabelListInfoView(request, list_id: int):
    try:
        task = Tasks.objects.get(task_number=list_id)
        dbisam = DBISAMDatabase()
        count = dbisam.get_table_tmp_count(task.dbisam_table)
        departamentos = dbisam.get_departamentos_tabla_tmp(task.dbisam_table)
        return JsonResponse({'count': count, 'departamentos': departamentos})
    except Tasks.DoesNotExist:
        return JsonResponse({'error': 'No existe una lista con ese ID'}, status=404)

@login_required(login_url='/login/')
def download_duplicados(request):
    if 'duplicados_txt' not in request.session:
        return HttpResponse("No hay productos duplicados para descargar")
    
    content = request.session['duplicados_txt']
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = 'attachment; filename="productos_duplicados.txt"'
    
    # Limpia la sesión después de descargar
    del request.session['duplicados_txt']
    return response
@login_required(login_url='/login/')
@user_passes_test(is_in_group_generar_lista, login_url='dashboard')
def PreviewListView(request):
    """Endpoint AJAX: valida el Excel de lista de precios sin crear la tarea ni modificar precios.

    Recibe: file (Excel), header (int), date_time (YYYY-MM-DD), is_oferta ('on'/'off').
    Devuelve: JsonResponse con el dict de validación o {error: ...} en fallo.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    file = request.FILES.get('file')
    if not file:
        return JsonResponse({'error': 'No se proporcionó archivo'}, status=400)

    try:
        header = int(request.POST.get('header', 1))
        date_time_str = request.POST.get('date_time', '')
        from datetime import date as date_type
        fecha = date_type.fromisoformat(date_time_str)
        is_oferta = request.POST.get('is_oferta', 'off') == 'on'
    except (ValueError, TypeError) as e:
        return JsonResponse({'error': f'Parámetros inválidos: {e}'}, status=400)

    resultado = previsualizar_lista(file, header, fecha, is_oferta)
    if isinstance(resultado, ValueError):
        return JsonResponse({'error': str(resultado)}, status=400)
    return JsonResponse(resultado)


@login_required(login_url='/login/')
@user_passes_test(is_in_group_consultar_lista, login_url='dashboard')
def TaskDetailView(request, task_id: int):
    try:
        task = Tasks.objects.get(task_number=task_id)
    except Tasks.DoesNotExist:
        return JsonResponse({'error': 'Lista no encontrada'}, status=404)

    if not task.dbisam_table:
        return JsonResponse({'error': 'Esta lista no tiene tabla de datos asociada'}, status=404)

    try:
        dbisam = DBISAMDatabase()
        items = dbisam.get_tabla_detalle(task.dbisam_table)
        return JsonResponse({'items': items, 'total': len(items), 'is_oferta': task.is_oferta})
    except Exception as e:
        logger.error('TaskDetailView error task %s: %s', task_id, e)
        return JsonResponse({'error': f'No se pudo obtener el detalle: {e}'}, status=500)


@login_required(login_url='/login')
def download_excel(request, task_id):
    try:
        task = Tasks.objects.get(task_number=task_id)
        # Asumiendo que tu modelo Task tiene un campo file_path que almacena la ruta al archivo
        file_path = task.file.name
        
        # Construir la ruta completa al archivo
        full_path = os.path.join(settings.MEDIA_ROOT, file_path)
        
        # Verificar que el archivo existe
        if os.path.exists(full_path):
            # Abrir el archivo en modo binario
            file = open(full_path, 'rb')
            response = FileResponse(file)
            
            # Configurar las cabeceras para forzar la descarga
            filename = os.path.basename(full_path)
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            
            return response
        else:
            # Si el archivo no existe, devolver un error 404
            from django.http import Http404
            raise Http404("El archivo solicitado no existe")
            
    except Tasks.DoesNotExist:
        from django.http import Http404
        raise Http404("La tarea solicitada no existe")