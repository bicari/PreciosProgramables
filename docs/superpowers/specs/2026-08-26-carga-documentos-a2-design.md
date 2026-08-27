# Carga de documentos a2 (presupuestos, pedidos, notas de entrega) en Pedidos de Almacén

## Contexto

Hoy, al crear un pedido de almacén (`PedidosAlmacen/views.py:crear_pedido`, template `templates/pedidos-crear.html`), el único mecanismo para agregar ítems es la búsqueda manual de productos individuales contra `SINVENTARIO`/`SINVDEP` (`buscar_producto`, `PedidosDBISAM.buscar_en_categoria`). No existe forma de partir de un documento ya existente en a2 (presupuesto, pedido de venta, o nota de entrega de venta) y traer sus líneas de una sola vez.

Se agrega la opción de buscar documentos de venta en a2 por número de documento o por nombre de cliente, seleccionar varios documentos (de tipos distintos y con productos de categorías distintas) y cargar sus ítems al carrito del pedido en curso, sin alterar el flujo de validación/totalización existente.

## Alcance

- Aplica solo a `PedidosAlmacen`, dentro del flujo de creación de pedido (`pedidos-crear.html` / `crear_pedido`).
- Tipos de documento soportados: Presupuesto (`FTI_TIPO=9`), Pedido (`FTI_TIPO=10`), Nota de Entrega en Ventas (`FTI_TIPO=13`).
- No incluye edición/anulación de documentos en a2 — es solo lectura.
- No incluye trazabilidad del documento de origen en `PedidoItem` (decisión explícita: los ítems cargados se comportan igual que los agregados manualmente, sin marca de origen).
- No modifica la lógica de validación de stock/categoría/condición al totalizar — reutiliza exactamente la que ya existe.

## Esquema a2 relevante

**Cabecera — `SOPERACIONINV`:**
- `FTI_AUTOINCREMENT` — PK, usado para el join con la tabla de detalle.
- `FTI_TIPO` — tipo de operación (9/10/13 para este feature).
- `FTI_STATUS` — estado del documento a nivel de cabecera.
- `FTI_DOCUMENTO` — número de documento.
- `FTI_FECHAEMISION` — fecha de emisión.
- `FTI_PERSONACONTACTO` — nombre del cliente.
- `FTI_RESPONSABLE` — código del cliente (no se usa como filtro en este feature; la búsqueda por cliente es por nombre).

**Detalle — `SDETALLEVENTA`** (misma estructura que `SDETALLECOMPRA`):
- `FDI_OPERACION_AUTOINCREMENT` — FK a `SOPERACIONINV.FTI_AUTOINCREMENT`.
- `FDI_CODIGO` — código de producto (join con `SINVENTARIO.FI_CODIGO`).
- `FDI_CANTIDAD` — cantidad de la línea (se usa este campo, no `FDI_CANTIDADPENDIENTE`, ver decisión de cantidad más abajo).
- `FDI_STATUS` — estado de la línea.

**Filtro de estado "abierto/pendiente" (aplica igual a los 3 tipos de documento):**
- Cabecera: `FTI_STATUS IN (1, 4)` (1=Procesado, 4=Tránsito).
- Línea: `FDI_STATUS IN (1, 4)`, mismos valores, para excluir renglones ya anulados/facturados dentro de un documento cuya cabecera sí califica.

**Categoría de producto:** se resuelve por `SINVENTARIO` (mismo mecanismo que ya usa `PedidosDBISAM.buscar_en_categoria`, `PedidosAlmacen/dbisam.py:531-566`), no vive en el documento de a2.

## Backend

### `PedidosAlmacen/dbisam.py` — nuevos métodos en `PedidosDBISAM`

**`buscar_documentos_venta(tipos: list[int], documento: str | None, cliente: str | None, limit: int = 50) -> list[dict]`**

Consulta solo cabeceras, liviana, para poblar la lista de resultados:

```sql
SELECT FTI_AUTOINCREMENT, FTI_TIPO, FTI_DOCUMENTO, FTI_FECHAEMISION, FTI_PERSONACONTACTO
FROM SOPERACIONINV
WHERE FTI_TIPO IN (<tipos>)
  AND FTI_STATUS IN (1, 4)
  AND (FTI_DOCUMENTO LIKE '%<documento>%' OR FTI_PERSONACONTACTO LIKE '%<cliente>%')
ORDER BY FTI_FECHAEMISION DESC
```

- Al menos uno de `documento`/`cliente` debe venir no vacío (si ambos vienen, se combinan con `OR`, igual que el filtro implícito de la UI: el usuario busca "por documento o por cliente").
- Al menos un `tipo` debe venir seleccionado; si no, la vista responde sin ejecutar query (ver sección Endpoints).
- `limit` aplicado con `SELECT TOP <limit>` (o equivalente DBISAM) para acotar resultados.
- Sanitización de `documento`/`cliente` sigue el patrón existente de `notas_entrega/sanitize.py` (sin placeholders `?`, f-strings con escape/sanitize upstream — DBISAM no soporta parámetros).

**`obtener_items_documentos(operacion_ids: list[int]) -> list[dict]`**

Trae las líneas de los documentos ya seleccionados por el usuario, revalidando tipo y estado (no confía en los IDs recibidos del cliente):

```sql
SELECT
    FDI_CODIGO,
    FDI_CANTIDAD,
    FI_DESCRIPCION,
    FI_PUESTO,
    FI_REFERENCIA,
    ZZCAMPO_001,
    FI_CATEGORIA,
    FTI_AUTOINCREMENT
FROM SOPERACIONINV
INNER JOIN SDETALLEVENTA ON FTI_AUTOINCREMENT = FDI_OPERACION_AUTOINCREMENT
INNER JOIN SINVENTARIO ON FDI_CODIGO = FI_CODIGO
WHERE FTI_AUTOINCREMENT IN (<operacion_ids>)
  AND FTI_TIPO IN (9, 10, 13)
  AND FTI_STATUS IN (1, 4)
  AND FDI_STATUS IN (1, 4)
```

- La resolución de nombre de categoría (`FI_CATEGORIA` → nombre legible) usa el mismo mecanismo que ya usa `buscar_en_categoria`.
- `FI_CATEGORIA` viaja en el resultado — necesario para que la vista pueda decidir si el conjunto cargado es mixto.

### Endpoints y URLs (`PedidosAlmacen/views.py`, `urls.py`)

**`GET /pedidos/buscar-documentos-a2/`** (htmx)
- Query params: `tipos` (uno o más de `9`,`10`,`13`), `documento`, `cliente`.
- Si no viene ningún `tipo` seleccionado, o ambos `documento`/`cliente` están vacíos, responde el fragmento de "aviso" pidiendo completar el filtro (sin pegarle a DBISAM).
- Llama `PedidosDBISAM().buscar_documentos_venta(...)`.
- Renderiza `templates/pedidos-buscar-documentos-a2.html`: tabla con checkbox por fila, tipo (badge + ícono), número, fecha, cliente.
- Errores de conexión DBISAM: captura `pyodbc.Error`, log con `logger.error`, renderiza fragmento de error con el copy definido en la sección de diseño visual.

**`POST /pedidos/cargar-items-a2/`**
- Body: `operacion_ids` (lista de `FTI_AUTOINCREMENT` marcados).
- Si viene vacío, responde 400.
- Llama `PedidosDBISAM().obtener_items_documentos(operacion_ids)`.
- Agrega (suma `FDI_CANTIDAD`) líneas con el mismo `FDI_CODIGO` que vengan de documentos distintos.
- Responde JSON:
  ```json
  {
    "items": [
      {"codigo": "...", "descripcion": "...", "referencia": "...", "puesto": "...",
       "ref_proveedor": "...", "cantidad": 0, "categoria": "...", "categoria_nombre": "..."}
    ],
    "categorias_distintas": ["COD1", "COD2"]
  }
  ```
- Errores de conexión DBISAM: JSON `{"error": "..."}` con status 502, mismo copy de error que la búsqueda.

Ambas rutas requieren el mismo login/permiso que ya exige `crear_pedido` hoy (sin restricción de rol nueva).

## Frontend — `templates/pedidos-crear.html`

### Integración en el carrito existente

- Botón "Cargar de a2" junto al bloque de búsqueda manual, **sin candado de categoría** (visible y usable aunque no se haya seleccionado categoría/condición/depósito aún — a diferencia de la búsqueda manual de productos).
- Abre un overlay propio (mismo patrón que `overlay-confirmar`/`overlay-carga`: `position:fixed; inset:0; background:rgba(0,0,0,.55)`, tarjeta blanca `border-radius:16px`, centrada, ancho ≈720px), no el componente `.modal` de Bootstrap.
- Cierra con botón "Cancelar", con clic fuera de la tarjeta, o con tecla `Escape` (los overlays existentes no tienen `Escape`; se agrega aquí y puede extenderse a los otros como mejora futura, fuera de alcance).

### Contenido del overlay

1. **Selector de tipo:** 3 chips tipo checkbox (Presupuesto `fa-file-invoice-dollar`, Pedido `fa-file-invoice`, Nota de Entrega `fa-truck`), al menos uno debe quedar marcado para poder buscar.
2. **Campos de búsqueda:** input "N° de documento" e input "Cliente", ambos opcionales pero se exige al menos uno no vacío (validación cliente-side antes de disparar htmx, mismo `delay:500ms` que la búsqueda de productos).
3. **Resultados:** tabla con checkbox de fila, columna tipo (badge de color distinto por tipo + ícono), número de documento, fecha, cliente. Usa el patrón `skeleton-busqueda`/`texto-buscando` ya existente mientras carga.
4. **Estado vacío:** "No se encontraron documentos abiertos con esos datos. Prueba con otro número o nombre de cliente."
5. **Estado de error:** "No se pudo consultar a2. Intenta de nuevo en unos segundos."
6. **Footer:** botón "Cargar seleccionados (N)" (deshabilitado si N=0) + botón "Cancelar".

### Al confirmar "Cargar seleccionados"

JS hace `fetch POST` a `/pedidos/cargar-items-a2/` con los `operacion_ids` marcados:

1. Por cada ítem devuelto, se aplica la misma lógica de merge que ya usa `agregarItem()`: si el código ya existe en `itemsPedido`, suma cantidad; si no, lo agrega. Se reutiliza `renderItems()` tal cual.
2. Si `categorias_distintas.length > 1`:
   - Marca `checkbox-mixto` como `checked` y dispara `sincronizarMixto()`.
   - No fija ninguna categoría única en `campo-categoria` (queda como pedido mixto; cada `PedidoItem` lleva su propia categoría, igual que hoy soporta el modelo).
3. Si `categorias_distintas.length === 1` y el pedido no era ya mixto:
   - Fija `selector-categoria`/`campo-categoria`/`campo-categoria-nombre` con esa categoría (mismo efecto que `seleccionarCategoria()`).
4. Llama `bloquearCategoria()` (ya se invoca dentro de `renderItems()`), cerrando el candado de categoría igual que cuando se agrega el primer producto manual.
5. Cierra el overlay. Las filas nuevas en la tabla de ítems reciben `.row-flash` (mismo efecto que al agregar un producto manual) — no hay toast ni marca de origen adicional.

### Condición y depósito

No se tocan por este feature: siguen siendo seleccionados por el usuario en el formulario principal, igual que hoy, independientemente de si los ítems vienen de búsqueda manual o de documentos a2.

## Validación al totalizar

Sin cambios. `crear_pedido` (`views.py:261-394`) ya valida stock real (`consultar_stock_multiple` + `calcular_disponibilidad`), categoría/condición/depósito obligatorios, y persiste `categoria`/`categoria_nombre` por línea en cada `PedidoItem` — todo a partir de `items_json`, sin importar si el ítem se originó en búsqueda manual o en carga desde a2.

## Manejo de errores

- Fallos de conexión/consulta a DBISAM en ambos endpoints nuevos: capturados con `try/except pyodbc.Error`, logueados con `logger.error`, respuesta con copy de error definido arriba — nunca rompen el resto del formulario de creación de pedido.
- `obtener_items_documentos` revalida `FTI_TIPO IN (9,10,13)` y ambos filtros de estado, para no confiar ciegamente en `operacion_ids` que lleguen manipulados desde el cliente.
- Si `operacion_ids` no corresponde a ningún documento válido tras la revalidación (ej. el documento cambió de estado entre la búsqueda y la carga), la respuesta trae `items: []` y el frontend muestra el mismo copy de estado vacío dentro del overlay antes de cerrarlo, sin intentar agregar nada al carrito.

## Testing

- **Unitarios `PedidosDBISAM`:** mock del cursor pyodbc; verifican cláusulas `WHERE` generadas (tipos `IN`, estado, `LIKE` por documento/cliente), y que `obtener_items_documentos` incluye siempre el filtro de tipo+estado sin importar los `operacion_ids` recibidos.
- **Vistas:** mock de `PedidosDBISAM`; verifican:
  - `buscar_documentos_a2` sin `tipos` o sin `documento`/`cliente` no llama a DBISAM.
  - Estructura del fragmento/JSON de respuesta.
  - Agregación de cantidades cuando dos documentos traen el mismo código.
  - `categorias_distintas` calculado correctamente (mixto vs. no mixto).
  - Manejo de error de conexión DBISAM (respuesta de error, no excepción sin capturar).
- **Manual en navegador:** flujo completo del overlay (abrir, buscar, seleccionar múltiples documentos de tipos distintos, cargar, verificar mixto automático, cerrar, totalizar) — el proyecto no tiene test runner de JS.

## Decisiones explícitas (para no reabrir en implementación)

| Decisión | Elegido |
|---|---|
| Estados a2 a mostrar | Solo "abiertos": `FTI_STATUS`/`FDI_STATUS` IN (1,4), igual para los 3 tipos |
| Alcance de búsqueda | Usuario elige tipo(s) primero (checkboxes), luego busca |
| Cantidad cargada por línea | Cantidad total original del documento (`FDI_CANTIDAD`), no la pendiente |
| Duplicados entre documentos | Se suman en una sola línea del carrito |
| Ubicación del botón/pantalla | Modal/overlay dentro de `pedidos-crear.html`, sin recarga |
| Candado de categoría | El overlay de a2 lo ignora; mixto se marca automáticamente si aplica |
| Trazabilidad de origen | Ninguna — los ítems se ven y comportan igual que los manuales |
| Estrategia de consulta | Dos fases: cabeceras en la búsqueda, ítems solo al confirmar selección |
| Permisos | Los mismos que ya exige `crear_pedido` hoy |
