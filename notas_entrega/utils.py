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
            to=settings.EMAIL_RECEPCIONES,  # Email del primer admin
            
            )
    mail.attach
    mail.content_subtype = "html"
    mail.attach(f'Nota_Entrega_{nro_documento}.pdf', bytes_pdf, 'application/pdf')
    mail.send()


def calcular_totales(factura: dict):
     moneda_operacion =  factura['ordenes'][0]['moneda']
     total_bruto_oc = sum(list(map(lambda item: item['costo'] * item['recibido'] , factura['ordenes'])))
     base_imponible_oc = sum([item['costo'] * item['recibido'] for item in factura['ordenes'] if item['iva'] == 16])
     exento_oc = sum([item['costo'] * item['recibido'] for item in factura['ordenes'] if item['iva'] == 0])
     iva_16_oc = base_imponible_oc * .16
     #total_oc = total_bruto_oc + iva_16_oc 
     if moneda_operacion.__contains__('1'):
          total_bruto_sin_oc = sum(list(map(lambda item: item['costoBS'] * item['cantidad'] , factura['productoSinOc'])))
          base_imponible_sin_oc = sum([item['costoBS'] * item['cantidad'] for item in factura['productoSinOc'] if item['iva'] == 16])
          exento_sin_oc = sum([item['costoBS'] * item['cantidad'] for item in factura['productoSinOc'] if item['iva'] == 0])
          iva_16_sin_oc = base_imponible_sin_oc * .16

     else:
          total_bruto_sin_oc = sum(list(map(lambda item: item['costoUS'] * item['cantidad'] , factura['productoSinOc'])))
          base_imponible_sin_oc = sum([item['costoBS'] * item['cantidad'] for item in factura['productoSinOc'] if item['iva'] == 16])
          exento_sin_oc = sum([item['costoUS'] * item['cantidad'] for item in factura['productoSinOc'] if item['iva'] == 0])
          iva_16_sin_oc = base_imponible_sin_oc * .16
     factura['base_imponible'] = base_imponible_sin_oc + base_imponible_oc
     factura['exento'] = exento_oc + exento_sin_oc
     factura['iva'] = iva_16_oc + iva_16_sin_oc
     factura['total_neto'] = factura['base_imponible'] + factura['exento'] + factura['iva']    
     factura['total_bruto'] = total_bruto_oc + total_bruto_sin_oc 
     factura['moneda'] = moneda_operacion
     #print(f"Base Im: {base_imponible_oc}\n Exento: {exento_oc}\n Iva: {iva_16_oc}\n Total:{total_oc}")      
     return factura
           


      
#factura =  {'ordenes': [{'codigo': '01010006', 'orden': '00009929', 'cantidad': 12, 'diferencia': 0, 'recibido': 12, 'costo': 9.87, 'iva': 0, 'moneda': '1', 'deposito': '1', 'descripcion': 'CARPETA FIBRA MARRON CARTA OFIMAK REF 02614E', 'autoincrement': 269, 'puesto': 'ALMACEN', 'referencia': '10005', 'ref_proveedor': '02614E', 'iva_16_monto': 1.579}, {'codigo': '01010015', 'orden': '00009929', 'cantidad': 1, 'diferencia': 0, 'recibido': 1, 'costo': 293.7, 'iva': 16, 'moneda': '1', 'deposito': '1', 'descripcion': 'RESMA PAPEL  CARTA BLANCO REF 7005038', 'autoincrement': 269, 'puesto': 'ALMACEN', 'referencia': '7891173019448', 'ref_proveedor': '7005038', 'iva_16_monto': 46.992}, {'codigo': '01010017', 'orden': '00009929', 'cantidad': 1, 'diferencia': 0, 'recibido': 1, 'costo': 33.87, 'iva': 16, 'moneda': '1', 'deposito': '1', 'descripcion': 'CARPETA CLIP DE SUJECION DE PLASTICO A4 REF OK344', 'autoincrement': 269, 'puesto': 'ALMACEN', 'referencia': '0663701985467', 'ref_proveedor': 'OK344', 'iva_16_monto': 5.419}], 'productoSinOc': [], 'proveedor': 'A2CONSULTORES ARAGUA, C.A.', 'rif': 'J407903691', 'comentario': '', 'direccion_proveedor': 'CALLE MARIÑO SUR, CENTRO EMPRESARIAL UNIARAGUA, PISO 3, OFICINA 303, MARACAY EDO. ARAGUA', 'usuario': 'bicari'}
#print(calcular_totales(factura))