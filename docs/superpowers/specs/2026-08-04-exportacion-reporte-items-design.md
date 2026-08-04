# Exportación CSV/PDF del Reporte de Items — Diseño

## Problema

El Reporte de Items por Estado (`/pedidos/reporte/items/`) solo se puede consultar en pantalla. Los supervisores necesitan poder descargar el listado agrupado (sin el detalle expandible por pedido) en CSV y PDF, respetando los filtros que tengan aplicados en ese momento — incluyendo el filtro por defecto de `cantidad_back_order > 0` cuando no hay ningún filtro explícito.

## Alcance

- Dos nuevos endpoints de exportación (CSV y PDF) para el reporte de items existente.
- Exportan únicamente la fila agrupada por código (cabecera), **sin** el detalle por pedido individual.
- Mismos filtros, mismos permisos (`Pedidos Supervisor`), mismos datos de existencia que la pantalla.
- Fuera de alcance: exportar el detalle por pedido, exportar en otros formatos (Excel nativo, JSON), programar envíos automáticos.

## Decisiones

1. **Columnas exportadas** = mismas que la tabla en pantalla, sin la columna "Detalle": Código, Descripción, Pedido(s), Estado, Solicit., Preparada, Despach., Recibida, Back Order, Existencia.
   - "Pedido(s)": si `num_pedidos == 1` → el número de pedido; si no → `"{n} pedidos"` (texto plano, sin link).
   - "Estado": labels de `estados_badges` unidos por coma (ej. `"Pendiente, Parcial"`).
   - "Existencia": entero, o `"N/D"` si falló la consulta a DBISAM (mismo fallback que pantalla).

2. **Los exports respetan los filtros aplicados en pantalla** vía querystring (código(s), categoría, estado, fechas), incluyendo el default de `cantidad_back_order__gt=0` cuando no hay ningún filtro. Para que este default no se rompa, el link de exportar arma su querystring omitiendo parámetros vacíos — así, en la carga por defecto (sin filtros), el link de exportar tampoco lleva querystring y `sin_filtros_aplicados` sigue evaluando `True` en la vista de exportación.

3. **Refactor de soporte**: se extrae la lógica de filtrado/agregación de `reporte_items` a una función compartida `_construir_grupos_reporte_items(request)` en `views.py`, reutilizada por las tres vistas (pantalla, CSV, PDF). Evita triplicar la lógica de filtros (5 filtros + 1 regla de default) y garantiza que pantalla y exportación vean siempre los mismos datos. `reporte_items` pasa a ser un wrapper delgado sobre el helper. El comportamiento observable de `reporte_items` no cambia (mismos tests existentes deben seguir pasando sin modificación).

4. **Formato CSV**: `csv.writer` sobre `io.StringIO`, delimitador coma, encoding `utf-8-sig` (BOM) para que Excel en español muestre bien los acentos. `content_type='text/csv'`. Nombre de archivo: `reporte_items_YYYYMMDD_HHMM.csv`.

5. **Formato PDF**: nueva función `generar_reporte_items_pdf(grupos, filtros)` en `PedidosAlmacen/pdf.py`, siguiendo el estilo de `generar_reporte_pickers_pdf` — solo tabla (sin tarjetas de KPIs), con título "Reporte de Items por Estado", línea de filtros aplicados + fecha de generación, tabla con `repeatRows=1`, fila "Sin datos" si no hay grupos. `content_type='application/pdf'`. Nombre de archivo: `reporte_items_YYYYMMDD_HHMM.pdf`.

6. **Permisos**: mismo gate que el reporte (`login_required` + `user_passes_test(is_pedidos_supervisor)`).

## Diseño de datos

```python
def _construir_grupos_reporte_items(request):
    """
    Query y agregación compartidos por pantalla, export CSV y export PDF.
    Devuelve (grupos, filtros) donde filtros incluye codigos_filtro,
    categoria_filtro, estado_filtro, fecha_inicio, fecha_fin,
    sin_filtros_aplicados, categorias_disponibles, estados_item.
    """
    # ... misma lógica de filtrado, agregación (Sum/Count/Coalesce),
    # detalle_por_codigo, estados_badges, existencia_por_codigo
    # que la implementación actual de reporte_items.
    return grupos, filtros
```

`reporte_items`, `exportar_reporte_items_csv` y `exportar_reporte_items_pdf` llaman a esta función con el mismo `request`, por lo que ven exactamente el mismo `request.GET`.

### URLs

```python
path('pedidos/reporte/items/csv/', views.exportar_reporte_items_csv, name='pedidos-reporte-items-csv'),
path('pedidos/reporte/items/pdf/', views.exportar_reporte_items_pdf, name='pedidos-reporte-items-pdf'),
```

### Construcción del querystring de exportación

`reporte_items` calcula un `querystring_filtros` (string ya armado con `urlencode` sobre un dict que excluye claves con valor vacío) y lo agrega al contexto. El template arma el href como:

```html
<a href="{% url 'pedidos-reporte-items-csv' %}{% if querystring_filtros %}?{{ querystring_filtros }}{% endif %}" ...>
```

Esto evita lógica condicional compleja anidada en el template y garantiza que un valor vacío nunca termine en el querystring.

## UI

En `pd-header-actions` de `templates/pedidos-reporte-items.html`, junto al botón "Volver a Pedidos", se agregan dos botones:

- `Exportar CSV` — `btn-outline-success`, ícono `fa-file-csv`.
- `Exportar PDF` — `btn-danger`, ícono `fa-file-pdf` (mismo estilo que "Exportar PDF" en `pedidos-reporte.html`).

## Testing

Se agrega una clase `ExportarReporteItemsTest` (o se extiende `ReporteItemsTest`) en `PedidosAlmacen/tests.py`:

- Permisos: usuario no-supervisor redirige en ambas vistas de export.
- CSV: headers correctos, una fila por código agrupado, respeta cada filtro (código, categoría, estado, fechas) y el default de back order sin filtros, existencia `N/D` si DBISAM falla.
- PDF: `content_type` correcto (`application/pdf`), no lanza excepción con 0/1/N grupos, respeta los mismos filtros que CSV.
- Regresión: los tests existentes de `ReporteItemsTest` sobre `reporte_items` deben seguir pasando sin modificación tras el refactor a `_construir_grupos_reporte_items`.

## Notas técnicas

- No se agregan nuevas dependencias: `csv` es de la librería estándar, `reportlab` ya está en uso (`PedidosAlmacen/pdf.py`).
- El export no muestra mensajes de Django (`messages` framework) si falla DBISAM — a diferencia de la pantalla, la respuesta es una descarga de archivo directa; el fallback a "N/D" en la columna Existencia es la única señal para el usuario, igual que en el patrón existente de `exportar_reporte_pdf`.
