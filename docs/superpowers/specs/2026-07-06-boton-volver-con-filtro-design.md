# Botón "volver" del detalle de pedido con memoria de origen y filtro

**Fecha:** 2026-07-06
**Estado:** Aprobado

## Problema

El botón "volver" del detalle de un pedido (`pedidos-detalle.html`) apunta fijo a
`{% url 'pedidos-lista' %}`. Esto produce dos pérdidas:

1. Si el usuario estaba en la lista de pedidos con un filtro de estado aplicado
   (`/pedidos/?estado=PENDIENTE`), al volver pierde el filtro.
2. Si el usuario llegó al detalle desde la lista de despachos
   (`/despachos/?estado=ENVIADO`), al volver es enviado a la lista de pedidos en
   lugar de regresar a despachos con su filtro.

## Comportamiento acordado

El botón "volver" regresa **al origen con su filtro**: la última lista visitada
(pedidos o despachos) con el querystring que tuviera en ese momento.

## Restricción de diseño

Las acciones POST del detalle (confirmar despacho, asignar/liberar picker,
recibir, anular, reintentar traslado…) **no se modifican**. La solución debe
sobrevivir a cualquier cantidad de ciclos POST → redirect → detalle sin
perder el destino de retorno.

## Solución: memoria en sesión

Enfoque elegido entre tres alternativas (parámetro `?next=` propagado por
enlaces y formularios; `history.back()`), descartadas por requerir cambios en
~10 formularios o por acumular entradas de historial tras acciones POST.

### Mecánica (3 puntos de cambio)

1. **Vistas de lista** (`PedidosAlmacen/views.py`): al final de `lista_pedidos`
   y `lista_despachos`, antes del `render`:

   ```python
   request.session['pedidos_volver_url'] = request.get_full_path()
   ```

2. **Vista de detalle** (`detalle_pedido`): pasa al contexto:

   ```python
   'volver_url': request.session.get('pedidos_volver_url') or reverse('pedidos-lista')
   ```

3. **Template** (`pedidos-detalle.html`, botón `pd-back`): cambiar
   `href="{% url 'pedidos-lista' %}"` por `href="{{ volver_url }}"`.

### Comportamiento resultante

- Pedidos filtrado → detalle → N acciones POST → volver → Pedidos con el mismo
  filtro (los POST no escriben la clave de sesión; solo las listas).
- Despachos filtrado → ver pedido → volver → Despachos con el mismo filtro.
- Entrada directa al detalle por URL sin sesión previa → fallback a la lista de
  pedidos sin filtro (comportamiento actual).

### Seguridad

El valor de sesión lo escribe siempre el servidor desde
`request.get_full_path()` de vistas propias; nunca proviene de input del
cliente. No hay riesgo de open redirect.

### Casos límite aceptados

- Dos pestañas con filtros distintos: el botón usa la última lista visitada.
- La búsqueda de texto y la página de DataTables no se restauran; solo el
  filtro de chips (que viaja en la URL).

## Tests

En `PedidosAlmacen/tests.py`:

1. Visitar `/pedidos/?estado=PENDIENTE` (y `/despachos/?estado=ENVIADO`) guarda
   la URL completa en `session['pedidos_volver_url']`.
2. El detalle renderiza el botón volver con la URL guardada en sesión.
3. Sin clave en sesión, el detalle usa el fallback `{% url 'pedidos-lista' %}`.
