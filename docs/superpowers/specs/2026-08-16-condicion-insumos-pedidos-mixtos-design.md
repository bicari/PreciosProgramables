# Condición "Insumos" y pedidos mixtos — Diseño

**Fecha:** 2026-08-16
**App:** PedidosAlmacen

## Problema

Hoy `Pedido.condicion` (`models.py:18-22`) solo admite `URGENTE`, `SURTIDO`,
`CLIENTE_RETIRA`. No existe una condición para pedidos internos de insumos de
uso de oficina (los productos sí existen en el catálogo del ERP a2, bajo su
propia categoría).

Además, `Pedido.categoria` (código de línea de producto del ERP a2) es un
valor único de cabecera que se bloquea en la UI apenas se agrega el primer
producto (`templates/pedidos-crear.html:407-420`). Esto impide crear un
pedido que combine productos de más de una categoría en una sola solicitud.

Son dos features independientes: una nueva condición, y la posibilidad de
mezclar categorías dentro de un mismo pedido.

## Feature 1: Condición "Insumos"

### Cambio de modelo

`Pedido.CONDICION_CHOICES` (`models.py:18-22`) agrega:

```python
('INSUMOS', 'Insumos'),
```

Una migración `AlterField` sobre `condicion`, siguiendo el patrón de
`migrations/0021_add_estado_anulado.py` (que agregó un choice a
`ESTADO_CHOICES`).

### Cascada de cambios

- **`pdf.py:26-30`** (`_LABEL_CONDICION`): agregar `"INSUMOS": "Insumos"`.
- **`templates/pedidos-lista.html:94-99`** y **`pedidos-detalle.html:144-146`**:
  nueva rama `elif` para `INSUMOS` con badge de color `secondary`.
- **`api_views.py:138-146`** (`api_preparar_pedido`, límite de 1 pedido en
  Picking por picker): `INSUMOS` **no** se agrega a la tupla de excepción
  `('URGENTE', 'CLIENTE_RETIRA')`. Queda sujeto al límite normal, igual que
  `SURTIDO`.
- **Creación de pedido** (`views.py:245-350`, `templates/pedidos-crear.html`)
  y **filtros de reporte** (`views.py:1559-1753`): ambos ya pueblan sus
  `<select>` dinámicamente desde `Pedido.CONDICION_CHOICES`, así que el nuevo
  valor aparece sin tocar esas vistas.
- Serializers (`serializers.py:25-28, 91`): sin cambios, ya exponen
  `condicion` como campo genérico.

### Tests

- Crear pedido con `condicion='INSUMOS'`.
- Límite de Picking: un picker con un pedido `INSUMOS` en `PICKING` no puede
  iniciar Picking de un segundo pedido `INSUMOS`/`SURTIDO` (igual que hoy con
  `SURTIDO`), pero sí puede si el segundo es `URGENTE`/`CLIENTE_RETIRA`.
- Label en PDF y badge en lista/detalle para `INSUMOS`.

## Feature 2: Pedidos mixtos (múltiples categorías por pedido)

### Modelo de datos

Una migración con:

- `Pedido.es_mixto` — `BooleanField(default=False)`.
- `PedidoItem.categoria` — `CharField(max_length=70, blank=True, default='')`.
- `PedidoItem.categoria_nombre` — `CharField(max_length=150, blank=True, default='')`.

Migración de datos (mismo archivo o uno siguiente): para todo `PedidoItem`
existente, copiar `categoria`/`categoria_nombre` desde su `Pedido` padre.
Así los pedidos ya creados (todos no-mixtos) quedan consistentes sin
necesidad de tocar `es_mixto`.

### UX (`templates/pedidos-crear.html`)

- Checkbox "Pedido mixto (varias categorías)" junto al selector de
  categoría existente.
- **Marcado**: el selector de categoría (`selector-categoria`,
  `pedidos-crear.html:343-420`) no se deshabilita tras agregar el primer
  ítem. Cada vez que se agrega un producto, se captura la categoría
  seleccionada en ese momento y se guarda en `categoria`/`categoria_nombre`
  del `PedidoItem` recién creado.
- **Sin marcar (default)**: comportamiento actual sin cambios — categoría y
  condición se bloquean tras el primer ítem, como hoy.
- En ambos casos (marcado o no), `condicion` sigue bloqueándose tras el
  primer ítem: "pedido mixto" solo libera el selector de `categoria`. Un
  pedido conserva una única condición aunque combine varias categorías.
- `Pedido.categoria`/`categoria_nombre` de cabecera se siguen llenando con
  la categoría del primer ítem agregado (compatibilidad con código que lea
  el campo de cabecera), pero dejan de ser la fuente de verdad para mostrar
  en UI cuando `es_mixto=True`.

### Badges y reportes

- `templates/pedidos-lista.html:88-99` y `pedidos-detalle.html:137-146`: si
  `pedido.es_mixto`, mostrar badge "Mixto" en vez del nombre de categoría de
  cabecera.
- Reportes `views.py:1559-1672` y `1679-1753`: la agregación "por categoría"
  pasa a sumar desde `PedidoItem.categoria` en vez de `Pedido.categoria`.
  Esto es correcto tanto para pedidos normales (donde todos los ítems
  comparten la categoría de cabecera) como para mixtos, y deja una sola
  fuente de verdad para el conteo.
- Traslados al ERP a2 (`dbisam.py:184, 316, 459, 471, 492, 506, 514`) no se
  ven afectados: `FTI_PROPOSITO` se arma solo a partir de `condicion`
  (`views.py:858, 1362, 1477`), nunca de `categoria`.

### Interacción con "Insumos"

`es_mixto` y `condicion` son campos independientes en `Pedido`: un pedido
puede ser `condicion='INSUMOS'` y `es_mixto=True` simultáneamente sin
conflicto alguno.

### Tests

- Crear pedido con `es_mixto=True` y agregar ítems de 2+ categorías
  distintas; verificar que cada `PedidoItem` guarda su propia
  `categoria`/`categoria_nombre`.
- Verificar que un pedido no-mixto (`es_mixto=False`) conserva el
  comportamiento actual: selector de categoría bloqueado tras el primer
  ítem (regresión).
- Reportes: agregación "por categoría" cuenta correctamente los ítems de un
  pedido mixto en sus categorías respectivas, no todos bajo la categoría de
  cabecera.
- Migración de datos: `PedidoItem`s preexistentes quedan con
  `categoria`/`categoria_nombre` igual a los de su `Pedido` padre tras
  aplicar la migración.
