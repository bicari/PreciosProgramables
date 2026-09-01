from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable


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
    "INSUMOS": "Insumos",
}

# Sufijo de título por variante de impresión ('' = sin sufijo).
_VISTA_LABEL = {
    "todos": "",
    "despachado": "Despachado",
    "back_order": "Back Order",
    "recibido": "Recibido",
    "parcial": "Parcial",
}
# Columnas de cantidad (encabezado, atributo del item) por variante filtrada.
_VISTA_CANTIDADES = {
    "despachado": [("Despachado", "cantidad_despachada")],
    "back_order": [("Back Order", "cantidad_back_order")],
    "recibido": [("Recibido", "cantidad_recibida")],
    "parcial": [("Despachado", "cantidad_despachada"), ("Back Order", "cantidad_back_order")],
}
# Anchos de columna (suman 542 pt) segun cantidad de columnas de cantidad extra.
# Cols fijas: Codigo, Descripcion, Referencia, Puesto, Ref.Prov, Solicitado, <cant...>, Observacion
_VISTA_WIDTHS = {
    1: [50, 150, 65, 52, 52, 45, 48, 80],
    2: [48, 132, 60, 48, 48, 42, 44, 44, 76],
}
# Anchos cuando se combinan 2+ vistas: se agrega columna "Estado" antes de Observacion.
# Cols fijas: Codigo, Descripcion, Referencia, Puesto, Ref.Prov, Solicitado, <cant...>, Estado, Observacion
_MULTI_VISTA_WIDTHS = {
    1: [48, 130, 60, 48, 48, 42, 46, 58, 62],
    2: [46, 116, 55, 44, 44, 40, 42, 42, 55, 58],
    3: [44, 100, 50, 42, 42, 38, 38, 38, 38, 52, 60],
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


def generar_reporte_pickers_pdf(ctx: dict) -> bytes:
    """
    Genera el PDF del reporte de estadisticas por picker.

    Args:
        ctx: Diccionario con los datos calculados en _estadisticas_pickers.
            Claves requeridas: stats (lista de dicts por picker), totales,
            fecha_inicio, fecha_fin. Opcional: picker_filtro_nombre.

    Returns:
        Bytes del PDF generado.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        leftMargin=35, rightMargin=35, topMargin=25, bottomMargin=25,
    )
    elements = []

    # ---- Encabezado ----
    st_titulo = ParagraphStyle("t", fontSize=16, textColor=_AZUL_OSCURO,
                                spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica-Bold")
    st_sub = ParagraphStyle("s", fontSize=9, textColor=colors.grey,
                             spaceAfter=2, alignment=TA_CENTER)

    elements.append(Paragraph("Estadisticas por Picker", st_titulo))

    filtros = []
    if ctx.get("fecha_inicio"):
        filtros.append(f"Desde: {ctx['fecha_inicio']}")
    if ctx.get("fecha_fin"):
        filtros.append(f"Hasta: {ctx['fecha_fin']}")
    if ctx.get("picker_filtro_nombre"):
        filtros.append(f"Picker: {ctx['picker_filtro_nombre']}")
    if filtros:
        elements.append(Paragraph(" | ".join(filtros), st_sub))
    elements.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}", st_sub))
    elements.append(Spacer(1, 14))

    # ---- Fila de KPIs ----
    totales = ctx["totales"]
    anulados_color = _ROJO if totales["anulados"] else colors.grey
    kpis = Table([[
        _kpi_card("Despachos", str(totales["despachos"]), _AZUL_CLARO),
        _kpi_card("Pedidos", str(totales["pedidos"]), _AZUL_OSCURO),
        _kpi_card("Uds. Pickeadas", str(totales["unidades"]), _VERDE),
        _kpi_card("Lineas", str(totales["lineas"]), _MORADO),
        _kpi_card("Desp. Anulados", str(totales["anulados"]), anulados_color),
    ]], colWidths=[108, 108, 108, 108, 108])
    kpis.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(kpis)
    elements.append(Spacer(1, 16))

    # ---- Tabla por picker ----
    elements.append(_seccion_header("Detalle por Picker", 542))

    st_cell = ParagraphStyle("pc", fontSize=8, leading=10)
    st_head = ParagraphStyle("ph", fontSize=8, leading=10, fontName="Helvetica-Bold")
    data = [[
        Paragraph("Picker", st_head), Paragraph("Despachos", st_head),
        Paragraph("Pedidos", st_head), Paragraph("Lineas", st_head),
        Paragraph("Productos", st_head), Paragraph("Uds. Pickeadas", st_head),
        Paragraph("Anulados", st_head),
    ]]
    for s in ctx["stats"]:
        data.append([
            Paragraph(s["picker__username"], st_cell),
            str(s["total_despachos"]), str(s["total_pedidos"]),
            str(s["total_lineas"]), str(s["total_productos"]),
            str(s["total_unidades"]), str(s["despachos_anulados"]),
        ])
    if not ctx["stats"]:
        data.append([Paragraph("Sin datos", st_cell), "-", "-", "-", "-", "-", "-"])
    else:
        data.append([
            Paragraph("Totales", st_head),
            str(totales["despachos"]), str(totales["pedidos"]),
            str(totales["lineas"]), "", str(totales["unidades"]),
            str(totales["anulados"]),
        ])

    tabla = Table(data, colWidths=[182, 60, 60, 60, 60, 60, 60], repeatRows=1)
    estilo = [
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
    ]
    if ctx["stats"]:
        estilo += [
            ("BACKGROUND", (0, -1), (-1, -1), _GRIS_CLARO),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, _AZUL_OSCURO),
        ]
    tabla.setStyle(TableStyle(estilo))
    elements.append(tabla)

    elements.append(Spacer(1, 10))
    st_nota = ParagraphStyle("nt", fontSize=7, textColor=colors.grey, leading=9)
    elements.append(Paragraph(
        "Un pedido atendido por varios pickers cuenta para cada uno; el total de pedidos no duplica. "
        "Las metricas excluyen despachos anulados (columna aparte) y solo incluyen usuarios del grupo Pedidos Picker. "
        "Los SKU no contemplados cuentan en lineas y unidades, pero no en productos distintos.",
        st_nota,
    ))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generar_pedido_pdf(pedido, items, vistas=("todos",), mostrar_cantidades: bool = False) -> bytes:
    """
    Genera el PDF de un pedido individual.

    Args:
        pedido: Instancia del modelo Pedido.
        items: QuerySet o lista de PedidoItem relacionados al pedido.
        vistas: Secuencia de claves de variante de impresion (ver _VISTA_LABEL).
            Con una sola vista filtrada, el PDF es identico al de antes de
            soportar combinaciones. Con dos o mas, se agrega una columna
            "Estado" y se unen las columnas de cantidad de cada vista.
        mostrar_cantidades: Si es True, incluye las columnas de cantidad
            despachada y recibida (solo para usuarios con privilegios).

    Returns:
        Bytes del PDF generado.
    """
    vistas = list(vistas)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        leftMargin=35, rightMargin=35, topMargin=25, bottomMargin=25,
    )
    elements = []

    # ---- Estilos ----
    st_titulo = ParagraphStyle(
        "t", fontSize=16, textColor=_AZUL_OSCURO,
        spaceAfter=2, alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    st_sub = ParagraphStyle(
        "s", fontSize=9, textColor=colors.grey,
        spaceAfter=2, alignment=TA_CENTER,
    )
    st_label = ParagraphStyle(
        "lbl", fontSize=9, textColor=colors.grey,
        fontName="Helvetica-Bold", leading=13,
    )
    st_valor = ParagraphStyle(
        "val", fontSize=9, leading=13,
    )
    st_th = ParagraphStyle(
        "th", fontSize=8, fontName="Helvetica-Bold",
        textColor=colors.white, alignment=TA_CENTER,
    )
    st_td = ParagraphStyle("td", fontSize=8, leading=10)
    st_td_c = ParagraphStyle("tdc", fontSize=8, leading=10, alignment=TA_CENTER)

    # ---- Encabezado ----
    estado_label = _LABEL_ESTADO.get(pedido.estado, pedido.estado)
    condicion_label = _LABEL_CONDICION.get(pedido.condicion, pedido.condicion) if pedido.condicion else "-"

    sufijo_vista = ", ".join(
        label for label in (_VISTA_LABEL.get(v, "") for v in vistas) if label
    )
    titulo_pedido = f"Pedido de Almacen  #{pedido.numero_pedido}"
    if sufijo_vista:
        titulo_pedido += f"  —  {sufijo_vista}"
    elements.append(Paragraph(titulo_pedido, st_titulo))
    elements.append(Paragraph(
        f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        st_sub,
    ))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1, color=_AZUL_OSCURO))
    elements.append(Spacer(1, 10))

    # ---- Bloque de informacion del pedido (2 columnas) ----
    def _fila(etiqueta: str, valor: str):
        return [Paragraph(etiqueta, st_label), Paragraph(valor or "-", st_valor)]

    solicitante = pedido.solicitante.get_username() or pedido.solicitante.username
    despachador = (
        (pedido.despachador.get_username() or pedido.despachador.username)
        if pedido.despachador else "-"
    )
    fecha_creacion = pedido.fecha_creacion.strftime("%d/%m/%Y %H:%M") if pedido.fecha_creacion else "-"
    fecha_despacho = pedido.fecha_despacho.strftime("%d/%m/%Y %H:%M") if pedido.fecha_despacho else "-"
    fecha_recepcion = pedido.fecha_recepcion.strftime("%d/%m/%Y %H:%M") if pedido.fecha_recepcion else "-"

    col_izq = [
        _fila("Solicitante:", solicitante),
        _fila("Despachador:", despachador),
        _fila("Categoria:", "Mixto" if pedido.es_mixto else (pedido.categoria or "-")),
        _fila("Deposito origen:", pedido.deposito or "-"),
    ]
    col_der = [
        _fila("Estado:", estado_label),
        _fila("Condicion:", condicion_label),
        _fila("Fecha creacion:", fecha_creacion),
        _fila("Fecha despacho:", fecha_despacho),
    ]

    ancho_campo = 75
    ancho_valor = 170

    tabla_izq = Table(col_izq, colWidths=[ancho_campo, ancho_valor])
    tabla_der = Table(col_der, colWidths=[ancho_campo, ancho_valor])

    for t in (tabla_izq, tabla_der):
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))

    info_general = Table(
        [[tabla_izq, tabla_der]],
        colWidths=[255, 255],
    )
    info_general.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(info_general)

    if pedido.observaciones:
        elements.append(Spacer(1, 6))
        obs_tabla = Table(
            [[Paragraph("Observaciones:", st_label), Paragraph(pedido.observaciones, st_valor)]],
            colWidths=[ancho_campo, ancho_valor * 2 + 10],
        )
        obs_tabla.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
        elements.append(obs_tabla)

    elements.append(Spacer(1, 12))

    # ---- Encabezado de la tabla de items ----
    sec_items = Table(
        [[Paragraph("Items del Pedido", ParagraphStyle(
            "si", fontSize=10, textColor=colors.white,
            fontName="Helvetica-Bold", leftPadding=6,
        ))]],
        colWidths=[542],
    )
    sec_items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _AZUL_OSCURO),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(sec_items)

    # ---- Tabla de items ----
    # Ancho util = 542 pt (612 - margenes 35*2)
    # Sin cantidades: 55+175+75+60+60+47+70 = 542
    # Con cantidades: 50+148+68+55+55+42+40+44+40 = 542
    # Union de columnas de cantidad de las vistas seleccionadas, deduplicada
    # y en el orden canonico Despachado -> Back Order -> Recibido.
    cantidad_cols = []
    _attrs_vistos = set()
    for v in vistas:
        for encabezado, attr in _VISTA_CANTIDADES.get(v, []):
            if attr not in _attrs_vistos:
                cantidad_cols.append((encabezado, attr))
                _attrs_vistos.add(attr)

    es_filtrada = bool(cantidad_cols)
    # Con 2+ vistas combinadas se agrega la columna "Estado" para distinguir
    # filas; con una sola vista filtrada el PDF queda igual que antes.
    es_multi = es_filtrada and len(vistas) >= 2

    if es_filtrada:
        cabeceras = [
            Paragraph("Codigo", st_th),
            Paragraph("Descripcion", st_th),
            Paragraph("Referencia", st_th),
            Paragraph("Puesto", st_th),
            Paragraph("Ref. Prov.", st_th),
            Paragraph("Solicitado", st_th),
        ]
        for encabezado, _attr in cantidad_cols:
            cabeceras.append(Paragraph(encabezado, st_th))
        if es_multi:
            cabeceras.append(Paragraph("Estado", st_th))
        cabeceras.append(Paragraph("Observacion", st_th))
        widths_por_vista = _MULTI_VISTA_WIDTHS if es_multi else _VISTA_WIDTHS
        col_widths = widths_por_vista[len(cantidad_cols)]
    elif mostrar_cantidades:
        cabeceras = [
            Paragraph("Codigo", st_th),
            Paragraph("Descripcion", st_th),
            Paragraph("Referencia", st_th),
            Paragraph("Puesto", st_th),
            Paragraph("Ref. Prov.", st_th),
            Paragraph("Solicitado", st_th),
            Paragraph("Despachado", st_th),
            Paragraph("Recibido", st_th),
            Paragraph("Observacion", st_th),
        ]
        col_widths = [50, 148, 68, 55, 55, 42, 40, 44, 40]
    else:
        cabeceras = [
            Paragraph("Codigo", st_th),
            Paragraph("Descripcion", st_th),
            Paragraph("Referencia", st_th),
            Paragraph("Puesto", st_th),
            Paragraph("Ref. Prov.", st_th),
            Paragraph("Solicitado", st_th),
            Paragraph("Observacion", st_th),
        ]
        col_widths = [55, 175, 75, 60, 60, 47, 70]

    data = [cabeceras]

    for item in items:
        fila = [
            Paragraph(item.codigo, st_td),
            Paragraph(item.descripcion, st_td),
            Paragraph(item.referencia or "-", st_td),
            Paragraph(item.puesto or "-", st_td),
            Paragraph(item.ref_proveedor or "-", st_td),
            Paragraph(str(item.cantidad_solicitada), st_td_c),
        ]
        if es_filtrada:
            for _encabezado, attr in cantidad_cols:
                fila.append(Paragraph(str(getattr(item, attr)), st_td_c))
            if es_multi:
                fila.append(Paragraph(item.get_estado_display(), st_td_c))
        elif mostrar_cantidades:
            fila += [
                Paragraph(str(item.cantidad_despachada), st_td_c),
                Paragraph(str(item.cantidad_recibida), st_td_c),
            ]
        fila.append(Paragraph(item.observacion or "-", st_td))
        data.append(fila)

    tabla_items = Table(data, colWidths=col_widths, repeatRows=1)

    item_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), _AZUL_CLARO),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GRIS_CLARO]),
        ("ALIGN", (5, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    tabla_items.setStyle(TableStyle(item_styles))
    elements.append(tabla_items)

    # ---- Pie de pagina ----
    elements.append(Spacer(1, 14))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"Pedido #{pedido.numero_pedido}  —  {solicitante}  —  {fecha_creacion}",
        ParagraphStyle("footer", fontSize=7, textColor=colors.grey, alignment=TA_CENTER),
    ))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generar_despacho_pdf(despacho, despacho_items) -> bytes:
    """
    Genera el PDF de un despacho individual con sus items.

    Args:
        despacho: Instancia del modelo Despacho.
        despacho_items: QuerySet de DespachoItem con select_related('pedido_item').

    Returns:
        Bytes del PDF generado.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        leftMargin=35, rightMargin=35, topMargin=25, bottomMargin=25,
    )
    elements = []

    st_titulo = ParagraphStyle(
        "t", fontSize=16, textColor=_AZUL_OSCURO,
        spaceAfter=2, alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    st_sub = ParagraphStyle(
        "s", fontSize=9, textColor=colors.grey,
        spaceAfter=2, alignment=TA_CENTER,
    )
    st_label = ParagraphStyle(
        "lbl", fontSize=9, textColor=colors.grey,
        fontName="Helvetica-Bold", leading=13,
    )
    st_valor = ParagraphStyle("val", fontSize=9, leading=13)
    st_th = ParagraphStyle(
        "th", fontSize=8, fontName="Helvetica-Bold",
        textColor=colors.white, alignment=TA_CENTER,
    )
    st_td = ParagraphStyle("td", fontSize=8, leading=10)
    st_td_c = ParagraphStyle("tdc", fontSize=8, leading=10, alignment=TA_CENTER)

    pedido = despacho.pedido

    elements.append(Paragraph(f"Despacho #{despacho.numero_despacho}", st_titulo))
    elements.append(Paragraph(f"Pedido de Almacen #{pedido.numero_pedido}", st_sub))
    elements.append(Paragraph(
        f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        st_sub,
    ))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1, color=_AZUL_OSCURO))
    elements.append(Spacer(1, 10))

    _LABEL_ESTADO_DESPACHO = {
        "PREPARANDO": "Preparando",
        "ENVIADO": "Enviado",
        "RECIBIDO": "Recibido",
        "PARCIAL": "Parcial",
    }

    def _fila(etiqueta, valor):
        return [Paragraph(etiqueta, st_label), Paragraph(valor or "-", st_valor)]

    despachador = despacho.despachador.get_username() if despacho.despachador else "-"
    pickeador = despacho.picker.get_username() if despacho.picker else "-"
    receptor = despacho.receptor.get_username() if despacho.receptor else "-"
    fecha_despacho = despacho.fecha_despacho.strftime("%d/%m/%Y %H:%M") if despacho.fecha_despacho else "-"
    fecha_recepcion = despacho.fecha_recepcion.strftime("%d/%m/%Y %H:%M") if despacho.fecha_recepcion else "-"
    estado_label = _LABEL_ESTADO_DESPACHO.get(despacho.estado, despacho.estado)

    col_izq = [
        _fila("Solicitante:", pedido.solicitante.get_username()),
        _fila("Despachador:", despachador),
        _fila("Pickeador:", pickeador),
        _fila("Deposito origen:", pedido.deposito or "-"),
    ]
    col_der = [
        _fila("Estado:", estado_label),
        _fila("Fecha despacho:", fecha_despacho),
        _fila("Fecha recepcion:", fecha_recepcion),
    ]

    ancho_campo = 80
    ancho_valor = 175

    tabla_izq = Table(col_izq, colWidths=[ancho_campo, ancho_valor])
    tabla_der = Table(col_der, colWidths=[ancho_campo, ancho_valor])
    for t in (tabla_izq, tabla_der):
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))

    info = Table([[tabla_izq, tabla_der]], colWidths=[255, 255])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(info)
    elements.append(Spacer(1, 12))

    sec = Table(
        [[Paragraph("Items del Despacho", ParagraphStyle(
            "si", fontSize=10, textColor=colors.white,
            fontName="Helvetica-Bold", leftPadding=6,
        ))]],
        colWidths=[542],
    )
    sec.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _AZUL_OSCURO),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(sec)

    # Codigo 55 | Descripcion 210 | Despachado 60 | Recibido 60 | Observacion 157 = 542
    cabeceras = [
        Paragraph("Codigo", st_th),
        Paragraph("Descripcion", st_th),
        Paragraph("Despachado", st_th),
        Paragraph("Recibido", st_th),
        Paragraph("Observacion", st_th),
    ]
    col_widths = [55, 210, 60, 60, 157]
    data = [cabeceras]

    for di in despacho_items:
        item = di.pedido_item
        recibido = str(di.cantidad_recibida) if di.cantidad_recibida else "-"
        data.append([
            Paragraph(item.codigo, st_td),
            Paragraph(item.descripcion, st_td),
            Paragraph(str(di.cantidad_despachada), st_td_c),
            Paragraph(recibido, st_td_c),
            Paragraph(di.observacion or "-", st_td),
        ])

    tabla = Table(data, colWidths=col_widths, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _AZUL_CLARO),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GRIS_CLARO]),
        ("ALIGN", (2, 0), (3, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(tabla)

    elements.append(Spacer(1, 14))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"Despacho #{despacho.numero_despacho}  —  Pedido #{pedido.numero_pedido}  —  {fecha_despacho}",
        ParagraphStyle("footer", fontSize=7, textColor=colors.grey, alignment=TA_CENTER),
    ))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generar_reporte_items_pdf(grupos: list, filtros: dict) -> bytes:
    """
    Genera el PDF del reporte de items agrupado por codigo (solo cabecera,
    sin el detalle por pedido).

    Args:
        grupos: Lista de dicts con las mismas claves usadas en pantalla
            (codigo, descripcion, referencia, ref_proveedor, pedidos_ids,
            num_pedidos, detalle, estados_badges, total_solicitada,
            total_preparada, total_despachada, total_recibida,
            total_back_order, existencia).
        filtros: Dict con codigos_filtro, categoria_filtro, estado_filtro,
            fecha_inicio, fecha_fin, sin_filtros_aplicados.

    Returns:
        Bytes del PDF generado.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        leftMargin=35, rightMargin=35, topMargin=25, bottomMargin=25,
    )
    elements = []

    st_titulo = ParagraphStyle("t", fontSize=16, textColor=_AZUL_OSCURO,
                                spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica-Bold")
    st_sub = ParagraphStyle("s", fontSize=9, textColor=colors.grey,
                             spaceAfter=2, alignment=TA_CENTER)

    elements.append(Paragraph("Reporte de Items por Estado", st_titulo))

    filtros_texto = []
    if filtros.get("codigos_filtro"):
        filtros_texto.append(f"Codigos: {filtros['codigos_filtro']}")
    if filtros.get("categoria_filtro"):
        filtros_texto.append(f"Categoria: {filtros['categoria_filtro']}")
    if filtros.get("estado_filtro"):
        filtros_texto.append(f"Estado: {filtros['estado_filtro']}")
    if filtros.get("fecha_inicio"):
        filtros_texto.append(f"Desde: {filtros['fecha_inicio']}")
    if filtros.get("fecha_fin"):
        filtros_texto.append(f"Hasta: {filtros['fecha_fin']}")
    if filtros.get("sin_filtros_aplicados"):
        filtros_texto.append("Solo items con back order pendiente (default)")
    if filtros_texto:
        elements.append(Paragraph(" | ".join(filtros_texto), st_sub))
    elements.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}", st_sub))
    elements.append(Spacer(1, 14))

    elements.append(_seccion_header("Items", 542))

    st_cell = ParagraphStyle("ic", fontSize=8, leading=10)
    st_head = ParagraphStyle("ih", fontSize=8, leading=10, fontName="Helvetica-Bold")
    data = [[
        Paragraph("Codigo", st_head), Paragraph("Descripcion", st_head),
        Paragraph("Referencia", st_head), Paragraph("Ref. Proveedor", st_head),
        Paragraph("Pedido(s)", st_head), Paragraph("Estado", st_head),
        Paragraph("Solicit.", st_head), Paragraph("Preparada", st_head),
        Paragraph("Despach.", st_head), Paragraph("Recibida", st_head),
        Paragraph("Back Order", st_head), Paragraph("Existencia", st_head),
    ]]
    for grupo in grupos:
        pedido_col = ", ".join(f"#{pid}" for pid in grupo["pedidos_ids"])
        estado_col = ", ".join(label for _codigo, label in grupo["estados_badges"])
        existencia_col = "N/D" if grupo["existencia"] is None else str(grupo["existencia"])
        data.append([
            Paragraph(grupo["codigo"], st_cell),
            Paragraph(grupo["descripcion"], st_cell),
            Paragraph(grupo["referencia"], st_cell),
            Paragraph(grupo["ref_proveedor"], st_cell),
            Paragraph(pedido_col, st_cell),
            Paragraph(estado_col, st_cell),
            str(grupo["total_solicitada"]), str(grupo["total_preparada"]),
            str(grupo["total_despachada"]), str(grupo["total_recibida"]),
            str(grupo["total_back_order"]), existencia_col,
        ])
    if not grupos:
        data.append([Paragraph("Sin datos", st_cell), "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"])

    # Ancho util = 542 pt (612 - margenes 35*2)
    # Codigo 42 | Descripcion 95 | Referencia 45 | Ref.Proveedor 45 | Pedido(s) 48 | Estado 65 |
    # Solicit 30 | Preparada 33 | Despach 33 | Recibida 30 | BackOrder 36 | Existencia 40 = 542
    col_widths = [42, 95, 45, 45, 48, 65, 30, 33, 33, 30, 36, 40]
    tabla = Table(data, colWidths=col_widths, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _GRIS_CLARO),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GRIS_CLARO]),
        ("ALIGN", (4, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(tabla)

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
