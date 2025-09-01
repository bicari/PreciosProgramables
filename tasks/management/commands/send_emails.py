from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Envía correos electrónicos a los usuarios'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--test',
            action='store_true',
            help='Enviar solo correo de prueba al admin'
        )
    
    def handle(self, *args, **options):
        if options['test']:
            self.enviar_correo_prueba()
        else:
            self.enviar_correos_masivos()
    
    def enviar_correo_prueba(self):
        """Envía un correo de prueba"""
        try:
            html_str = render_to_string('mail-message.html', context={'notification_title': 'Etiquetas listas para la impresión', 'action_url': '', 'settings_link': ''})
            text_content = strip_tags(html_str)
            send_mail(
                subject='Etiquetas por imprimir',
                message=text_content,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=["arangurencg2@gmail.com", "soporte@geekcod.com", "sistemas@ksahomecenter.com"],  # Email del primer admin
                html_message=html_str,
                fail_silently=False,
            )
            self.stdout.write(
                self.style.SUCCESS('✓ Correo de prueba enviado exitosamente')
            )
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f'✗ Error enviando correo de prueba: {e}')
            )
    
    def enviar_correos_masivos(self):
        """Envía correos a todos los usuarios"""
        try:
            usuarios = User.objects.filter(is_active=True, email__isnull=False)
            total = usuarios.count()
            
            self.stdout.write(f'Enviando correos a {total} usuarios...')
            
            for i, usuario in enumerate(usuarios, 1):
                subject = 'Mensaje importante de nuestra plataforma'
                context = {
                    'usuario': usuario,
                    'unsubscribe_link': f'{getattr(settings, "SITE_URL", "http://localhost:8000")}/unsubscribe'
                }
                
                html_content = render_to_string('email/plantilla_general.html', context)
                text_content = strip_tags(html_content)
                
                send_mail(
                    subject=subject,
                    message=text_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[usuario.email],
                    html_message=html_content,
                    fail_silently=False,
                )
                
                if i % 10 == 0:
                    self.stdout.write(f'Procesados {i}/{total} usuarios...')
            
            self.stdout.write(
                self.style.SUCCESS(f'✓ Se enviaron {total} correos exitosamente')
            )
            
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f'✗ Error enviando correos: {e}')
            )