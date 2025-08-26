from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
from .forms import UploadTaskForm, PrintLabelTask
from .models import Tasks
from users.models import User
from .utils import read_excel_file, print_labels
from .scheduler import programar_tarea
from django.contrib.auth.decorators import login_required
from uuid import uuid4
from .dbisam import DBISAMDatabase
from django.contrib import messages

#from .dbisam import create_table_tmp, insert_data_tmp


@login_required(login_url='/login/')
def ListFormView(request):
    if request.method== 'POST':
        form = UploadTaskForm(request.POST, request.FILES, user= request.user)
       
        
        if form.is_valid():
            user = User.objects.get(id=form.cleaned_data['user_id'])
            check_process = request.POST.get('check_process', 'off')
            is_oferta = request.POST.get('is_oferta', 'off')
            

            if check_process == 'off':
                print('apagado')
                name_table = str(uuid4()).replace('-', '')
                print(name_table, 'Nombre de la tabla')
                filas = read_excel_file(form, request.FILES['file'],name_table, user, inmediato=False, is_oferta=True if is_oferta == 'on' else False)
                print(name_table)
                if type(filas) == ValueError:
                    return render(request, 'form-list.html', context={'form': form,  
                                                'message': 'Error al leer o procesar el archivo: %s' % filas
                    })   
                        #task.save()
                print('Tarea creada con exito', filas[1])
                programar_tarea(filas[1])
                if len(filas[2]) > 0:
                    request.session['duplicados_txt'] = ''.join(
                            f"-SKU: {sku} \n" for sku in filas[2]
                        )
                    return render(request, 'accept-list.html', context= {'document': filas[1].task_number, 'filas': filas[0], 'actualizados': filas[3], 'duplicados': len(filas[2]) })
                return render(request, 'accept-list.html', context= {'document': filas[1].task_number, 'filas': filas[0], 'duplicados': 0, 'actualizados': filas[3] }) 
            else:
                name_table = str(uuid4()).replace('-', '')
                filas = read_excel_file(form, request.FILES['file'], name_table, user, inmediato=True, is_oferta=True if is_oferta == 'on' else False)
                if type(filas) == ValueError:
                    return render(request, 'form-list.html', context={'form': form,  
                                            'message': 'Error al leer o procesar el archivo: %s' % filas
                    })
                
                #dbisam_db = DBISAMDatabase()
                #dbisam_db.update_a2precios(name_table)
                #dbisam_db.delete_table(name_table)
                if len(filas[2]) > 0:
                    request.session['duplicados_txt'] = ''.join(
                        f"-SKU: {sku} \n" for sku in filas[2]
                    )
                return render(request, 'accept-list.html', context= {'document': filas[1].task_number, 'filas': filas[0], 'duplicados': len(filas[2]), 'actualizados': filas[3]})
                 
        else:  

            return render(request, 'form-list.html', context={'form':form})
    else:
        if request.session.get('duplicados_txt'):
            del request.session['duplicados_txt']
        form = UploadTaskForm(user=request.user)
        return render(request, 'form-list.html', context={'form':form})

@login_required(login_url='/login/')
def ListTaskView(request):
    tasks = Tasks.objects.select_related('user_id').order_by('-date_to_execute')
    return render(request, 'list-tasks.html', context={'tasks': tasks})


@login_required(login_url='/login/')
def ListLabelView(request):
    if request.method == 'POST':
        print(request.POST)
        form = PrintLabelTask(request.POST)
        if form.is_valid():
            try:
                task = Tasks.objects.get(task_number=form.cleaned_data['list_id'])
                dbisam = DBISAMDatabase()
                dbisam.update_table_existencia(task.dbisam_table)
                row=dbisam.get_table_tmp(task.dbisam_table)
                print_labels(row, request)
            except Tasks.DoesNotExist:
                print("No existe una tarea con ese ID")
                form.add_error('list_id', 'No existe una tarea con ese ID')
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
