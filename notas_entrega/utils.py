from decimal import Decimal
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
import logging

logger = logging.getLogger(__name__)


def send_notification(data, nro_documento, bytes_pdf):
    ordenes_compra = {orden['orden'] for orden in data['ordenes']}
    cant_items = len(data['ordenes']) + len(data['productoSinOc'])
    html_str = render_to_string('recepcion_mail.html', context={
        'proveedor': data['proveedor'],
        'nro_documento': nro_documento,
        'ordenes_compra': ordenes_compra,
        'cant_items': cant_items,
    })
    mail = EmailMessage(
        subject='Recepcion',
        body=html_str,
        from_email=settings.EMAIL_HOST_USER,
        to=settings.EMAIL_RECEPCIONES,
    )
    mail.content_subtype = "html"
    mail.attach(f'Nota_Entrega_{nro_documento}.pdf', bytes_pdf, 'application/pdf')
    mail.send()


def calcular_totales(factura: dict) -> dict:
    moneda_operacion = factura['ordenes'][0]['moneda']

    total_bruto_oc = sum(Decimal(str(item['costo'])) * Decimal(str(item['recibido'])) for item in factura['ordenes'])
    base_imponible_oc = sum(Decimal(str(item['costo'])) * Decimal(str(item['recibido'])) for item in factura['ordenes'] if item['iva'] == 16)
    exento_oc = sum(Decimal(str(item['costo'])) * Decimal(str(item['recibido'])) for item in factura['ordenes'] if item['iva'] == 0)
    iva_16_oc = base_imponible_oc * Decimal('0.16')

    if str(moneda_operacion).__contains__('1'):
        total_bruto_sin_oc = sum(Decimal(str(item['costoBS'])) * Decimal(str(item['cantidad'])) for item in factura['productoSinOc'])
        base_imponible_sin_oc = sum(Decimal(str(item['costoBS'])) * Decimal(str(item['cantidad'])) for item in factura['productoSinOc'] if item['iva'] == 16)
        exento_sin_oc = sum(Decimal(str(item['costoBS'])) * Decimal(str(item['cantidad'])) for item in factura['productoSinOc'] if item['iva'] == 0)
        iva_16_sin_oc = base_imponible_sin_oc * Decimal('0.16')
    else:
        total_bruto_sin_oc = sum(Decimal(str(item['costoUS'])) * Decimal(str(item['cantidad'])) for item in factura['productoSinOc'])
        base_imponible_sin_oc = sum(Decimal(str(item['costoBS'])) * Decimal(str(item['cantidad'])) for item in factura['productoSinOc'] if item['iva'] == 16)
        exento_sin_oc = sum(Decimal(str(item['costoUS'])) * Decimal(str(item['cantidad'])) for item in factura['productoSinOc'] if item['iva'] == 0)
        iva_16_sin_oc = base_imponible_sin_oc * Decimal('0.16')

    factura['base_imponible'] = float(base_imponible_sin_oc + base_imponible_oc)
    factura['exento'] = float(exento_oc + exento_sin_oc)
    factura['iva'] = float(iva_16_oc + iva_16_sin_oc)
    factura['total_neto'] = float(factura['base_imponible'] + factura['exento'] + factura['iva'])
    factura['total_bruto'] = float(total_bruto_oc + total_bruto_sin_oc)
    factura['moneda'] = moneda_operacion
    return factura
