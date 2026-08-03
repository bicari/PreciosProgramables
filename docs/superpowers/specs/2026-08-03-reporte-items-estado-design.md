# Reporte de items por estado (agrupado por código)

**Fecha:** 2026-08-03

## Problema

No existe forma de consultar, para uno o varios códigos de producto (o una
categoría entera), qué pedidos pendientes/en curso los contienen, en qué
estado están y si hay existencia en almacén para resolverlos. Los reportes
actuales (`reporte_pedidos`, `reporte_pickers`, `reporte_incidencias`) miran
el pedido como unidad; ninguno mira el producto como unidad.

## Alcance

Tablero de consulta de "foto actual" (sin rango de fechas): items de pedido
(`PedidoItem`) filtrables por código(s), categoría y estado, agrupados por
código con cantidades agregadas y existencia de almacén en vivo.

## Decisiones (acordadas con el usuario)

1. **Unidad de fila = código de producto**, no línea de pedido. Cuando un
   código tiene líneas en varios pedidos, la fila principal muestra las
   cantidades **ya agregadas** (`Sum` de solicitada/preparada/despachada/
   recibida/back_order sobre todas las líneas que matchean el filtro).
2. **Detalle expandible por pedido**: si el código tiene más de un pedido
   coincidente, aparece un botón "Detalle" que expande/colapsa las líneas
   individuales (una por pedido) debajo de la fila agrupada. Códigos con un
   solo pedido no muestran el botón (nada que expandir).
3. **Filtros**: código(s) — texto, uno o varios separados por coma
   (`codigo__in=[...]`); categoría — select dinámico desde
   `Pedido.categoria`/`categoria_nombre` (mismo patrón que `reporte_pedidos`);
   estado del item — select con `PedidoItem.ESTADO_ITEM_CHOICES`.
4. **Sin filtro de fechas.** Por defecto se excluyen pedidos `ANULADO` (mismo
   criterio que `reporte_pedidos`).
5. **Existencia de almacén**: una sola llamada a
   `PedidosDBISAM.consultar_stock_multiple(codigos)` por carga de página,
   sobre el conjunto de códigos visibles, sumando existencia total entre
   depósitos (sin filtrar por depósito). Si falla (DBISAM caído), la columna
   muestra "N/D" fila por fila; el resto del reporte (datos de Postgres) sigue
   siendo usable.
6. **Sin export PDF.** Solo pantalla, tabla interactiva DataTables.
7. **Permisos**: restringido a grupo `Pedidos Supervisor`, igual que los
   demás reportes de `PedidosAlmacen`.

## Diseño de datos

Query base (excluye `ANULADO`, aplica filtros de categoría/estado/código):

```python
pedidos = Pedido.objects.exclude(estado='ANULADO')
items = PedidoItem.objects.filter(pedido__in=pedidos)
# + filtros de codigo/categoria/estado sobre items y items.pedido
```

Agregación por código:

```python
grupos = items.values('codigo').annotate(
    descripcion=Max('descripcion'),
    total_solicitada=Sum('cantidad_solicitada'),
    total_preparada=Sum('cantidad_preparada'),
    total_despachada=Sum('cantidad_despachada'),
    total_recibida=Sum('cantidad_recibida'),
    total_back_order=Sum('cantidad_back_order'),
    num_pedidos=Count('pedido', distinct=True),
).order_by('codigo')
```

Detalle por pedido (para las filas hijas, cargado junto con los grupos de la
página actual): `items.filter(codigo__in=codigos_pagina).select_related('pedido').order_by('codigo', 'pedido_id')`.

Existencia: `consultar_stock_multiple([g['codigo'] for g in grupos])` → dict
`{codigo: existencia}`, una sola vez por carga.

## UI

- Extiende `dashboard.html`, mismo sistema visual que el resto de reportes:
  `pd-header` (header oscuro), `pr-filter-card` (filtros), `pl-table-card` +
  `pl-tabla` (tabla).
- Columnas: Código | Descripción | Pedido | Estado | Solicitada | Preparada |
  Despachada | Recibida | Back Order | Existencia | Detalle.
- Fila de grupo: negrita, badge(s) de estado (uno por cada estado distinto
  presente entre sus pedidos si son mixtos), botón "Detalle" con caret.
- Fila hija: indentada, sin repetir código/descripción/existencia, con link
  al pedido (`pedidos-detalle`).
- Master/detail implementado con la funcionalidad nativa de **child rows de
  DataTables** (`row().child()`), ya incluida en la librería vendorizada
  (`static/vendor/datatables/`) — no se agrega ninguna extensión nueva
  (RowGroup no hace falta).
- Sin paginación en el servidor: la vista renderiza todos los grupos que
  matchean el filtro (mismo patrón que `despachos-lista.html`) y DataTables
  pagina/busca del lado del cliente sobre las filas de grupo.

## Testing

En `PedidosAlmacen/tests.py`, junto a los tests de los demás reportes:

- Filtro por código único y por múltiples códigos.
- Filtro por categoría y por estado, y combinaciones.
- Exclusión de pedidos `ANULADO` por defecto.
- Agregación correcta cuando un código tiene líneas en 2+ pedidos (suma de
  cantidades, `num_pedidos` correcto).
- Fallback a "N/D" cuando `consultar_stock_multiple` lanza `pyodbc.DatabaseError`
  (mockeado — no depende de DBISAM real).
- Permisos: acceso solo para `Pedidos Supervisor`.

## Notas técnicas

- No se agrega ninguna dependencia nueva (ni RowGroup de DataTables ni
  librerías de agregación); la agregación ocurre en la query de Django.
- La consulta de existencia sigue el mismo patrón ya usado por
  `PedidosDBISAM.consultar_stock_multiple` (suma entre depósitos); si en el
  futuro se necesita existencia por depósito específico, el método ya acepta
  el parámetro `deposito`.
