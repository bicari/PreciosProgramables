from django.shortcuts import render
from django.http import HttpResponse, FileResponse
from django.conf import settings
from .forms import UploadTaskForm, PrintLabelTask
from .models import Tasks, ProductsTasks
from users.models import User
from .utils import read_excel_file, print_labels
from .scheduler import programar_tarea
from django.contrib.auth.decorators import login_required, user_passes_test
from uuid import uuid4
from .dbisam import DBISAMDatabase
from django.contrib import messages
from datetime import datetime, time
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
                    return render(request, 'form-list.html', context={'form': form,  
                                                'message': 'Error al leer o procesar el archivo: %s' % filas
                    })   
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
                    programar_tarea(task)
                    if len(filas[1]) > 0:
                        request.session['duplicados_txt'] = ''.join(
                                f"SKU: {sku} \n" for sku in filas[1]
                            )
                        return render(request, 'accept-list.html', context= {'document': task.task_number, 'filas': len(filas[0]), 'actualizados': filas[2], 'duplicados': len(filas[1]) })
                    return render(request, 'accept-list.html', context= {'document': task.task_number, 'filas': len(filas[0]), 'duplicados': 0, 'actualizados': filas[2] }) 
                else:
                    if len(filas[1]) > 0:
                        request.session['duplicados_txt'] = ''.join(
                                f"SKU: {sku} \n" for sku in filas[1]
                            )
                    return render(request, 'abort-list.html', context= {'filas': len(filas[0]), 'duplicados': len(filas[1]), 'actualizados': filas[2] })
            else:
                name_table = str(uuid4()).replace('-', '')
                filas = read_excel_file(form, request.FILES['file'], name_table, user, inmediato=True, is_oferta=True if is_oferta == 'on' else False)
                if type(filas) == ValueError:
                    return render(request, 'form-list.html', context={'form': form,  
                                            'message': 'Error al leer o procesar el archivo: %s' % filas
                    })
                
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

                    if len(filas[1]) > 0:
                        request.session['duplicados_txt'] = ''.join(
                            f"-SKU: {sku} \n" for sku in filas[1]
                        )
                    return render(request, 'accept-list.html', context= {'document': task.task_number, 'filas': len(filas[0]), 'duplicados': len(filas[1]), 'actualizados': filas[2]})
                return render(request, 'abort-list.html', context= {'filas': len(filas[0]), 'duplicados': len(filas[1]), 'actualizados': filas[2] })
                 
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
    tasks = Tasks.objects.select_related('user_id').order_by('-date_to_execute')
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
                if validar_existencia == 'on':
                    dbisam.update_table_existencia(task.dbisam_table)
                    productos = dbisam.get_table_tmp_con_existencia(task.dbisam_table)
                else:    
                    productos = dbisam.get_table_tmp_sin_existencia(task.dbisam_table)
                etiquetas_impresas = print_labels(productos, request)          
                if etiquetas_impresas > 0:
                    messages.success(request, f'Impresion de {etiquetas_impresas} etiquetas realizada con éxito')
            except Tasks.DoesNotExist:
                messages.error(request, 'No existe una tarea con ese ID', extra_tags='danger')
        return render(request, 'print-label.html', context={'form': form})    
            
    
    return render (request, 'print-label.html', context={'form': PrintLabelTask()})

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