from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags

def send_notification(data, nro_documento, bytes_pdf):
    ordenes_compra = {orden['orden'] for orden in data['ordenes']}
    cant_items = len(data['ordenes']) + len(data['productoSinOc'])
    print('ordenes de compra', ordenes_compra)
    html_str = render_to_string('recepcion_mail.html', context={'proveedor': data['proveedor'],
                                                                'nro_documento': nro_documento,
                                                                'ordenes_compra': ordenes_compra,
                                                                'cant_items': cant_items})
    #text_content = strip_tags(html_str)
    print(settings.EMAIL_USERS)
    mail=EmailMessage(
            subject='Recepcion',
            body=html_str,
            from_email=settings.EMAIL_HOST_USER,
            to=settings.EMAIL_USERS,  # Email del primer admin
            
            )
    mail.attach
    mail.content_subtype = "html"
    mail.attach(f'Nota_Entrega_{nro_documento}.pdf', bytes_pdf, 'application/pdf')
    mail.send()