# tareas/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution
from django_apscheduler import util
#from .models import Tasks
from .send_mail import enviar_correo
from .tasks import ejecutar_tarea_programada
from datetime import datetime
from django.db import transaction
import threading

_scheduler_instance = None
_scheduler_lock = threading.Lock()

def get_scheduler():
    global _scheduler_instance
    if _scheduler_instance is None:
        with _scheduler_lock:
            if _scheduler_instance is None:
                _scheduler_instance = BackgroundScheduler()
                _scheduler_instance.configure(
                    job_defaults={
                        'coalesce': True,
                        'max_instances': 1,
                        'misfire_grace_time': 30  # segundos
                    })
                _scheduler_instance.add_jobstore(DjangoJobStore(), 'default')
                # Configuración recomendada
                
                
    return _scheduler_instance



def programar_correo():
    scheduler = get_scheduler()
    job_id = 'correo_automatico_diario'
    job=scheduler.add_job(
        enviar_correo,
        trigger='cron',
        hour=20,
        minute=30,
        second=15,
        id=job_id,
        replace_existing=True,
        jobstore='default',
        max_instances=1,
        misfire_grace_time=9600
    )
    print('Correo programado', job)


def iniciar_scheduler():
    scheduler = get_scheduler()
    print('inciando')
    with _scheduler_lock:
        if not scheduler.running:
            print("Iniciando scheduler...")
            
            # Limpieza inicial
            eliminar_ejecuciones_antiguas()
            
            # Iniciar scheduler
            scheduler.start()
            
            # Cargar tareas pendientes al inicio
            cargar_tareas_pendientes()
            programar_correo()
            
            print("Scheduler iniciado correctamente")

def cargar_tareas_pendientes():
    from .models import Tasks  # Import local para evitar circular imports
    
    try:
        with transaction.atomic():
            tareas = Tasks.objects.select_for_update().filter(
                check_process=False,
                date_to_execute__gte=datetime.now()
            )
            
            for tarea in tareas:
                programar_tarea(tarea)
                
    except Exception as e:
        print(f"Error al cargar tareas pendientes: {e}")

def programar_tarea(tarea):
    scheduler = get_scheduler()
    job_id = f'tarea_{tarea.task_number}'
    
    try:
        # # Eliminar job existente si hay conflicto
        # try:
        #     scheduler.remove_job(job_id)
        # except:
        #     pass
            
        # Crear nuevo job
        ob=scheduler.add_job(
            id=job_id,
            func=ejecutar_tarea_programada,  
            args=[tarea.task_number],
            trigger='date',
            run_date=tarea.date_to_execute,
            replace_existing=True,
            jobstore='default',
            max_instances=1,
            misfire_grace_time=9600
        )
        print(f"Tarea {job_id} programada para {tarea.date_to_execute}{ob}")
        
    except Exception as e:
        print(f"Error al programar tarea {job_id}: {e}")
        raise

def ejecutar_tarea(task_number):
    from .models import Tasks
    try:
        with transaction.atomic():
            tarea = Tasks.objects.select_for_update().get(task_number=task_number)
            # Tu lógica de procesamiento aquí
            print(f"Ejecutando tarea {task_number}")
            tarea.check_process = True
            tarea.save()
    except Exception as e:
        print(f"Error al ejecutar tarea {task_number}: {e}")


# def agregar_tarea_al_scheduler(tarea):
#     scheduler.add_job(
#         ejecutar_tarea_programada,
#         trigger='date',
#         run_date=tarea.date_to_execute,
#         args=[tarea.task_number],
#         id=f'tarea_{tarea.task_number}',
#         replace_existing=True,
#         misfire_grace_time=60
#     )

@util.close_old_connections
def eliminar_ejecuciones_antiguas(max_age=604_800):
     DjangoJobExecution.objects.delete_old_job_executions(max_age)

# def iniciar_scheduler():
#     if not scheduler.running:
#         print("Inciando el scheduler....")
#         scheduler.start()
        
#         # Agregar tareas pendientes al scheduler al iniciar
#         tareas_pendientes = Tasks.objects.filter(check_process=False, date_to_execute__gte=timezone.now())
#         print(tareas_pendientes.count(), "tareas pendientes encontradas.")
#         for tarea in tareas_pendientes:
#             if not DjangoJob.objects.filter(id=f'tarea_{tarea.task_number}').exists():
#                 agregar_tarea_al_scheduler(tarea)