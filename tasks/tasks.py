from .models import Tasks, ProductsTasks
#from .utils import read_excel_file
from .dbisam import DBISAMDatabase
from django.db import transaction
from django_apscheduler import util

@util.close_old_connections
def ejecutar_tarea_programada(task_number):
    try:
        with transaction.atomic():
            dbisam_db = DBISAMDatabase()
            task = Tasks.objects.get(task_number=task_number)
            productsTasks = ProductsTasks.objects.filter(task=task)
            if task.status and not task.check_process:
                print('Ejecutando tarea programada:', task.task_number )
                #create_table_tmp()
                #filas = read_excel_file(task.file, task.header_file, process=True)
                #for fila in filas: 
                #    insert_data_tmp(fila.SKU, fila.PRECIO)
                dbisam_db.update_a2precios(task.dbisam_table)

                #Cambiando status de la tarea a procesada
                task.check_process = True
                task.save()
                productsTasks.delete()

    except Exception as e:
        print('Error al ejecutar la tarea programada', e)        
