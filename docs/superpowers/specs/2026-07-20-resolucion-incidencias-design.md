# Módulo de Resolución de Incidencias — Diseño

**Fecha:** 2026-07-20
**App:** PedidosAlmacen

## Problema

Las incidencias de recepción de despachos solo quedan registradas como un estado
del propio SKU (`PedidoItem.estado = 'INCIDENCIA'` y
`DespachoItem.tipo_incidencia`). No hay forma de registrar ni reportar su
resolución: cuando el problema se corrige en a2 mediante un traslado interno,
la app sigue mostrando la incidencia como abierta y el despacho queda en
`PARCIAL` indefinidamente.

## Objetivo

Un módulo operativo de resolución de incidencias, con la misma estética del
reporte informativo actual (`reporte_incidencias`), donde un supervisor:

1. Selecciona una o varias incidencias pendientes.
2. Registra el número de documento del traslado interno de a2 que las corrigió
   (o una resolución manual sin documento, con observación obligatoria).
3. La app valida contra a2 que el traslado existe y cubre los SKUs afectados.
4. Los estados de items y despachos se actualizan automáticamente.

El reporte informativo actual se mantiene intacto.

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Granularidad | Un traslado puede resolver varias incidencias a la vez |
| Validación a2 | Documento existe como traslado (FTI_TIPO=1) + cada SKU aparece en el detalle |
| Tipos de resolución | Con traslado (normal) o manual sin documento (observación obligatoria) |
| Permisos | Solo supervisores (`is_pedidos_supervisor`), igual que el reporte actual |
| Estado del item | Nuevo estado `INCIDENCIA_RESUELTA` en `PedidoItem` |
| Despacho | `PARCIAL` → `RECIBIDO` cuando no queden incidencias pendientes |
| Anulación | Sí, solo supervisores; revierte estados y deja auditoría |
| Modelo de datos | Opción C: modelo de resolución + historial de eventos inmutable |

## 1. Modelo de datos

Tres piezas en `PedidosAlmacen/models.py`:

### `ResolucionIncidencia`

El acto de resolución que agrupa incidencias resueltas juntas.

- `tipo`: `TRASLADO` | `MANUAL`
- `documento_traslado`: `CharField`, número de documento a2 (vacío si `MANUAL`)
- `observacion`: obligatoria cuando `tipo=MANUAL`, opcional en `TRASLADO`
- `resuelto_por`: FK a `User` (`SET_NULL`)
- `fecha_resolucion`: `DateTimeField(auto_now_add=True)`
- `estado`: `ACTIVA` | `ANULADA`
- `anulada_por`: FK a `User` (`SET_NULL`, null)
- `fecha_anulacion`: `DateTimeField(null=True)`
- `motivo_anulacion`: `CharField(blank=True)` — obligatorio al anular

### `IncidenciaEvento`

Log inmutable por item — nunca se edita ni borra; cada acción agrega filas. El
historial completo de una incidencia se lee de aquí.

- `despacho_item`: FK a `DespachoItem`
- `resolucion`: FK a `ResolucionIncidencia`
- `tipo_evento`: `RESOLUCION` | `ANULACION`
- `usuario`: FK a `User` (`SET_NULL`)
- `fecha`: `DateTimeField(auto_now_add=True)`
- `detalle`: `CharField(blank=True)` — snapshot legible (ej. documento usado,
  motivo de anulación)

### `DespachoItem.resolucion`

FK nullable denormalizado a la `ResolucionIncidencia` **activa**. Es el atajo
de consulta:

- Incidencia pendiente: `tipo_incidencia != '' AND resolucion IS NULL`
- Incidencia resuelta: `resolucion IS NOT NULL`

Al anular una resolución, el FK vuelve a `NULL` (el historial queda en los
eventos). Una incidencia anulada puede resolverse de nuevo con otro documento,
generando más eventos.

### Estado nuevo en `PedidoItem`

Se agrega `INCIDENCIA_RESUELTA` a los choices de estado de `PedidoItem`, con su
badge correspondiente en las plantillas que muestran estados de items.

## 2. Validación contra a2 (`PedidosAlmacen/dbisam.py`)

Nuevo método `validar_traslado_resolucion(nro_documento: str, codigos: list[str])`:

1. Busca en `SOPERACIONINV` el documento con `FTI_TIPO = 1` (traslado) y
   visible. Si no existe → error "el documento no es un traslado válido en a2".
2. Consulta `SDETALLEINV` (por `FDI_DOCUMENTO` + `FDI_OPERACION_AUTOINCREMENT`
   del traslado encontrado) y devuelve el conjunto de códigos presentes en el
   detalle.
3. El caller compara: cada SKU de las incidencias seleccionadas debe estar en
   ese conjunto. Si falta alguno → error indicando cuáles SKUs no aparecen.

Notas:

- Para `PRODUCTO_ERRONEO` y `SKU_NO_CONTEMPLADO` el SKU a validar es
  `codigo_real` (lo que realmente llegó); para `CANTIDAD_MENOR` /
  `CANTIDAD_MAYOR`, el código del `pedido_item`.
- No se validan cantidades (un traslado puede agrupar cantidades de varias
  incidencias del mismo SKU).
- Sin placeholders `?` — f-strings con sanitización upstream, como el resto de
  `dbisam.py`. SQL92 sin CTEs.

## 3. Vista y flujo de UI

Nueva página **"Resolución de Incidencias"** en
`/pedidos/incidencias/resolver/`, protegida con `is_pedidos_supervisor`, basada
en la plantilla del reporte actual (`pedidos-reporte-incidencias.html`) pero
operativa:

- **Dos pestañas/filtros**: *Pendientes* y *Resueltas*, más los filtros de
  fecha y tipo de incidencia del reporte actual.
- **Pendientes**: tabla con checkbox por incidencia. El supervisor selecciona
  una o varias y abre un panel/modal con dos modos:
  - *Resolver con traslado*: campo para el número de documento → botón
    "Validar" (AJAX contra a2) → muestra el resultado (documento encontrado,
    SKUs cubiertos / faltantes) → "Confirmar resolución" habilitado solo si la
    validación pasó.
  - *Resolución manual*: sin documento; observación obligatoria.
- **Resueltas**: muestra documento, tipo, quién resolvió y cuándo; botón
  "Anular" (pide motivo obligatorio) y detalle expandible con el historial de
  eventos (`IncidenciaEvento`) del item.
- El POST de confirmación **revalida contra a2 en servidor** — no confía en la
  validación AJAX previa — dentro de una transacción.

Endpoints:

- `GET /pedidos/incidencias/resolver/` — página principal (pendientes/resueltas)
- `POST /pedidos/incidencias/resolver/validar/` — AJAX: valida documento + SKUs
- `POST /pedidos/incidencias/resolver/confirmar/` — crea la resolución
- `POST /pedidos/incidencias/resolver/anular/<id>/` — anula una resolución

Entrada al módulo desde el menú de supervisores, junto al reporte de
incidencias existente.

## 4. Efectos sobre estados existentes

Al confirmar una resolución (transacción atómica en PostgreSQL):

1. Crea `ResolucionIncidencia` + un `IncidenciaEvento` (`RESOLUCION`) por item.
2. Asigna `DespachoItem.resolucion`.
3. Cada `PedidoItem` asociado pasa de `INCIDENCIA` → `INCIDENCIA_RESUELTA`.
4. Si el `Despacho` está `PARCIAL` y ya no le quedan items con incidencia
   pendiente, pasa a `RECIBIDO`.

Al anular una resolución:

1. `ResolucionIncidencia.estado` → `ANULADA` (con quién, cuándo y motivo).
2. `DespachoItem.resolucion` → `NULL` en todos los items del grupo.
3. Cada `PedidoItem` vuelve de `INCIDENCIA_RESUELTA` → `INCIDENCIA`.
4. El `Despacho` vuelve de `RECIBIDO` → `PARCIAL` si había cambiado por esta
   resolución (es decir, si vuelve a tener incidencias pendientes).
5. Un `IncidenciaEvento` (`ANULACION`) por item.

Las métricas existentes que cuentan `estado='INCIDENCIA'` bajan al resolver —
comportamiento deseado. El reporte informativo actual no cambia.

Ejemplo de referencia: un despacho con 10 items, 8 bien y 2 con incidencia,
queda `PARCIAL` con 2 items en `INCIDENCIA`. Si el supervisor resuelve solo 1,
el despacho sigue `PARCIAL`; al resolver la segunda, pasa a `RECIBIDO`. Si
luego anula una de las resoluciones, el item vuelve a `INCIDENCIA` y el
despacho a `PARCIAL`.

## 5. Manejo de errores

- **a2 inaccesible (error ODBC):** mensaje claro; no se permite resolver con
  traslado (la resolución manual sigue disponible). Nunca se guarda una
  resolución con validación fallida.
- **Documento inexistente o SKUs no cubiertos:** error específico listando los
  SKUs que faltan en el traslado.
- **Concurrencia:** el POST de confirmación verifica que las incidencias sigan
  pendientes (`resolucion IS NULL`) dentro de la transacción; si otra sesión
  las resolvió, error amable sin efectos parciales.
- **Anulación sin motivo / resolución manual sin observación:** rechazadas con
  error de validación.

## 6. Testing

En `PedidosAlmacen/tests.py`, con mock del cliente dbisam:

- Resolución con traslado válido → estados de item/despacho actualizados,
  eventos creados.
- Documento inexistente → error, sin cambios.
- SKU no cubierto por el traslado → error listando faltantes.
- Resolución manual sin observación → error de validación.
- Resolución manual válida → sin llamada a a2.
- Resolución parcial (1 de 2 incidencias) → despacho sigue `PARCIAL`.
- Anulación → reversión completa de estados + eventos `ANULACION`.
- Re-resolución tras anulación → historial de eventos acumulado correcto.
- Concurrencia: incidencia ya resuelta por otra sesión → error sin efectos.
- Permisos: usuario no supervisor → redirect.

## Fuera de alcance

- Modificar el flujo de registro de incidencias en la recepción.
- Insertar o modificar traslados en a2 desde este módulo (solo lectura).
- Notificaciones por correo de resoluciones.
- Cambios al reporte informativo existente.
