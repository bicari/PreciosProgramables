# Formatos de impresión editables con ReportBro

**Fecha:** 2026-07-06
**Estado:** Aprobado

## Problema

Los PDFs de despacho y pedido se generan con código reportlab escrito a mano
(`PedidosAlmacen/pdf.py`). Cualquier cambio de formato — logo, columnas,
textos, orden — requiere modificar código Python y redesplegar. El objetivo es
que un superusuario pueda editar los formatos de impresión desde la propia app,
sin programar.

## Decisiones tomadas (con el usuario)

- **Objetivo:** editar formatos sin programar (diseñador visual incrustado en
  la app).
- **Alcance fase 1:** despacho (`pedidos-despacho-pdf`) y pedido
  (`pedidos-pdf`). El reporte de pedidos y las notas de entrega quedan para
  fases posteriores sobre la misma infraestructura.
- **Licencia:** ReportBro bajo **AGPLv3** (gratis). Válido mientras la app sea
  de uso interno y no se distribuya como producto a terceros.
- **Ubicación:** sección nueva "Formatos de impresión" en el menú de la app,
  visible y accesible **solo para superusuarios**.
- **Enfoque:** A — reemplazo con fallback. El generador reportlab actual se
  conserva intacto como respaldo.

## Qué es ReportBro

- `reportbro-designer`: editor visual JavaScript que se incrusta en una página
  y produce una **definición JSON** de la plantilla (layout, estilos,
  parámetros).
- `reportbro-lib` (~3.12, PyPI): librería Python que toma esa definición JSON
  más un diccionario de datos y genera el PDF en el servidor. Usa reportlab
  internamente (ya presente en requirements: 4.4.5; verificar compatibilidad
  de versiones al instalar).
- Patrón de integración de referencia: demo oficial
  [jobsta/albumapp-django](https://github.com/jobsta/albumapp-django).

## Arquitectura

App Django nueva: **`formatos`**. Es una pieza transversal — en esta fase
sirve a PedidosAlmacen; después servirá al reporte y a notas_entrega sin
acoplarse a ninguna app. Contiene el modelo de plantillas, las vistas del
diseñador, el endpoint de preview y la función de generación. PedidosAlmacen
solo la consume.

```
Superusuario → /formatos/ → diseñador JS (reportbro-designer)
                              │ guarda JSON          │ preview (PUT report/run)
                              ▼                      ▼
                    PlantillaImpresion (PG)   reportbro-lib + datos de ejemplo reales
Usuario almacén → exportar_despacho_pdf → ¿plantilla activa? ─ sí → reportbro-lib
                                                        └─ no / error → reportlab actual (fallback)
```

## Componentes

### Modelo `formatos.PlantillaImpresion` (PostgreSQL)

- `tipo`: CharField, choices `despacho` | `pedido` (extensible), **unique** —
  una plantilla por documento.
- `definicion`: JSONField — el JSON que produce el diseñador.
- `definicion_anterior`: JSONField nullable — se rota en cada guardado;
  permite "Restaurar versión anterior" (un solo nivel de historial).
- `activa`: BooleanField default `False` — interruptor del fallback: se diseña
  y prueba con la plantilla inactiva; solo al activarla los PDFs reales salen
  por ReportBro.
- `actualizado_por`: FK a `users.User`, nullable, `on_delete=SET_NULL`.
- `fecha_actualizacion`: DateTimeField `auto_now`.

### Modelo `formatos.ReportePreview` (PostgreSQL)

Almacén efímero de PDFs de preview (patrón del demo oficial): `key` (UUID),
`pdf` (BinaryField), `creado` (DateTimeField). Cada PUT limpia filas con más
de ~10 minutos.

### Contrato de datos — `formatos/contratos.py`

El código define qué datos puede usar cada plantilla; el diseñador solo los
consume:

- `datos_despacho(despacho, items) -> dict` y
  `datos_pedido(pedido, items) -> dict`: número de pedido, número de despacho,
  fechas (creación, despacho, recepción), solicitante, tienda/depósito,
  estado, condición, responsables, y lista `items` con código, descripción,
  referencia, puesto, referencia de proveedor, cantidades (solicitada,
  despachada, back order, recibida) y observación — los mismos campos que hoy
  pinta `PedidosAlmacen/pdf.py`.
- Estas funciones son la **única fuente de datos** para la generación real y
  para el preview.

### Plantillas semilla — `formatos/plantillas_iniciales/*.json`

Una definición ReportBro por tipo con los **parámetros ya declarados** y un
layout básico equivalente al formato actual. El superusuario nunca parte de
cero ni declara parámetros a mano. Se cargan cuando no existe fila en
`PlantillaImpresion` para el tipo.

### Vistas y URLs (`formatos/urls.py`, todas solo superusuario)

- `GET /formatos/` — lista de plantillas con el estilo de la app (pd-header +
  pl-table-card): tipo, activa sí/no, última modificación, quién; acciones
  Editar / Activar / Desactivar / Restaurar.
- `GET /formatos/<tipo>/disenar/` — página a pantalla completa con el
  diseñador cargado con `definicion` (o la semilla).
- `POST /formatos/<tipo>/guardar/` — guarda el JSON del diseñador; rota
  `definicion` → `definicion_anterior`.
- `POST /formatos/<tipo>/activar/` y `.../desactivar/` — al activar se valida
  generando un PDF con datos de ejemplo; si falla, no se activa y se muestra
  el error.
- `POST /formatos/<tipo>/restaurar/` — intercambia `definicion` y
  `definicion_anterior`.
- `PUT/GET /formatos/report/run` — endpoint de preview (protocolo estándar del
  diseñador, ver abajo).

### Preview — protocolo `report/run`

`PUT` recibe `{report, outputFormat, data, isTestData}` y ejecuta
`reportbro-lib`:

- Plantilla con errores → responde la lista de errores; el diseñador los marca
  visualmente sobre el elemento defectuoso.
- OK → guarda el PDF en `ReportePreview` y responde `key:<uuid>`.

`GET ?key=<uuid>&outputFormat=pdf` descarga el PDF. Los datos de prueba salen
del **último despacho/pedido real** vía las funciones de contrato (o de un
diccionario sintético si la BD está vacía). CSRF se maneja en la
inicialización del diseñador (header `X-CSRFToken`).

### Generación real con fallback — `formatos/generacion.py`

`generar_pdf(tipo, datos) -> bytes | None`:

- Busca la plantilla activa del tipo; si no hay, devuelve `None`.
- Ejecuta `Report(definicion, datos).generate_pdf()`; ante **cualquier**
  excepción hace `logger.error` y devuelve `None`.

Las vistas `exportar_despacho_pdf` y `exportar_pedido_pdf` de
`PedidosAlmacen/views.py` cambian mínimamente: intentan
`formatos.generacion.generar_pdf(...)` y si reciben `None` llaman al generador
reportlab actual (`PedidosAlmacen/pdf.py`), que **no se modifica**. La
generación real nunca rompe la operación del almacén.

### Dependencias y estáticos

- `reportbro-lib` en `requirements.txt`.
- `reportbro-designer` self-hosted en `static/vendor/reportbro/` (JS + CSS del
  release oficial, sin CDN), como ya se hace con DataTables.
- Entrada nueva en el menú de navegación, visible solo para superusuarios.

## Manejo de errores

- **Preview:** errores de plantilla → los muestra el diseñador; error
  inesperado → HTTP 500 con mensaje y `logger.error`.
- **Generación real:** nunca lanza — cualquier fallo cae al generador
  reportlab con log de error.
- **Guardado:** JSON inválido o `tipo` desconocido → HTTP 400.
- **Activación:** plantilla que no compila con datos de ejemplo → no se
  activa, mensaje de error al usuario.

## Tests (`formatos/tests.py` + ajuste en `PedidosAlmacen/tests.py`)

1. Modelo: unicidad por tipo; guardado rota `definicion_anterior`; restaurar
   intercambia versiones.
2. Permisos: usuario no superusuario recibe redirect/403 en todas las vistas
   de formatos.
3. Generación: con plantilla activa el PDF sale de ReportBro; sin plantilla o
   con plantilla rota, `generar_pdf` devuelve `None` y la vista de exportación
   cae al reportlab actual (mock de `Report`).
4. Activación: plantilla que no compila es rechazada.
5. Contrato: `datos_despacho`/`datos_pedido` devuelven todas las claves
   prometidas.
6. Preview: PUT devuelve `key:` y GET con esa key descarga un PDF;
   `ReportePreview` viejo se limpia.

Suite ejecutable con SQLite en memoria (patrón existente
`--settings=test_settings_sqlite`).

## Casos límite aceptados

- Historial de una sola versión anterior (no versionado completo). Si se
  necesita más profundidad, se amplía después.
- Si la plantilla activa referencia un parámetro que el contrato ya no
  provee, la generación falla y cae al fallback (queda en el log).
- El formato reportlab y la plantilla ReportBro pueden divergir visualmente
  mientras conviven; el fallback garantiza continuidad operativa, no identidad
  visual.
