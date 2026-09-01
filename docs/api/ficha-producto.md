# Ficha de producto — `GET /api/productos/<codigo>/ficha/`

Documento de integración para el equipo de app móvil. Endpoint bajo demanda
(botón "ver"/ojito al escanear un item): entrega la ficha completa del
producto, su existencia en el almacén principal, y en qué otros pedidos
del sistema está pendiente, parcial o en backorder.

> No confundir con `GET /api/productos/<codigo>/` (búsqueda rápida usada en
> cada escaneo, sin estos datos extra). Ver [Endpoint relacionado](#endpoint-relacionado)
> más abajo. Este endpoint (`/ficha/`) se llama **solo** cuando el usuario
> pide ver el detalle — no en cada escaneo — porque hace más consultas
> (existencia en a2 + búsqueda de pedidos relacionados).

## Autenticación

Requiere token (ver `docs de integración general de la API` / esquema de
conexión ya compartido con el equipo):

```
Authorization: Token <token>
```

Sin token válido → `401`.

## Request

```
GET /api/productos/<codigo>/ficha/
```

| Parte | Valor |
|---|---|
| Método | `GET` |
| Path param | `codigo` — el valor escaneado/tipeado, tal cual (string) |
| Header requerido | `X-Campo: sku \| codBarra \| refProveedor` — indica contra qué campo de a2 buscar `codigo` |
| Header requerido | `Authorization: Token <token>` |

`X-Campo` determina la columna de búsqueda en a2 (SINVENTARIO):

| `X-Campo` | Busca contra |
|---|---|
| `sku` | Código interno del producto |
| `codBarra` | Código de barras / referencia |
| `refProveedor` | Referencia del proveedor |

## Response — 200 OK

```json
{
  "codigo": "ABC123",
  "descripcion": "Cerámica 30x30 Blanca",
  "referencia": "7501234567890",
  "puesto": "A-14",
  "ref_proveedor": "PROV-998",
  "ubicaciones_internas": [
    {
      "codigo": "G1-A1-C1-N4",
      "tipo_nivel": "PICKING",
      "tipo_nivel_display": "Picking"
    }
  ],
  "existencia_almacen": 42,
  "pedidos_pendientes": [
    {
      "numero_pedido": 20,
      "deposito": "CENTRO CERAMICO",
      "estado_pedido": "ASIGNADO",
      "condicion": "URGENTE",
      "cantidad_solicitada": 5,
      "fecha_creacion": "2026-08-01T10:00:00"
    }
  ],
  "pedidos_parciales": [
    {
      "numero_pedido": 18,
      "deposito": "ALMACEN NORTE",
      "estado_pedido": "PARCIAL",
      "condicion": "SURTIDO",
      "cantidad_solicitada": 10,
      "cantidad_despachada": 6,
      "cantidad_back_order": 4,
      "fecha_creacion": "2026-07-28T09:15:00"
    }
  ],
  "pedidos_backorder": [
    {
      "numero_pedido": 15,
      "deposito": "TIENDA SUR",
      "estado_pedido": "PARCIAL",
      "condicion": "SURTIDO",
      "cantidad_solicitada": 8,
      "cantidad_back_order": 3,
      "fecha_creacion": "2026-07-20T14:30:00"
    }
  ]
}
```

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `codigo` | string | Código del producto en a2 (`FI_CODIGO`) |
| `descripcion` | string | Descripción del producto |
| `referencia` | string | Código de barras |
| `puesto` | string | Ubicación física declarada en a2 |
| `ref_proveedor` | string | Referencia del proveedor |
| `ubicaciones_internas` | array | Ubicaciones del sistema de racks propio (puede venir vacío `[]` si el producto no está asignado a ninguna) |
| `ubicaciones_internas[].codigo` | string | Código completo del nivel (galpón-rack-cuerpo-nivel) |
| `ubicaciones_internas[].tipo_nivel` | string | Valor interno del tipo de nivel |
| `ubicaciones_internas[].tipo_nivel_display` | string | Texto legible del tipo de nivel |
| `existencia_almacen` | integer | Existencia actual **solo del almacén principal** (depósito 1), sumada desde a2. No incluye stock de otros depósitos/tiendas. |
| `pedidos_pendientes` | array | Pedidos donde este código todavía no se preparó nada (item en estado `PENDIENTE`) |
| `pedidos_parciales` | array | Pedidos donde el item se despachó parcialmente (item en estado `PARCIAL`) — incluye `cantidad_despachada` y `cantidad_back_order` |
| `pedidos_backorder` | array | Pedidos con este código en backorder puro (item en estado `BACK_ORDER`) — incluye `cantidad_back_order` |
| `*.numero_pedido` | integer | Número de pedido (ID) |
| `*.deposito` | string | Depósito/tienda del pedido |
| `*.estado_pedido` | string | Estado del pedido (`ASIGNADO`, `PICKING`, `EN_PREPARACION`, `PARCIAL`, etc.) |
| `*.condicion` | string | `URGENTE` \| `SURTIDO` \| `CLIENTE_RETIRA` (puede venir `""` si no se asignó) |
| `*.cantidad_solicitada` | integer | Cantidad solicitada del item en ese pedido |
| `*.cantidad_despachada` | integer | Solo en `pedidos_parciales` |
| `*.cantidad_back_order` | integer | En `pedidos_parciales` y `pedidos_backorder` |
| `*.fecha_creacion` | string (ISO 8601) | Fecha de creación del pedido |

### Alcance y reglas importantes

- **`existencia_almacen`** es solo del almacén principal (depósito 1). No hay
  desglose por depósito en este endpoint.
- **Pedidos relacionados** buscan en **todos los depósitos del sistema**, no
  solo en el depósito del pedido que se está trabajando — es a propósito,
  para dar visibilidad total de la demanda pendiente de ese producto.
- Los pedidos **ANULADO** o **CERRADO** nunca aparecen, aunque el item
  individual haya quedado técnicamente en `PENDIENTE`/`PARCIAL`/`BACK_ORDER`
  (anular un pedido no reescribe el estado de sus items).
- Si el producto no tiene pedidos relacionados, las tres listas vienen
  vacías (`[]`), no se omiten del JSON.

## Errores

| Código | Cuándo | Body |
|---|---|---|
| `400` | Falta el header `X-Campo` | `{"error": "Header X-Campo requerido"}` |
| `400` | `X-Campo` con valor distinto de `sku`/`codBarra`/`refProveedor` | `{"error": "X-Campo inválido. Use: sku, codBarra, refProveedor"}` |
| `401` | Sin token / token inválido | (estándar DRF) |
| `404` | El código no existe en a2 | `{"error": "Producto no encontrado"}` |
| `502` | a2/DBISAM no responde o falla la consulta | `{"error": "Error consultando DBISAM: <detalle>"}` |

`ubicaciones_internas` es la única parte que **no** puede provocar un error:
si falla su consulta interna, se devuelve `[]` y el resto de la ficha
sigue funcionando normalmente (se loguea el error del lado del servidor).

## Ejemplo (curl)

```bash
curl -X GET "https://<host>/api/productos/ABC123/ficha/" \
  -H "Authorization: Token abc123..." \
  -H "X-Campo: sku"
```

## Endpoint relacionado

`GET /api/productos/<codigo>/` — mismo header `X-Campo`, se usa en **cada**
escaneo (flujo rápido de armar/recibir pedido). Devuelve solo `codigo`,
`descripcion`, `referencia`, `puesto`, `ref_proveedor`,
`ubicaciones_internas` — sin `existencia_almacen` ni pedidos relacionados,
para no penalizar cada escaneo con las consultas extra.

## Referencia de implementación

- Vista: `PedidosAlmacen/api_views.py::api_ficha_producto`
- Ruta: `PedidosAlmacen/api_urls.py` (`name="api-producto-ficha"`)
- Spec de diseño: `docs/superpowers/specs/2026-08-11-ficha-item-escaneo-design.md`
- Plan de implementación: `docs/superpowers/plans/2026-08-11-ficha-item-escaneo.md`
