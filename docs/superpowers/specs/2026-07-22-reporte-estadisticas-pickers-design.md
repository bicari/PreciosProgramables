# Reporte de estadísticas por picker

**Fecha:** 2026-07-22

## Problema

No existía forma de medir estadísticas de los pickers (unidades pickeadas,
despachos y pedidos involucrados). Se pedía determinar si esos datos eran
recuperables para un informe sin crear una tabla de estadísticas.

## Hallazgo clave

`Despacho.picker` es un snapshot inmutable capturado al crear cada despacho
(`picker = pedido.picker or request.user`) que nunca se sobreescribe y
sobrevive a anulaciones. Como un pedido reasignado genera varios despachos,
la tabla `Despacho` funciona de facto como historial picker↔trabajo. No se
necesita tabla nueva.

Lo NO reconstruible con datos históricos:

- Tiempos de picking: las transiciones ASIGNADO→PICKING→EN_PREPARACION no
  dejaban timestamp en BD.
- Pickers reasignados antes de generar despacho alguno.
- Quién pickeó cada línea individual.

## Decisiones (acordadas con el usuario)

1. Informe web + export PDF sobre `Despacho`/`DespachoItem` (no `Pedido.picker`).
2. Solo cuentan despachos cuyo picker pertenece al grupo **Pedidos Picker**
   (excluye auto-atribuciones de despachadores que despacharon sin picker).
3. Selector de filtro: solo miembros vigentes del grupo (`_pickers_disponibles`).
4. Despachos ANULADOS: columna aparte, excluidos de las métricas netas.
5. Preparar el futuro sin tabla nueva: columnas `fecha_inicio_picking` /
   `fecha_fin_picking` en `Pedido` (estado vivo del ciclo) y snapshot de ambas
   en `Despacho` al crearlo (mismo patrón que `picker`).

## Implementación

- **Migración 0026**: 4 columnas `DateTimeField(null=True)` (2 en Pedido, 2 en Despacho).
- **Transiciones**: `preparar_pedido` (web) y `api_preparar_pedido` (`iniciar`/
  `finalizar`) setean inicio/fin; el fin solo se estampa desde PICKING para no
  pisarse en re-guardados. `desasignar_picker` limpia ambos.
- **Snapshot**: `despachar_pedido` y `api_crear_despacho` copian ambos campos
  al `Despacho`. Bug corregido: la API no seteaba `Despacho.fecha_despacho`.
- **Helper `_estadisticas_pickers`** (views.py): agrega por picker con
  `fecha_ref = Coalesce(fecha_despacho, pedido.fecha_despacho, pedido.fecha_creacion)`
  como fallback para despachos legacy con fecha null. Métricas: despachos,
  pedidos distintos, unidades, líneas, productos distintos, anulados.
- **Vistas**: `reporte_pickers` (`/pedidos/reporte/pickers/`) y
  `exportar_reporte_pickers_pdf` (`.../pdf/`), acceso Pedidos Supervisor.
- **Template** `pedidos-reporte-pickers.html`: patrón visual de
  `pedidos-reporte.html` (header, filtros, banda KPI, tabla con totales).
- **PDF** `generar_reporte_pickers_pdf` en `PedidosAlmacen/pdf.py`.

## Notas de semántica

- Un pedido atendido por varios pickers cuenta para cada uno; el KPI de
  pedidos totales se calcula aparte y no duplica.
- Líneas SKU_NO_CONTEMPLADO (sin `pedido_item`) cuentan en líneas/unidades
  pero no en productos distintos.
- Al filtrar por grupo vigente, el histórico de ex-pickers removidos del
  grupo deja de mostrarse (aceptado).
- Métricas futuras de duración de picking deben leerse del snapshot en
  `Despacho`, no de los campos vivos de `Pedido`.
