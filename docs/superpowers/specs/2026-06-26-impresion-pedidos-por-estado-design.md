# Impresión de pedidos por estado de items

**Fecha:** 2026-06-26
**App:** PedidosAlmacen
**Estado:** Diseño aprobado

## Problema

El detalle de un pedido tiene un único botón "Descargar PDF" que genera el PDF
con **todos** los items del pedido (`exportar_pedido_pdf` →
`generar_pedido_pdf`), sin importar el estado actual de cada item.

Operativamente se necesita poder imprimir el pedido filtrado por el estado de
los items: solo lo despachado, solo el back order, solo lo recibido, etc. Cada
variante debe destacar la cantidad relevante a ese estado.

## Objetivo

Permitir elegir, al imprimir un pedido, una de varias **variantes** que filtran
los items por su estado y muestran la cantidad correspondiente. Mantener el
comportamiento actual ("TODOS") intacto.

## Alcance

Solo afecta la impresión del **pedido** (`generar_pedido_pdf` /
`exportar_pedido_pdf` / `pedidos-detalle.html`). No toca el PDF de despacho ni
el reporte de pedidos.

## Variantes y filtrado

El filtrado es **por estado exacto** del campo `PedidoItem.estado`.

| Variante     | Filtro (`PedidoItem.estado`)      | Columnas de cantidad destacadas      |
|--------------|-----------------------------------|--------------------------------------|
| TODOS        | sin filtro (todos los items)      | Solicitado (+ Despachado/Recibido según rol) |
| DESPACHADO   | `== 'DESPACHADO'`                 | Solicitado · Despachado              |
| BACK ORDER   | `== 'BACK_ORDER'`                 | Solicitado · Back Order              |
| RECIBIDO     | `== 'RECIBIDO'`                   | Solicitado · Recibido                |
| PARCIAL      | `== 'PARCIAL'`                    | Solicitado · Despachado · Back Order |

Notas:
- Un item PARCIAL (se despachó parte y quedó back order) **no** aparece en
  DESPACHADO ni en BACK ORDER; solo en su variante propia PARCIAL y en TODOS.
- "TODOS" conserva exactamente el comportamiento actual, incluida la lógica de
  `mostrar_cantidades` por rol.

## Permisos

| Rol                  | Variantes disponibles                          |
|----------------------|------------------------------------------------|
| Almacén / Supervisor | TODOS, DESPACHADO, BACK ORDER, RECIBIDO, PARCIAL |
| Tienda               | TODOS, RECIBIDO, BACK ORDER                     |

- La validación es **en servidor**: si un usuario de Tienda solicita
  `?vista=despachado` o `?vista=parcial`, la vista lo rechaza (redirige al
  detalle con mensaje de error). El modal solo oculta opciones por usabilidad,
  no es el control de seguridad.
- Las variantes filtradas muestran su cantidad relevante a todos los roles que
  tengan permiso a esa variante (p. ej. Tienda ve la columna Recibido en la
  variante RECIBIDO aunque hoy el PDF "TODOS" se la oculte).

## UX — Modal en `pedidos-detalle.html`

- El botón actual "Descargar PDF" pasa a abrir un modal **"Imprimir pedido"**.
- El modal lista las variantes permitidas según el rol del usuario.
- Cada variante muestra el **conteo de items** de ese estado, p. ej.
  "Back Order (3)". TODOS muestra el total de items del pedido.
- Las variantes con **0 items** se muestran deshabilitadas.
- Al elegir una variante, se navega a `pedidos-pdf?vista=<x>` (descarga el PDF).
- La vista que renderiza el detalle calcula los conteos por estado y los pasa
  al contexto del template.

## Backend

### `exportar_pedido_pdf(request, pk)`
- Lee `vista` desde `request.GET` (default `'todos'`).
- Valida que `vista` sea una de las permitidas; si no, usa `'todos'`.
- Valida permiso por rol; si el rol no puede usar esa variante, redirige al
  detalle con `messages.error`.
- Filtra `items` por el estado correspondiente (TODOS = sin filtro).
- Llama `generar_pedido_pdf(pedido, items, vista=vista, mostrar_cantidades=...)`.
- Nombre de archivo refleja la variante: `pedido_<n>_<vista>.pdf`
  (TODOS conserva `pedido_<n>.pdf`).

### `generar_pedido_pdf(pedido, items, vista='todos', mostrar_cantidades=False)`
- Nuevo parámetro `vista`.
- Determina cabeceras de tabla, anchos de columna y qué campo de cantidad
  renderiza por fila, según la tabla de variantes.
- El título/encabezado del PDF refleja la variante
  (p. ej. "Pedido de Almacen #42 — Back Order"). TODOS conserva el título actual.
- Para `vista='todos'` el comportamiento es idéntico al actual (incluida la
  ramificación por `mostrar_cantidades`).

## Casos borde

- **Variante sin items:** el endpoint genera un PDF válido con la tabla vacía
  (solo cabeceras). El modal igualmente deshabilita la opción, pero el endpoint
  no asume que siempre haya filas.
- **`vista` inválida en la URL:** se trata como `'todos'`.
- **Tienda forzando variante no permitida:** redirección con mensaje de error.

## Pruebas

- Filtrado: cada variante incluye solo los items con el estado esperado; PARCIAL
  no aparece en DESPACHADO ni BACK ORDER.
- Columnas: la variante renderiza la(s) cantidad(es) correcta(s).
- Permisos: un usuario de Tienda no puede generar DESPACHADO ni PARCIAL
  (redirección/error); sí puede TODOS, RECIBIDO y BACK ORDER.
- Variante vacía: el endpoint responde 200 con PDF válido.
- Conteos: la vista de detalle expone los conteos por estado al contexto.

## Fuera de alcance

- PDF de despacho y reporte de pedidos.
- Filtros combinados o por rango (solo una variante por impresión).
- Exportar varias variantes en un mismo PDF.
