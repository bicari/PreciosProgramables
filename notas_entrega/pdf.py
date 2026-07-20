import logging
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.enums import TA_RIGHT, TA_LEFT
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepInFrame
)
from io import BytesIO
from datetime import datetime
from reportlab.platypus import Flowable

logger = logging.getLogger(__name__)


class EmpujarAlFondo(Flowable):
    """
    Este componente ocupa todo el espacio vertical disponible en la página
    menos una altura reservada para el footer.
    """
    def __init__(self, altura_footer):
        Flowable.__init__(self)
        self.altura_footer = altura_footer

    def wrap(self, availWidth, availHeight):
        # Si no hay espacio suficiente para el footer, forzamos salto de pág
        if availHeight < self.altura_footer:
            return (availWidth, availHeight + 1) 
        # Si hay espacio, ocupamos todo menos lo que necesita el footer
        return (availWidth, availHeight - self.altura_footer)

    def draw(self):
        pass # No dibuja nada, es un espacio invisible

def formatear_numeros(valor):
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def validar_moneda(moneda: str):
    pass

def generar_factura(filename, pedido: dict[list[dict]], logo_path=None, preliminar: bool = False):
    try:
        
        buffer = BytesIO()
        if preliminar:
            doc = SimpleDocTemplate(buffer, pagesize=LETTER, leftMargin=30,   # en puntos (72 = 1 pulgada)
                rightMargin=30,
                topMargin=10,
                bottomMargin=10)
        else:    
            doc = SimpleDocTemplate(filename, pagesize=LETTER, leftMargin=30,   # en puntos (72 = 1 pulgada)
                rightMargin=30,
                topMargin=10,
                bottomMargin=10)
        elements = []
        
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="Center", alignment=1, fontSize=14, spaceAfter=8))
        styles.add(ParagraphStyle(name="Conditions", fontSize=9, leading=12, spaceBefore=20))

        # ---- Encabezado con logo + datos empresa ----
        logo = None
        if logo_path:
            logo = Image(logo_path, width=150, height=100,)  # Tamaño variable
            logo.hAlign = "LEFT"
            #logo.drawOn(doc, doc.leftMargin, doc.height + doc.topMargin - 50)
            
        
        doc_origen = set(oc['orden'].lstrip('0') for oc in pedido['ordenes'])
        style_right = ParagraphStyle(name='AlignRight', parent=styles['Normal'], alignment=TA_RIGHT)
        empresa_info = [
            Paragraph(f"Usuario: {pedido['usuario'].upper()}", styles["Normal"]),
            Paragraph(f"Doc Afectados: [{','.join(doc_origen)}]", style_right)

        ]
        nro_pedido = str(pedido['id']).rjust(8,'0')
        factura_datos = [Paragraph(f"<b>Nota Entrega #{nro_pedido}</b>", styles["Heading2"]),
                        Paragraph(f"Fecha Recepción: {datetime.now().strftime('%d-%m-%Y')}", styles["Normal"]),
                        Paragraph(f"Hora Recepción: {datetime.now().strftime('%H:%M')}"),
                        Paragraph("Deposito Origen: Almacen", styles["Normal"])
        ]
        

        encabezado_data = [[logo, factura_datos]] if logo else [["", empresa_info]]
        tabla_encabezado = Table(encabezado_data, colWidths=[420,200])
        tabla_encabezado.setStyle(TableStyle([
            ("ALIGN", (0,0), (0, 0), "LEFT"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN", (1,0), (1, 0), "RIGHT"),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            #("ALIGN", (2,0), (2, 0), "RIGHT")
        ]))
        elements.append(tabla_encabezado)
        elements.append(Spacer(1, 10))
        empresa_info_table = Table([empresa_info])
        empresa_info_table.setStyle([("ALIGN", (0,0), (0, 0), "LEFT")])
        elements.append(empresa_info_table)

        # ---- Info factura ----
        # elements.append(Paragraph("<b>Factura #00001</b>", styles["Heading2"]))
        # elements.append(Paragraph("Fecha: 02/09/2025", styles["Normal"]))
        # elements.append(Paragraph("Vencimiento: 10/09/2025", styles["Normal"]))
        # elements.append(Spacer(1, 20))

        # ---- Bill To / Ship To ----
        data_clientes = [
            ["Proveedor / Rif",  "Dirección / Comentario"],
            [Paragraph(pedido['proveedor']), Paragraph(pedido['direccion_proveedor'])],
            [Paragraph(pedido['rif']), Paragraph(pedido['comentario']) ],
        ]
        tabla_clientes = Table(data_clientes, colWidths=[300, 250])
        tabla_clientes.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("TEXTCOLOR", (0,0), (-1,0), colors.black),
            ("ALIGN", (0,0), (-1,-1), "LEFT"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0,0), (-1,0), 8)
        ]))
        elements.append(tabla_clientes)
        elements.append(Spacer(1, 20))
        estilo_celda = styles['Normal'].clone('estilo_celda')
        estilo_celda.alignment = TA_LEFT
        estilo_celda.fontSize = 8.5
        
        # ---- Tabla de productos
        data_items = [["Código","Cod Barra","Cod Prov","Descripción", "Puesto", "Und", "Ctdad", "Costo", "Total"]] 
        
        estilos_tabla = [
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("TEXTCOLOR", (0,0), (-1,0), colors.black),
            ("ALIGN", (0,0), (-1,-1), "LEFT"),     # Código y Descripción
            ("ALIGN", (5,1), (-1,-1), "RIGHT"),
            ("ALIGN", (5,0), (-1,-1), "RIGHT"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            #("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            #Encabezado
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,0),  10),
            #Filas
            ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,1), (-1,-1),  8.5),
            #Paddin o separacion de texto
            ("LEFTPADDING", (0,0), (-1,-1), 5),
            ("RIGHTPADDING", (0,0), (-1,-1), 5)

        ]
        valor_moneda = '0'
        for productos in pedido["ordenes"]:
            valor_moneda = productos.get('moneda', '0')
              
            data_items.append([
                            Paragraph(productos.get('codigo', ''), estilo_celda),  
                            Paragraph(productos.get('referencia', ''), estilo_celda),
                            Paragraph(productos.get('ref_proveedor', ''), estilo_celda),   
                            Paragraph(productos.get('descripcion', ''), estilo_celda), 
                            Paragraph(productos.get('puesto', ''), estilo_celda),"",
                            formatear_numeros(productos['recibido']),
                            formatear_numeros(productos["costo"]),
                            formatear_numeros(productos['costo'] * productos['recibido'])
                            ])
        base_imponible_sin_oc = 0
        sin_oc = set()
        for productos_sin_oc in pedido['productoSinOc']:
            cantidad = productos_sin_oc['cantidad']
            sin_oc.add(productos_sin_oc['codigo'])
            if valor_moneda == '1':
                costo = formatear_numeros(productos_sin_oc['costoBS'])
                total = formatear_numeros(productos_sin_oc['costoBS'] * productos_sin_oc['cantidad']) 
                base_imponible_sin_oc += productos_sin_oc['costoBS'] * productos_sin_oc['cantidad']      
            else:
                costo = formatear_numeros(productos_sin_oc['costoUS'])
                total = formatear_numeros(productos_sin_oc['costoUS'] * productos_sin_oc['cantidad'])       
                base_imponible_sin_oc += productos_sin_oc['costoUS'] * productos_sin_oc['cantidad']
            fila_actual =  len(data_items)
            data_items.append([
                            Paragraph(productos_sin_oc.get('codigo', ''), estilo_celda),
                            Paragraph(productos_sin_oc.get('referencia', ''), estilo_celda),
                            Paragraph(productos_sin_oc.get('ref_proveedor', ''), estilo_celda),     
                            Paragraph(productos_sin_oc.get('descripcion', ''), estilo_celda),
                            Paragraph(productos_sin_oc.get('puesto', ''), estilo_celda), "",
                            formatear_numeros(productos_sin_oc["cantidad"]), 
                            costo,
                            total
                            ])
            estilos_tabla.append(("BACKGROUND", (0,fila_actual), (-1,fila_actual), colors.coral))
                
            
        tabla_items = Table(data_items, colWidths=[60, 60, 50, 140, 40, 50, 50, 70, 70], repeatRows=1)  # repeatRows mantiene encabezado
        tabla_items.setStyle(TableStyle(estilos_tabla))
        elements.append(tabla_items)
        elements.append(Spacer(1, 20))
        #print(data_items)
        # ---- Footer con total ----
        
        
        pendientes = [items['codigo'] for items in pedido['ordenes'] if items['diferencia'] < 0 ]
        excedentes = [items['codigo'] for items in pedido['ordenes'] if items['diferencia'] > 0 ]
        observaciones_texto = f"Sin OC: <b>{','.join(sin_oc)}</b><br/>Pendiente:<b>{','.join(pendientes)}</b><br/>Excedentes:<b>{','.join(excedentes)}</b>"

        
        # 3. Creamos la sub-tabla de Totales (Derecha)
        #    Estructura: [Subtotal], [IVA], [TOTAL]
        sub_data_totales = [
            ["Base Imponible:", formatear_numeros(pedido['base_imponible'])],
            ["Exento:", formatear_numeros(pedido['exento'])], # Ejemplo
            ["IVA (16%):", formatear_numeros(pedido['iva'])],
            ["TOTAL:", formatear_numeros(pedido['total_neto'])]
        ]
        tabla_montos = Table(sub_data_totales, colWidths=[80, 80])
        tabla_montos.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'), # Negrita al Total
            ('LINEABOVE', (0,-1), (-1,-1), 1, colors.black),  # Linea sobre el total
            ('PADDING', (0,0), (-1,-1), 2),
        ]))

        # 4. Creamos el contenido de Observaciones (Izquierda)
        estilo_obs = styles["Normal"].clone('Obs')
        estilo_obs.fontSize = 8
        parrafo_obs =  [Paragraph(f"<b>Elaborado por:____________________________</b><br/><b>OBSERVACIONES:</b><br/>{observaciones_texto}", estilo_obs), 
                        ] 

        # 5. Tabla contenedora Principal (Footer completo)
        #    Columna 1: Observaciones (ancho dinámico), Columna 2: Totales
        ancho_pagina = doc.width  # El ancho útil definido en SimpleDocTemplate
        ancho_totales = 170
        ancho_obs = ancho_pagina - ancho_totales
        
        data_footer = [[parrafo_obs, tabla_montos]]
        
        tabla_footer = Table(data_footer, colWidths=[ancho_obs, ancho_totales])
        tabla_footer.setStyle(TableStyle([
            # Borde exterior estilizado (Cuadro)
            ('BOX', (0,0), (-1,-1), 1, colors.darkgreen),
            ('ROUNDEDCORNERS', [10, 10, 10, 10]), # Opcional si tu versión de RL lo soporta
            
            # Fondo y color
            ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
            
            # Separador vertical entre observaciones y totales (opcional)
            ('LINEAFTER', (0,0), (0,-1), 1, colors.grey),
        ]))

        # 6. Calcular altura estimada del footer para reservar espacio
        w, h = tabla_footer.wrap(ancho_pagina, doc.height)
        
        # 7. INYECCIÓN EN EL PDF
        # Primero empujamos hacia abajo
        elements.append(EmpujarAlFondo(altura_footer=h))
        # Luego ponemos el footer
        
        elements.append(tabla_footer)

        #elements.append(tabla_total)

        # ---- Sección de condiciones ----
        
        # ---- Construir PDF ----
        doc.build(elements)
        if preliminar:
            pdf_bytes = buffer.getvalue()
            buffer.close()
            return pdf_bytes    
    except Exception as e:
        logger.exception('generar_factura failed')
        raise

def generar_reporte_notas(notas: list[dict], fecha_desde: str, fecha_hasta: str):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        leftMargin=30, rightMargin=30, topMargin=20, bottomMargin=20
    )
    elements = []
    styles = getSampleStyleSheet()

    # Titulo
    elements.append(Paragraph("<b>Reporte de Notas de Entrega</b>", styles["Heading2"]))
    elements.append(Paragraph(
        f"Desde: {fecha_desde} &nbsp;&nbsp; Hasta: {fecha_hasta} &nbsp;&nbsp; Total: {len(notas)} notas",
        styles["Normal"]
    ))
    elements.append(Spacer(1, 15))

    # Tabla
    estilo_celda = styles['Normal'].clone('celda_reporte')
    estilo_celda.fontSize = 8.5

    data = [["#", "Nro Documento", "Fecha Recepcion", "Proveedor", "RIF", "Items", "Total", "Moneda"]]

    for i, nota in enumerate(notas, 1):
        data.append([
            str(i),
            nota['documento'],
            nota['fecha'],
            Paragraph(nota['proveedor'], estilo_celda),
            nota['rif'],
            str(nota['total_items']),
            formatear_numeros(nota['total_neto']),
            nota['moneda'],
        ])

    tabla = Table(data, colWidths=[25, 75, 75, 155, 75, 40, 70, 40], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (5, 0), (5, -1), "CENTER"),
        ("ALIGN", (6, 0), (6, -1), "RIGHT"),
        ("ALIGN", (7, 0), (7, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(tabla)

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


#pedido = {'id':'PRELIMINAR', 'direccion_cliente':'Maracay', 'cliente': 'E80338646', 'productos': {'01010001': {'cantidad': 23.0, 'descuento': 10, 'descripcion': 'MARCADOR PIZARRA PUNTA CINCEL OFIMAK REF OK93P', 'impuesto': 16, 'precio_sin_iva': 48.5, 'precio': 56.26, 'precio_con_descuento': 43.65, 'monto_iva': 6.98, 'precio_venta': 50.63, 'subtotal': 1164.49}, '01010009': {'cantidad': 2.0, 'descuento': 0, 'descripcion': 'TABLA D/INVENTARIO T/OFICIO OFIMAK REF  EN MADERA', 'impuesto': 0, 'precio_sin_iva': 2.0, 'precio': 2.0, 'precio_con_descuento': 2.0, 'monto_iva': 0.0, 'precio_venta': 2.0, 'subtotal': 4.0}, '01020003': {'cantidad': 1.0, 'descuento': 0, 'descripcion': 'ENGRAPADORA OFIMAK REF OK07B C/AZUL P/GRAPAS LISAS/CORRUG 120X60X20MM', 'impuesto': 16, 'precio_sin_iva': 5.87, 'precio': 6.81, 'precio_con_descuento': 5.87, 'monto_iva': 0.94, 'precio_venta': 6.81, 'subtotal': 6.81}, '07080059': {'cantidad': 2.0, 'descuento': 0, 'descripcion': 'TALADRO 1/2 BRUSHLESS BARETOOL GBS 18V-150 C BOCHS REF. 06019J51E0 / 03-32-011', 'impuesto': 16, 'precio_sin_iva': 867.98, 'precio': 1006.86, 'precio_con_descuento': 867.98, 'monto_iva': 138.88, 'precio_venta': 1006.86, 'subtotal': 2013.72}}, 'precio': 'P1', 'comentario': 'Despacho en 2 dias para entregar el 30 de agosto de 2025', 'total': 0.0, 'descripcion_cliente': 'RAUL ARAGUNDI', 'vendedor': '04', 'baseimponible': 2745.78, 'exento': 4.0, 'total_bruto': 2749.78, 'iva_16': 439.32, 'total_neto': 3189.1, 'nombre_vendedor': 'Carlos Aranguren', 'pedido':11}
# nota = {'ordenes': [{'codigo': '01020003', 'referencia':'7598002881124','ref_proveedor':'7594544454','orden': '00009921', 'descripcion':'Ratón recarcagable' ,'cantidad': 16, 'diferencia': -15, 'recibido': 1, 'costo': 20, 'iva': 16, 'iva_16_monto': 3.2, 'moneda': '1', 'deposito': '1', 'puesto': '25-LS-A'},
#                     {'codigo': '01020003', 'referencia':'7598002881124','orden': '00009922', 'descripcion':'Ratón recarcagable' ,'cantidad': 16, 'diferencia': -15, 'recibido': 1, 'costo': 1500, 'iva': 16, 'iva_16_monto':240,'moneda': '1', 'deposito': '1', 'puesto': '25-LS-A'},
#                     {'codigo': '01020003', 'orden': '00009923', 'descripcion':'SOBRE MANILA CARTA REF OK025A MARRON Y GRIS' ,'cantidad': 16, 'diferencia': -15, 'recibido': 100000, 'costo': 136.73, 'iva': 16, 'iva_16_monto':2187680,'moneda': '1', 'deposito': '1', 'puesto': '25-LS-A'},
#                     {'codigo': '01020003', 'orden': '00009924', 'descripcion':'Ratón recarcagable' ,'cantidad': 16, 'diferencia': 2, 'recibido': 1, 'costo': 12.73, 'iva': 16, 'iva_16_monto':2.03, 'moneda': '1', 'deposito': '1', 'puesto': '25-LS-A'}], 
#         'productoSinOc': [{'codigo': '01020003', 'descripcion':'Teclado RetroIluminado' ,'cantidad': 16, 'costoBS': 20, 'costoUS': 25, 'puesto': 'ls22', 'iva': 16}], 'proveedor': 'A2CONSULTORES ARAGUA, C.A.', 'rif': 'J407903691', 'usuario': 'Carlos Aranguren', 'id': 10357,
#         'direccion_proveedor': 'Av 101 Diaz Moreno, Edif Oficentro 108 Piso 2 OF 2-A', 'comentario': 'Entrega parcial de la orden 00009921'}
# generar_factura("factura_reportlab_logo.pdf", nota, logo_path="C:\Proyectos\Python\Precios-KsaHome\static\KsaHome.png", preliminar=False)
