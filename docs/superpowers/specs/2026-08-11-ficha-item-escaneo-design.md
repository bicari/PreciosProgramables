# Ficha completa de item al escanear (endpoint API)

**Fecha:** 2026-08-11

## Problema

En la app móvil, la sección de escaneo por item (código de barras / SKU / ref.
proveedor) solo devuelve datos básicos del producto vía
`GET /api/productos/<codigo>/` (`api_buscar_producto`): descripción,
referencia, puesto, ref. proveedor y ubicaciones internas. No hay forma de
que el usuario, desde ese mismo flujo, consulte de un vistazo:

- La existencia real del producto en a2 (DBISAM).
- En qué otros pedidos (de cualquier depósito) ese mismo código está
  pendiente, parcial o en backorder.

Se pide agregar esta vista bajo un botón de solo lectura ("ojito") en la app
móvil. La UI vive fuera de este repo (app móvil externa); el alcance de este
trabajo es exclusivamente el backend: un endpoint nuevo que le dé a la app
todos los datos necesarios en una sola respuesta.

## Decisión de diseño: endpoint nuevo, no ampliar el existente

`api_buscar_producto` se llama en cada escaneo dentro del flujo rápido de
armado de pedido (alta frecuencia). Agregarle la consulta de existencia y la
de pedidos relacionados penalizaría ese flujo con queries adicionales a
DBISAM y Postgres en cada pistoleo.

En cambio, se crea `GET /api/productos/<codigo>/ficha/`, que se llama solo
cuando el usuario toca el botón del ojito (bajo demanda, no en cada escaneo).
El endpoint existente queda intacto.

## Contrato del endpoint

```
GET /api/productos/<codigo>/ficha/
Headers: X-Campo: sku | codBarra | refProveedor   (igual que el endpoint existente)
Auth: IsAuthenticated
```

Respuesta 200:

```json
{
  "codigo": "ABC123",
  "descripcion": "...",
  "referencia": "...",
  "puesto": "...",
  "ref_proveedor": "...",
  "ubicaciones_internas": [
    {"codigo": "...", "tipo_nivel": "...", "tipo_nivel_display": "..."}
  ],
  "existencia_almacen": 42,
  "pedidos_pendientes": [
    {
      "numero_pedido": 20, "deposito": "CENTRO CERAMICO",
      "estado_pedido": "ASIGNADO", "condicion": "URGENTE",
      "cantidad_solicitada": 5, "fecha_creacion": "2026-08-01T10:00:00"
    }
  ],
  "pedidos_parciales": [
    {
      "numero_pedido": 18, "deposito": "...", "estado_pedido": "PARCIAL",
      "condicion": "SURTIDO", "cantidad_solicitada": 10,
      "cantidad_despachada": 6, "cantidad_back_order": 4,
      "fecha_creacion": "..."
    }
  ],
  "pedidos_backorder": [
    {
      "numero_pedido": 15, "deposito": "...", "estado_pedido": "PARCIAL",
      "condicion": "...", "cantidad_solicitada": 8,
      "cantidad_back_order": 3, "fecha_creacion": "..."
    }
  ]
}
```

Errores — mismo patrón que `api_buscar_producto`:

- `400` — falta el header `X-Campo` o su valor no es `sku|codBarra|refProveedor`.
- `404` — DBISAM no encuentra el producto.
- `502` — error de conexión/consulta a DBISAM (`pyodbc.DatabaseError`).

## Fuentes de datos y queries

1. **Identificación del producto**: reutiliza
   `PedidosDBISAM().buscar_producto_por_campo(codigo, campo)` (ya usado por
   `api_buscar_producto`). Devuelve `(codigo, descripcion, referencia, puesto,
   ref_proveedor)`.
2. **Ubicaciones internas**: reutiliza el mismo bloque que
   `api_buscar_producto` (`ProductoUbicacion` filtrado por `nivel/ubicacion/
   cuerpo/rack` activos).
3. **Existencia**: `PedidosDBISAM().consultar_stock(codigo, deposito=
   DEPOSITO_ALMACEN)` — existencia solo del almacén principal (depósito 1),
   ya existente en `dbisam.py`. No se desglosa por depósito.
4. **Pedidos relacionados**: query nueva a Postgres —

   ```python
   PedidoItem.objects.filter(
       codigo=codigo_prod,
       estado__in=['PENDIENTE', 'PARCIAL', 'BACK_ORDER'],
   ).exclude(
       pedido__estado__in=['ANULADO', 'CERRADO'],
   ).select_related('pedido').order_by('pedido__fecha_creacion')
   ```

   Alcance: todos los depósitos del sistema (no solo el del pedido en curso).
   Se agrupan en tres listas según `item.estado`: `pedidos_pendientes`,
   `pedidos_parciales`, `pedidos_backorder`.

### Por qué excluir `pedido.estado in (ANULADO, CERRADO)`

Se verificó en `views.py::anular_pedido` que anular un pedido **no** cambia
`PedidoItem.estado` — el pedido pasa a `ANULADO` pero sus items pueden seguir
en `PENDIENTE`/`PARCIAL`/`BACK_ORDER`. Sin este filtro explícito aparecerían
en la ficha pedidos ya anulados como si siguieran vigentes. `CERRADO` se
excluye por el mismo motivo de higiene, aunque `cerrar_pedido` sí marca los
items como `CERRADO` en la mayoría de los casos.

## Testing

Casos a cubrir en `PedidosAlmacen/tests.py`:

- Producto con items en los tres estados (pendiente, parcial, backorder) →
  aparecen en la lista correcta, con los campos esperados.
- Producto sin pedidos relacionados → las tres listas vienen vacías.
- Item de un pedido `ANULADO` → no aparece en ninguna lista.
- Item de un pedido `CERRADO` → no aparece.
- Pedidos de distintos depósitos → todos aparecen (alcance es sistema
  completo, no solo el depósito del pedido en curso).
- `X-Campo` faltante o inválido → `400`.
- DBISAM no encuentra el producto → `404`.
- Existencia se consulta solo para `DEPOSITO_ALMACEN` (mockear
  `consultar_stock` y verificar el argumento `deposito`).

## Fuera de alcance

- La UI del botón "ojito" en la app móvil (no vive en este repo).
- Desglose de existencia por depósito.
- Cambios al endpoint `api_buscar_producto` existente.
