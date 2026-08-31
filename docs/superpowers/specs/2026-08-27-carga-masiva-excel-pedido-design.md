# Creación masiva de pedidos vía plantilla Excel

## Contexto

`PedidosAlmacen` ya tiene dos formas de poblar el carrito de un pedido antes de totalizarlo: búsqueda manual de productos, y carga de documentos a2 (presupuestos, pedidos, notas de entrega). Se agrega una tercera: subir un Excel con SKU + Cantidad (y opcionalmente Categoría, solo informativa) para crear pedidos de forma masiva — mismo patrón conceptual que la carga de listas de ofertas en la app `tasks`, pero mucho más simple porque **la validación de stock/comprometido ya existe** en `crear_pedido` y se reutiliza sin cambios: el Excel solo resuelve qué ítems entran al carrito, no valida disponibilidad.

## Alcance

- Aplica solo a `PedidosAlmacen`, dentro de `pedidos-crear.html` / `crear_pedido`.
- Columnas de la plantilla: `SKU` (obligatoria), `Cantidad` (obligatoria), `Categoria` (opcional, puramente informativa para quien llena el archivo — el backend nunca la lee).
- No incluye validación de stock/comprometido en el paso de carga — eso ya ocurre al totalizar, sin cambios.
- No incluye tabla temporal en DBISAM ni resaltado del Excel original (a diferencia del patrón de `tasks/`) — la resolución es una sola consulta `SINVENTARIO WHERE FI_CODIGO IN (...)`.
- Límite de 500 filas por archivo (protege el tamaño del `IN (...)` contra DBISAM).

## Esquema a2 relevante

Igual que la carga de documentos a2, la resolución de producto por código usa `SINVENTARIO`:
`FI_CODIGO`, `FI_DESCRIPCION`, `FI_REFERENCIA`, `FI_PUESTO`, `ZZCAMPO_001` (ref. proveedor), `FI_CATEGORIA` (código de categoría, resuelto a nombre vía `SCATEGORIA` con el mismo mecanismo que ya usa `obtener_categorias()`).

## Backend — `PedidosAlmacen/dbisam.py`

**`resolver_productos(codigos: list[str]) -> dict[str, dict]`**

```sql
SELECT FI_CODIGO, FI_DESCRIPCION, FI_REFERENCIA, FI_PUESTO, ZZCAMPO_001, FI_CATEGORIA
FROM SINVENTARIO
WHERE FI_CODIGO IN (<codigos>)
```

- `codigos` se escapan/sanean igual que el resto de `dbisam.py` (sin placeholders `?`).
- Devuelve un dict indexado por código (`{'SKU1': {'descripcion': ..., 'referencia': ..., 'puesto': ..., 'ref_proveedor': ..., 'categoria': ...}, ...}`) para lookup O(1) por fila del Excel.
- Códigos no encontrados simplemente no aparecen en el dict — el caller (la vista) es responsable de detectar los ausentes y reportarlos como omitidos.
- Lista vacía de códigos → `{}` sin consultar DBISAM (mismo patrón de corte que el resto de los métodos de esta clase).

## Backend — endpoints (`PedidosAlmacen/views.py`)

**`GET /pedidos/plantilla-excel/`**
- Genera un `.xlsx` al vuelo con `openpyxl` (encabezados `SKU`, `Cantidad`, `Categoria (opcional)` en la fila 1).
- `Content-Disposition: attachment; filename="plantilla_pedido.xlsx"`.
- Mismos decoradores de permiso que el resto del flujo (`login_required` + `user_passes_test(is_pedidos_tienda, ...)`).

**`POST /pedidos/cargar-items-excel/`**
- Recibe el archivo en `request.FILES['archivo']` (sin `forms.py` de por medio, consistente con el resto de este flujo).
- Valida extensión (`.xlsx`/`.xls`); si no es válida, responde `{"error": "..."}` con 400.
- Lee con `pandas.read_excel(archivo, header=0, dtype={'SKU': str})` — la fila de encabezado es siempre la 0 porque la plantilla la generamos nosotros (a diferencia de `tasks/`, no hace falta un selector de fila de encabezado).
- Si el archivo excede 500 filas de datos, responde `{"error": "El archivo supera el máximo de 500 filas"}` con 400, sin procesar nada.
- Por cada fila (número de fila = índice + 2, contando la fila de encabezado):
  - `SKU` vacío/no-string → se omite, `motivo: "SKU vacío"`.
  - `Cantidad` no numérica o ≤ 0 → se omite, `motivo: "Cantidad inválida"`.
  - SKU no encontrado en el resultado de `resolver_productos` → se omite, `motivo: "SKU no encontrado en a2"`.
  - SKU repetido dentro del archivo (ya resuelto y válido) → se suma la cantidad a la línea ya acumulada, no se omite ni se reporta como error.
- La columna `Categoria` del Excel se lee y se descarta — nunca se usa para nada.
- Respuesta JSON:
  ```json
  {
    "items": [{"codigo","descripcion","referencia","puesto","ref_proveedor","cantidad","categoria","categoria_nombre"}],
    "categorias_distintas": ["COD1", "COD2"],
    "omitidos": [{"fila": 5, "sku": "XYZ", "motivo": "SKU no encontrado en a2"}]
  }
  ```
  Mismo shape de `items`/`categorias_distintas` que ya devuelve `cargar_items_documentos_a2`, más `omitidos`.
- Errores de conexión DBISAM: capturados, logueados con `logger.error`, respuesta `{"error": "No se pudo consultar a2. Intenta de nuevo en unos segundos."}` con 502 — mismo copy que el resto del flujo a2.

## Frontend — `templates/pedidos-crear.html`

- Botón "Cargar desde Excel" junto a "Cargar de a2", mismo criterio: **no está gateado por el candado** de categoría/condición/depósito.
- Overlay propio (mismo patrón visual `overlay-*` que el de a2): botón "Descargar plantilla" (enlace directo a `/pedidos/plantilla-excel/`), input de archivo, botón "Cargar archivo".
- La lógica de merge al carrito (`mezclarItemsA2`) se generaliza a una función compartida (ej. `mezclarItemsAlCarrito(items)`) que ambos overlays (a2 y Excel) invocan — recalcula categorías desde el carrito completo y marca "Pedido mixto" si aplica, igual que hoy.
- Si la respuesta trae `omitidos` no vacío, se muestra un resumen dentro del overlay antes de cerrarlo (ej. "3 SKU no encontrados: XYZ (fila 5), ABC (fila 8)..."), sin bloquear la carga de los ítems válidos — estos ya se mezclaron al carrito.
- Errores de conexión o archivo inválido: mismo copy y mismo patrón (mensaje en el overlay, sin cerrarlo, no se toca el carrito).

## Validación al totalizar

Sin cambios. `crear_pedido` ya valida stock/categoría/condición/depósito para cualquier ítem en `items_json`, sin importar el origen (manual, a2, o ahora Excel).

## Manejo de errores

- Extensión de archivo inválida, más de 500 filas, o fallo de conexión DBISAM: error claro, no se toca el carrito.
- Filas individuales inválidas (SKU vacío, cantidad inválida, SKU no encontrado): se omiten y se reportan por fila, el resto del archivo se procesa igual.
- SKU duplicado dentro del archivo: se suma, no se reporta como error.

## Testing

- **`resolver_productos`**: SQL con `IN (...)`, códigos no encontrados ausentes del dict devuelto, lista vacía → sin query.
- **Endpoint de carga**: extensión inválida → 400; fila con SKU vacío/cantidad inválida → omitida y reportada; SKU no encontrado → omitido y reportado; SKU duplicado → cantidades sumadas; más de 500 filas → 400 sin procesar; error DBISAM → 502 + log.
- **Endpoint de plantilla**: headers correctos en el `.xlsx` generado.
- **Manual en navegador**: mismo límite que la carga a2 — sin navegador real disponible en esta sesión, queda para verificación humana antes de dar por cerrada la feature.

## Decisiones explícitas (para no reabrir en implementación)

| Decisión | Elegido |
|---|---|
| Columnas de la plantilla | SKU (oblig.), Cantidad (oblig.), Categoria (opcional, solo informativa, nunca leída por el backend) |
| Filas con SKU/cantidad inválidos | Se omiten y se reportan; el resto del archivo se carga igual |
| SKU duplicado dentro del archivo | Se suman las cantidades en una sola línea |
| Origen de la plantilla | Se genera al vuelo con openpyxl (`GET /pedidos/plantilla-excel/`), no es un archivo estático |
| Ubicación del botón/pantalla | Overlay propio junto al de "Cargar de a2", candado de categoría ignorado igual |
| Librería de lectura | `pandas.read_excel`, consistente con `tasks/utils.py` |
| Validación de stock/comprometido | Ninguna en este paso — se reutiliza la que ya corre en `crear_pedido` al totalizar |
| Límite de filas | 500 por archivo |
