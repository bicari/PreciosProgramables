from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepInFrame
)
from io import BytesIO
from datetime import datetime

def generar_factura(filename, pedido: dict, logo_path=None, preliminar: bool = False):
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
            


        empresa_info = [
            Paragraph(f"Usuario: {pedido['usuario'].upper()}", styles["Normal"]),
        ]
        nro_pedido = str(pedido['id']).rjust(7,'0')
        factura_datos = [Paragraph(f"<b>Nota Entrega #{nro_pedido}</b>", styles["Heading2"]),
                        Paragraph(f"Fecha Recepción: {datetime.now().strftime('%d-%m-%Y')}", styles["Normal"]),
                        Paragraph(f"Hora Recepción: {datetime.now().strftime('%H:%M')}")
        #Paragraph("Vencimiento: 10/09/2025", styles["Normal"])
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
            ["Cliente / Rif",  "Comentario"],
            [Paragraph(pedido['proveedor']), Paragraph(pedido['comentario'])],
            [Paragraph(pedido['rif'])],
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

        # ---- Tabla de productos (ajustable en varias páginas) ----
        data_items = [["Código","Descripción", "Costo", "Cantidad", "Total"]] 
        
        estilos_tabla = [
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("TEXTCOLOR", (0,0), (-1,0), colors.black),
            ("ALIGN", (0,0), (1,-1), "LEFT"),     # Código y Descripción
            ("ALIGN", (2,0), (4,-1), "RIGHT"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            #("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold")
        ]
        for productos in pedido["ordenes"]:
            data_items.append([productos["codigo"],  
                            Paragraph(productos['descripcion'], styles['Normal']), 
                            f'{productos["costo"]:.2f}', 
                            f'{productos["cantidad"]:.2f}', 
                            f'{(productos["costo"] * productos["cantidad"]):.2f}'])

        for productos_sin_oc in pedido['productoSinOc']:
            fila_actual =  len(data_items)
            data_items.append([productos_sin_oc["codigo"],  
                            Paragraph(productos_sin_oc["descripcion"], styles['Normal']), 
                            f'{productos_sin_oc["costoBS"]:.2f}', 
                            f'{productos_sin_oc["cantidad"]:.2f}', 
                            f'{(productos_sin_oc["costoBS"] * productos_sin_oc["cantidad"]):.2f}'])
            estilos_tabla.append(("BACKGROUND", (0,fila_actual), (-1,fila_actual), colors.coral))
                
            
        tabla_items = Table(data_items, colWidths=[80, 250, 80, 80, 80], repeatRows=1)  # repeatRows mantiene encabezado
        tabla_items.setStyle(TableStyle(estilos_tabla))
        elements.append(tabla_items)
        elements.append(Spacer(1, 20))
        #print(data_items)
        # ---- Footer con total ----
        #total_value = pedido['total_neto']#sum(10.0 * int(cant) for cant in pedido["productos"].values())
        #total = [["", "", "TOTAL:", f"{total_value:.2f}"]]
        #tabla_total = Table(total, colWidths=[80, 300, 80, 80, 80])
        #tabla_total.setStyle(TableStyle([
        #    ("TEXTCOLOR", (2,0), (2,0), colors.black),
        #    ("BACKGROUND", (2,0), (3,0), colors.lightgrey),
        #    ("ALIGN", (2,0), (3,0), "CENTER"),
        #    ("FONTNAME", (2,0), (3,0), "Helvetica-Bold"),
        #    ("GRID", (2,0), (3,0), 0.5, colors.grey),
        #]))
        #elements.append(tabla_total)

        # ---- Sección de condiciones ----
        
        # ---- Construir PDF ----
        doc.build(elements)
        if preliminar:
            pdf_bytes = buffer.getvalue()
            buffer.close()
            return pdf_bytes    
    except Exception as e:
        print(f"Error al generar la factura: {e}")

#pedido = {'id':'PRELIMINAR', 'direccion_cliente':'Maracay', 'cliente': 'E80338646', 'productos': {'01010001': {'cantidad': 23.0, 'descuento': 10, 'descripcion': 'MARCADOR PIZARRA PUNTA CINCEL OFIMAK REF OK93P', 'impuesto': 16, 'precio_sin_iva': 48.5, 'precio': 56.26, 'precio_con_descuento': 43.65, 'monto_iva': 6.98, 'precio_venta': 50.63, 'subtotal': 1164.49}, '01010009': {'cantidad': 2.0, 'descuento': 0, 'descripcion': 'TABLA D/INVENTARIO T/OFICIO OFIMAK REF  EN MADERA', 'impuesto': 0, 'precio_sin_iva': 2.0, 'precio': 2.0, 'precio_con_descuento': 2.0, 'monto_iva': 0.0, 'precio_venta': 2.0, 'subtotal': 4.0}, '01020003': {'cantidad': 1.0, 'descuento': 0, 'descripcion': 'ENGRAPADORA OFIMAK REF OK07B C/AZUL P/GRAPAS LISAS/CORRUG 120X60X20MM', 'impuesto': 16, 'precio_sin_iva': 5.87, 'precio': 6.81, 'precio_con_descuento': 5.87, 'monto_iva': 0.94, 'precio_venta': 6.81, 'subtotal': 6.81}, '07080059': {'cantidad': 2.0, 'descuento': 0, 'descripcion': 'TALADRO 1/2 BRUSHLESS BARETOOL GBS 18V-150 C BOCHS REF. 06019J51E0 / 03-32-011', 'impuesto': 16, 'precio_sin_iva': 867.98, 'precio': 1006.86, 'precio_con_descuento': 867.98, 'monto_iva': 138.88, 'precio_venta': 1006.86, 'subtotal': 2013.72}}, 'precio': 'P1', 'comentario': 'Despacho en 2 dias para entregar el 30 de agosto de 2025', 'total': 0.0, 'descripcion_cliente': 'RAUL ARAGUNDI', 'vendedor': '04', 'baseimponible': 2745.78, 'exento': 4.0, 'total_bruto': 2749.78, 'iva_16': 439.32, 'total_neto': 3189.1, 'nombre_vendedor': 'Carlos Aranguren', 'pedido':11}
#nota = {'ordenes': [{'codigo': '01020003', 'orden': '00009921', 'descripcion':'Ratón recarcagable' ,'cantidad': 16, 'diferencia': -15, 'recibido': 1, 'costo': 136.73, 'iva': 16, 'moneda': '1', 'deposito': '1'}], 
#        'productoSinOc': [{'codigo': '01020003', 'descripcion':'Teclado RetroIluminado' ,'cantidad': 16, 'costoBS': 20, 'costoUS': 25}], 'proveedor': 'A2CONSULTORES ARAGUA, C.A.', 'rif': 'J407903691', 'usuario': 'Carlos Aranguren', 'id': 10357,
#        'direccion_proveedor': 'Maracay Av Aragua', 'comentario': 'Entrega parcial de la orden 00009921'}
#generar_factura("factura_reportlab_logo.pdf", nota, logo_path="C:\Proyectos\Python\Precios-KsaHome\static\KsaHome.png", preliminar=False)
