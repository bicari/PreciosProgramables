# Verificación por Pistoleo en Confirmación de Despacho

**Fecha:** 2026-06-29
**Estado:** Aprobado
**Alcance:** `templates/pedidos-detalle.html` únicamente

---

## Problema

Al confirmar un despacho (`PENDIENTE_APROBACION`), el supervisor ve la tabla de ítems preparados por el picker pero no tiene forma de verificar rápidamente que los artículos físicos en el carrito coinciden con los del sistema. Un artículo que no pertenece al pedido puede colarse sin detección.

## Solución

Agregar un campo de pistoleo (scanner de código de barras) a la tabla de despacho en estado `PENDIENTE_APROBACION`. Al escanear, el sistema busca el código en los ítems de ese despacho y resalta la fila si coincide, o muestra una alerta si no pertenece.

---

## Comportamiento

### Disponibilidad
El widget de pistoleo es visible **solo cuando**:
- El despacho está en estado `PENDIENTE_APROBACION`
- El usuario tiene rol supervisor (`es_supervisor = True`)

### Flujo de escaneo
1. El supervisor coloca el cursor en el campo de pistoleo (o hace clic en él)
2. Pasa la pistola por el código de barras del artículo → el campo recibe el valor
3. Al presionar `Enter` (que la pistola envía automáticamente al final):
   - **Código encontrado:** la fila se resalta en verde, aparece un ícono ✓, el contador se incrementa, el campo se limpia
   - **Código no encontrado:** alerta roja bajo el campo con el mensaje `"[código]" no pertenece a este despacho`, el campo se limpia después de 3 segundos
4. El campo queda vacío y listo para el siguiente scan

### Escaneo duplicado
Si el supervisor escanea un artículo ya verificado, la fila permanece verde sin cambios. El contador no se incrementa. Sin error ni advertencia.

### Estado
El resaltado de filas y el contador son **en memoria del navegador** (no persisten en BD). Si la página se recarga, el estado visual se pierde y el supervisor debe re-escanear.

---

## Motor de búsqueda

Búsqueda **100% en frontend**, contra atributos `data-*` de las filas de la tabla.

### Campos buscados (en orden, coincidencia exacta, case-insensitive)
| Campo buscado | Atributo HTML | Fuente en BD |
|---|---|---|
| COD / SKU | `data-codigo` | `PedidoItem.codigo` (FI_CODIGO) |
| BARRA / REF | `data-referencia` | `PedidoItem.referencia` (FI_REFERENCIA) |
| PROVEEDOR | `data-ref-proveedor` | `PedidoItem.ref_proveedor` (ZZCAMPO_001) |

La búsqueda es exacta (no parcial) porque la pistola siempre dispara el código completo. Una búsqueda de tipo `contains` resaltaría múltiples filas involuntariamente.

### Alcance
Cada despacho tiene su propio campo de pistoleo. La búsqueda opera únicamente sobre las filas del despacho al que pertenece el campo. Si hay múltiples despachos en la página, son independientes entre sí.

---

## Indicador de progreso

Un contador visible sobre el campo: `N / Total verificados`

- `N` = número de ítems únicos que el supervisor ha escaneado exitosamente en este despacho
- `Total` = número total de `DespachoItem` en ese despacho
- Al llegar a `Total / Total`, el contador cambia de color (verde) como indicación de completitud
- El contador no bloquea ni habilita el botón de confirmar — es informativo

---

## Cambios en código

### Archivo modificado
- `templates/pedidos-detalle.html` — único archivo afectado

### Cambios específicos

**1. Atributos `data-*` en cada `<tr>` de la tabla del despacho**

```html
<!-- Antes -->
<tr>

<!-- Después -->
<tr data-di-id="{{ di.id }}"
    data-codigo="{{ di.pedido_item.codigo|lower }}"
    data-referencia="{{ di.pedido_item.referencia|lower }}"
    data-ref-proveedor="{{ di.pedido_item.ref_proveedor|lower }}">
```

**2. Widget de pistoleo** — insertado dentro del bloque `{% if despacho.estado == 'PENDIENTE_APROBACION' and es_supervisor %}`, antes del filtro de texto existente

```
[Label: VERIFICACIÓN DE ARTÍCULOS]   [Contador: N / Total verificados]
[Campo input de pistoleo]             [Botón limpiar ✕]
[Zona de alerta — oculta por defecto]
```

**3. Ícono de verificación en la fila** — `<span class="pd-check-icon d-none">✓</span>` junto al input de cantidad en la columna "A Despachar". Se muestra cuando la fila es marcada como verificada.

**4. CSS** — nuevas clases en el bloque `<style>` del template:
- `.pd-fila-verificada` — fondo `#d1e7dd`, transición suave
- `.pd-check-icon` — ícono verde junto al input
- `.pd-pistoleo-wrap`, `.pd-pistoleo-field`, `.pd-pistoleo-counter`, `.pd-pistoleo-alert`

**5. JS** — función `iniciarPistoleo(tableId, totalItems, alertZoneId, counterId)`:
- Escucha `keydown` en el campo; actúa en `Enter`
- Normaliza el input a minúsculas, sin espacios al inicio/fin
- Itera los `<tr>` del `tableId` buscando coincidencia exacta en `data-codigo`, `data-referencia`, `data-ref-proveedor`
- En coincidencia: agrega clase `pd-fila-verificada`, muestra `.pd-check-icon`, actualiza contador interno, limpia campo
- En no-coincidencia: muestra mensaje de alerta, limpia campo tras 3 segundos con `setTimeout`
- En duplicado: no hace nada (fila ya tiene clase `pd-fila-verificada`)

---

## Lo que NO cambia

- Modelos, vistas, URLs — sin cambios
- Migraciones — no requeridas
- Lógica del formulario de confirmación (`cantidad_{di.id}`) — sin cambios
- El botón "Confirmar Despacho" y su JS — sin cambios
- Funcionalidad de filtro de texto por código/descripción — sin cambios
- Comportamiento en despachos con estado distinto a `PENDIENTE_APROBACION` — sin cambios

---

## Casos borde

| Caso | Comportamiento |
|---|---|
| `PedidoItem.referencia` vacío | El `data-referencia` queda vacío; la búsqueda por barras no coincide pero la búsqueda por código sí |
| `PedidoItem.ref_proveedor` vacío | Igual que arriba — sin impacto en búsqueda por código |
| Código con caracteres especiales o espacios | El filtro `\|lower` en Django normaliza el texto; el JS hace `.trim().toLowerCase()` en el input |
| Despacho sin ítems | El contador muestra `0 / 0`; el campo está activo pero nunca encontrará coincidencia |
| Múltiples despachos `PENDIENTE_APROBACION` en la misma página | Cada despacho tiene su propio widget y contador independiente |
