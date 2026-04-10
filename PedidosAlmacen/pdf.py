from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


_AZUL_OSCURO = colors.HexColor("#2c3e50")
_AZUL_CLARO = colors.HexColor("#3498db")
_GRIS_CLARO = colors.HexColor("#f2f2f2")
_VERDE = colors.HexColor("#27ae60")
_NARANJA = colors.HexColor("#e67e22")
_ROJO = colors.HexColor("#e74c3c")
_MORADO = colors.HexColor("#8e44ad")

_LABEL_ESTADO = {
    "PENDIENTE": "Pendiente",
    "PICKING": "Picking",
    "DESPACHADO": "Despachado",
    "RECIBIDO": "Recibido",
    "CERRADO": "Cerrado",
}
_LABEL_CONDICION = {
    "URGENTE": "Urgente",
    "SURTIDO": "Surtido",
    "CLIENTE_RETIRA": "Cliente Retira",
}


def _kpi_card(titulo: str, valor: str, color) -> Table:
    """Tarjeta KPI para la fila de resumen."""
    st_val = ParagraphStyle("kv", fontSize=18, textColor=color, alignment=TA_CENTER,
                             leading=22, fontName="Helvetica-Bold")
    st_lbl = ParagraphStyle("kl", fontSize=8, textColor=colors.grey, alignment=TA_CENTER)
    t = Table([[Paragraph(valor, st_val)], [Paragraph(titulo, st_lbl)]], colWidths=[105])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, color),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
    ]))
    return t


def _dist_table(filas: list[tuple[str, int]], total: int, ancho: int) -> Table:
    """Tabla de distribucion con descripcion, cantidad y porcentaje."""
    st = ParagraphStyle("dc", fontSize=8, leading=10)
    data = [[Paragraph("<b>Descripcion</b>", st), Paragraph("<b>Cant.</b>", st),
             Paragraph("<b>%</b>", st)]]
    for nombre, cantidad in filas:
        pct = f"{round(cantidad / total * 100)}%" if total else "0%"
        data.append([Paragraph(str(nombre), st), str(cantidad), pct])
    if not filas:
        data.append([Paragraph("Sin datos", st), "-", "-"])

    t = Table(data, colWidths=[ancho - 65, 33, 32])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _GRIS_CLARO),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GRIS_CLARO]),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _seccion_header(texto: str, ancho: int) -> Table:
    st = ParagraphStyle("sh", fontSize=10, textColor=colors.white,
                         fontName="Helvetica-Bold", leftPadding=6)
    t = Table([[Paragraph(texto, st)]], colWidths=[ancho])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _AZUL_OSCURO),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def generar_reporte_pedidos_pdf(ctx: dict) -> bytes:
    """
    Genera el PDF del reporte de pedidos de almacen.

    Args:
        ctx: Diccionario con los datos calculados en la vista reporte_pedidos.
            Claves requeridas: total_pedidos, total_solicitado, total_despachado,
            total_recibido, tiempo_horas, tiempo_minutos, categoria_top, condicion_top,
            por_estado, por_condicion, por_categoria, fecha_inicio, fecha_fin,
            categoria_filtro, condicion_filtro.

    Returns:
        Bytes del PDF generado.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        leftMargin=35, rightMargin=35, topMargin=25, bottomMargin=25,
    )
    styles = getSampleStyleSheet()
    elements = []

    # ---- Encabezado ----
    st_titulo = ParagraphStyle("t", fontSize=16, textColor=_AZUL_OSCURO,
                                spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica-Bold")
    st_sub = ParagraphStyle("s", fontSize=9, textColor=colors.grey,
                             spaceAfter=2, alignment=TA_CENTER)

    elements.append(Paragraph("Reporte de Pedidos Almacen", st_titulo))

    filtros = []
    if ctx.get("fecha_inicio"):
        filtros.append(f"Desde: {ctx['fecha_inicio']}")
    if ctx.get("fecha_fin"):
        filtros.append(f"Hasta: {ctx['fecha_fin']}")
    if ctx.get("categoria_filtro"):
        filtros.append(f"Categoria: {ctx['categoria_filtro']}")
    if ctx.get("condicion_filtro"):
        filtros.append(f"Condicion: {_LABEL_CONDICION.get(ctx['condicion_filtro'], ctx['condicion_filtro'])}")
    if filtros:
        elements.append(Paragraph(" | ".join(filtros), st_sub))
    elements.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}", st_sub))
    elements.append(Spacer(1, 14))

    # ---- Fila de KPIs ----
    tiempo_horas = ctx.get("tiempo_horas")
    tiempo_minutos = ctx.get("tiempo_minutos")
    tiempo_str = f"{tiempo_horas}h {tiempo_minutos}m" if tiempo_horas is not None else "N/D"
    tiempo_color = _NARANJA if tiempo_horas is not None else colors.grey

    pct_inc = ctx.get("pct_incidencias", 0)
    inc_color = _ROJO if pct_inc > 20 else (_NARANJA if pct_inc > 10 else _VERDE)

    kpis = Table([[
        _kpi_card("Total Pedidos", str(ctx["total_pedidos"]), _AZUL_CLARO),
        _kpi_card("Unid. Solicitadas", str(ctx["total_solicitado"]), _MORADO),
        _kpi_card("Unid. Despachadas", str(ctx["total_despachado"]), _VERDE),
        _kpi_card("Unid. Recibidas", str(ctx["total_recibido"]), _AZUL_OSCURO),
        _kpi_card("T. Prom. Despacho", tiempo_str, tiempo_color),
        _kpi_card("% Incidencias", f"{pct_inc}%", inc_color),
    ]], colWidths=[88, 88, 88, 88, 88, 88])
    kpis.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(kpis)
    elements.append(Spacer(1, 14))

    # ---- Destacados ----
    cat_top = ctx.get("categoria_top")
    cond_top = ctx.get("condicion_top")
    pedidos_con_inc = ctx.get("pedidos_con_incidencia", 0)
    items_inc = ctx.get("total_items_incidencia", 0)

    st_norm = styles["Normal"].clone("n8")
    st_norm.fontSize = 8.5
    st_dest_cat = ParagraphStyle("dcat", fontSize=11, textColor=_AZUL_CLARO, fontName="Helvetica-Bold")
    st_dest_cond = ParagraphStyle("dcond", fontSize=11, textColor=_ROJO, fontName="Helvetica-Bold")
    st_dest_inc = ParagraphStyle("dinc", fontSize=11, textColor=inc_color, fontName="Helvetica-Bold")

    destacados = Table(
        [
            [Paragraph("<b>Categoria mas despachada</b>", st_norm),
             Paragraph("<b>Condicion mas usada</b>", st_norm),
             Paragraph("<b>Incidencias</b>", st_norm)],
            [
                Paragraph(
                    f"{cat_top['categoria']}  ({cat_top['total']} pedidos)" if cat_top else "Sin datos",
                    st_dest_cat
                ),
                Paragraph(
                    f"{_LABEL_CONDICION.get(cond_top['condicion'], cond_top['condicion'])}  ({cond_top['total']} pedidos)"
                    if cond_top else "Sin datos",
                    st_dest_cond
                ),
                Paragraph(
                    f"{pedidos_con_inc} pedido(s) — {items_inc} item(s) afectado(s)",
                    st_dest_inc
                ),
            ],
        ],
        colWidths=[175, 175, 174]
    )
    destacados.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, colors.lightgrey),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), _GRIS_CLARO),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(destacados)
    elements.append(Spacer(1, 16))

    # ---- Tablas de distribucion ----
    ancho_col = 170
    total = ctx["total_pedidos"]

    por_estado = list(ctx["por_estado"])
    por_condicion = list(ctx["por_condicion"])
    por_categoria = list(ctx["por_categoria"])

    filas_estado = [(_LABEL_ESTADO.get(i["estado"], i["estado"]), i["total"]) for i in por_estado]
    filas_condicion = [(_LABEL_CONDICION.get(i["condicion"], i["condicion"]), i["total"]) for i in por_condicion]
    filas_categoria = [(i["categoria"], i["total"]) for i in por_categoria]

    sep = Spacer(10, 1)

    # Fila de encabezados de seccion
    encabezados = Table(
        [[_seccion_header("Por Estado", ancho_col), sep,
          _seccion_header("Por Condicion", ancho_col), sep,
          _seccion_header("Top Categorias", ancho_col)]],
        colWidths=[ancho_col, 10, ancho_col, 10, ancho_col]
    )
    encabezados.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(encabezados)

    # Fila de datos
    datos = Table(
        [[_dist_table(filas_estado, total, ancho_col), sep,
          _dist_table(filas_condicion, total, ancho_col), sep,
          _dist_table(filas_categoria, total, ancho_col)]],
        colWidths=[ancho_col, 10, ancho_col, 10, ancho_col]
    )
    datos.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(datos)

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
