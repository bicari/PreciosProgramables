#from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import Tasks
from users.models import User
from datetime import date
from datetime import timedelta
#from django.contrib.auth.models import User

def enviar_correo():
    tasks = Tasks.objects.filter(date_to_execute__date=str(date.today()), check_process=True).select_related('user_id')
    

    
    if len(tasks) > 0:
        try:
            
            #tasks_list = [f'Lista Oferta: {task.task_number}' if task.is_oferta == True else f'Lista Nro: {task.task_number}' for task in tasks]
            tasks_list= [{
                'is_oferta': task.is_oferta,
                'task_number': task.task_number,
            } for task in tasks]
            html_str = render_to_string('mail-message.html', context={'notification_title': 'Etiquetas listas para la impresión', 'tasks': tasks_list, 'settings_link': ''})
            text_content = strip_tags(html_str)
            send_mail(
                subject='Etiquetas por imprimir',
                message=text_content,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=settings.EMAIL_USERS,  # Email del primer admin
                html_message=html_str,
                fail_silently=False,
            )
    
        except Exception as e:
            print(e)
    else:
        print('No hay tareas procesadas el día de hoy')        


def notificar_creacion_lista(task: Tasks): 
    try:
            #tasks_list = [f'Lista Oferta: {task.task_number}' if task.is_oferta == True else f'Lista Nro: {task.task_number}' for task in tasks]
            tasks_list= [{
                'is_oferta': task.is_oferta,
                'task_number': task.task_number
            } ]
            html_str = render_to_string('mail-message.html', context={'notification_title': 'Etiquetas listas para la impresión', 'tasks': tasks_list, 'settings_link': ''})
            text_content = strip_tags(html_str)
            send_mail(
                subject='Etiquetas por imprimir',
                message=text_content,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=settings.EMAIL_USERS,  # Email del primer admin
                html_message=html_str,
                fail_silently=False,
            )
    
    except Exception as e:
            print(e) 


def notificar_creacion_tarea(task: Tasks): 
    try:
            #tasks_list = [f'Lista Oferta: {task.task_number}' if task.is_oferta == True else f'Lista Nro: {task.task_number}' for task in tasks]
            
            html_str = render_to_string('notification_list.html', context={'task_number': task.task_number, 'user_name': task.user_id.username})
            text_content = strip_tags(html_str)
            send_mail(
                subject='Etiquetas por imprimir',
                message=text_content,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=settings.EMAIL_USERS,  # Email del primer admin
                html_message=html_str,
                fail_silently=False,
            )
    
    except Exception as e:
            print(e)                    