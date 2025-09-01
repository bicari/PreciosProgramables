#from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import Tasks
from datetime import date
from datetime import timedelta
#from django.contrib.auth.models import User

def enviar_correo():
    tasks = Tasks.objects.filter(date_to_execute=str(date.today() - timedelta(days=1)), check_process=True)

    
    if len(tasks) > 0:
        try:
            #tasks_list = [f'Lista Oferta: {task.task_number}' if task.is_oferta == True else f'Lista Nro: {task.task_number}' for task in tasks]
            tasks_list= [{
                'is_oferta': task.is_oferta,
                'task_number': task.task_number
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