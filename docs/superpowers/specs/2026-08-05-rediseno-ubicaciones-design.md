# Rediseño de ubicaciones físicas de almacén

**Fecha:** 2026-08-05

## Problema

La app `ubicaciones` actual (modelo `Rack → Nivel → Ubicación`, 3 niveles) no
refleja la estructura física real del almacén. No existe un nivel "Galpón",
no hay concepto de stock mínimo ni alertas automáticas, no hay mapa ni
leyenda visual, y `ProductoUbicacion` solo registra presencia (sin cantidad),
por lo que no se puede saber cuánta existencia hay en cada ubicación —
la cifra de existencia sigue siendo un total único de DBISAM sin segmentar.

Al revisar `Lay-Out CD1-CD2 KSA HOME CENTER (1).xls` (layout real del
almacén, con etiquetas ya impresas y un maestro de 2676 ubicaciones)
se confirmó que la jerarquía física real tiene **5 niveles**, no los 4
descritos inicialmente: **Galpón → Rack → Cuerpo → Ubicación → Nivel**,
con códigos ya impresos con el formato `1A0101.4` (Galpón 1, Rack A, Cuerpo
01, Ubicación 01, Nivel 4). El rediseño adopta este esquema real para no
requerir re-etiquetar el almacén.

## Alcance

Reemplazo completo del modelo de datos y funcionalidad de la app
`ubicaciones`: nueva jerarquía de 5 niveles, cantidad por ubicación validada
contra la existencia real en a2 (DBISAM), función picking/almacenaje con
stock mínimo y alertas por producto, fusión de espacios para mercancía
grande, mapa visual del galpón con leyenda, e importación del maestro físico
real (2 galpones, 11 racks, ~2676 ubicaciones) como datos iniciales.

No hay datos de producción que preservar (la app existe en código pero no
se ha usado operativamente), por lo que es un reemplazo directo, no una
migración de datos existentes.

## Decisiones (acordadas con el usuario)

1. **Sin migración de datos existentes.** Se resetean las migraciones de la
   app (`0001_initial.py`, `0002_grupo_pedidos_ubicaciones.py` se eliminan)
   y se genera una migración inicial limpia con el modelo nuevo.
2. **Jerarquía real de 5 niveles**, adoptada del layout físico ya impreso:
   `Galpón → Rack → Cuerpo → Ubicación → Nivel`. El código completo de un
   Nivel reproduce exactamente el formato ya usado en las etiquetas físicas
   (`1A0101.4`).
3. **Cantidad por ubicación, validada contra a2**: cada asignación de
   producto a un Nivel tiene una `cantidad`. Al guardar, se valida que la
   suma de cantidades de ese código de producto en todas sus asignaciones
   activas no exceda la existencia real en **SINVDEP, depósito 1** (mismo
   depósito que usa hoy la integración con `PedidosAlmacen`). No es
   obligatorio que la suma iguale el total — puede haber stock sin ubicar.
4. **Función Picking/Almacenaje por Nivel** (la unidad atómica real, dado
   que el código físico siempre termina en el Nivel). Cuerpo y Ubicación son
   puramente estructurales/organizativos, sin función propia.
5. **Stock mínimo por producto dentro del Nivel** (no agregado por Nivel):
   cada `ProductoUbicacion` en un Nivel `PICKING` puede tener su propio
   `stock_minimo`; en Niveles `ALMACENAJE` no aplica.
6. **Alertas solo en dashboard**, sin envío de correo. Se calculan on-demand
   (sin tabla de alertas ni tareas programadas).
7. **Fusión sobre Nivel únicamente**, entre Niveles del mismo Rack (cubre
   tanto "fusionar Ubicación A+B" como "fusionar niveles adyacentes en
   altura" con un solo mecanismo). Se implementa como FK autoreferencial
   `fusionado_en` (Nivel maestro con redirección — Opción B evaluada),
   evitando la dualidad de un modelo de "grupo de fusión" separado.
8. **Límites estructurales configurables por Rack**: `max_niveles` (default
   6) es configurable por Rack. La cantidad de Cuerpos por Rack no tiene
   tope (se crean incrementalmente). Cada Cuerpo tiene siempre exactamente
   2 Ubicaciones (regla física fija, confirmada en los 11 racks reales —
   223 cuerpos, 100% con 2 ubicaciones cada uno), con código autogenerado
   como numeración global dentro del Rack (`2×cuerpo-1` y `2×cuerpo`, no
   reiniciada por cuerpo) para reproducir exactamente la numeración ya
   impresa en las etiquetas físicas.
9. **Mapa del Galpón**: plano físico basado en grilla (no coordenadas libres
   en píxeles), replicando el mismo layout que ya usa el Excel — cada Rack
   ocupa una celda o rango de celdas de la grilla del Galpón.
10. **Leyenda**: incluye tanto la leyenda visual (colores/íconos del mapa y
    diagrama de Rack) como la guía de nomenclatura del código completo.
11. **Importación del maestro real**: se incluye un comando de gestión que
    importa la estructura completa (Galpones, Racks, Cuerpos, Ubicaciones,
    Niveles) desde un CSV exportado del Excel, como datos iniciales. No
    importa asignaciones de producto (el Excel no las tiene) — solo la
    estructura vacía.

## Modelo de datos

```
Galpón (1, 2)
  └── Rack (letra A-G / A-D, posición en grilla del plano)
        └── Cuerpo (bahía numerada, ej. 01..27 — cantidad variable por rack)
              └── Ubicación (siempre 2 por Cuerpo — regla fija)
                    └── Nivel (altura 1-6, configurable por Rack, default 6)
```

- **`Galpon`**: `codigo`, `nombre`, `grid_filas`, `grid_columnas` (tamaño de
  grilla del plano), `activo`, auditoría (`creado_por`, `fecha_creacion`,
  `fecha_modificacion` — mismo patrón que los modelos actuales).
- **`Rack`**: FK `Galpon`, `codigo` (letra), `grid_fila`, `grid_columna`,
  `ancho`, `alto` (posición/tamaño en la grilla del plano), `max_niveles`
  (`PositiveIntegerField`, default 6), `activo`, auditoría.
- **`Cuerpo`**: FK `Rack`, `codigo` (`CharField`, 2 dígitos con cero a la
  izquierda, autoincremental dentro del rack: "01", "02", …), `activo`,
  auditoría. Al crearse, autogenera sus 2 `Ubicacion`.
- **`Ubicacion`**: FK `Cuerpo`, `codigo` (`CharField`, 2 dígitos,
  autogenerado como numeración global dentro del Rack —
  `2×cuerpo.codigo - 1` y `2×cuerpo.codigo`, no reiniciada por cuerpo, para
  calzar exactamente con las etiquetas físicas ya impresas), `activo`,
  auditoría. Al crearse, autogenera sus `Nivel` según `rack.max_niveles`.
- **`Nivel`**: FK `Ubicacion`, `numero` (`PositiveSmallIntegerField`, 1-6),
  `tipo` (`PICKING`/`ALMACENAJE`), `fusionado_en` (FK a `self`, null=True —
  apunta al Nivel maestro cuando está fusionado), `activo`, auditoría.
  - `codigo_completo` (property): `f"{galpon.codigo}{rack.codigo}{cuerpo.codigo}{ubicacion.codigo}.{numero}"`
    → reproduce exactamente el formato ya impreso (`"1A0101.4"`).
- **`ProductoUbicacion`**: `codigo_producto`, FK `Nivel` (antes apuntaba a
  `Ubicacion`), `cantidad` (`PositiveIntegerField`), `stock_minimo`
  (`PositiveIntegerField`, nullable, solo relevante si
  `nivel.tipo == PICKING`), `asignado_por`, `fecha_asignacion`.
  `UniqueConstraint(codigo_producto, nivel)`.
- **`MovimientoUbicacion`**: bitácora inmutable, se extiende con FK a
  `Galpon` y `Cuerpo` además de `Rack`/`Nivel`/`Ubicacion` origen-destino;
  nuevos tipos: `CREACION_GALPON`, `EDICION_GALPON`,
  `DESACTIVACION_GALPON`, `CREACION_CUERPO`, `DESACTIVACION_CUERPO`,
  `FUSION_NIVEL`, `DESFUSION_NIVEL` (reemplazan/complementan los tipos
  actuales de `FUSION`).

## Reglas de negocio y validaciones

**Límites estructurales:**
- Al reducir `Rack.max_niveles`, se rechaza si existen Niveles activos con
  productos asignados en los números de nivel que quedarían fuera del nuevo
  tope (mismo patrón que la validación actual de `editar_rack`).
- Desactivar Galpón/Rack/Cuerpo/Ubicación se rechaza si tiene hijos activos
  (soft-delete en cascada bloqueada, igual que hoy).

**Cantidad vs. existencia a2:**
- Al asignar o editar `cantidad` en un `ProductoUbicacion`, se valida:
  `suma(cantidad de todas las asignaciones activas de ese codigo_producto) <= existencia SINVDEP depósito 1`.
  Si se excede, se rechaza indicando el exceso.

**Stock mínimo y alertas:**
- `stock_minimo` solo es editable si `nivel.tipo == PICKING`.
- Alerta = `cantidad < stock_minimo` sobre `ProductoUbicacion` en niveles
  picking con `stock_minimo` configurado. Panel en el dashboard, calculado
  on-demand vía query (sin tabla de alertas ni cron).

**Fusión (sobre `Nivel`, mismo Rack):**
- `fusionar_niveles(niveles: list[Nivel], maestro: Nivel, usuario)`: valida
  que todos pertenezcan al mismo Rack y que ninguno esté ya fusionado.
  Transfiere/consolida las cantidades de `ProductoUbicacion` de los
  miembros hacia el maestro (misma lógica de consolidación que el
  `fusionar_ubicaciones` actual) y setea `fusionado_en` en cada miembro.
- Un Nivel con `fusionado_en` no nulo no admite asignaciones directas ni
  edición de `tipo`/`stock_minimo` — todo pasa por el maestro.
- `desfusionar_nivel(nivel_miembro, usuario)`: limpia `fusionado_en`. Se
  rechaza si el maestro tiene productos asignados y quedan miembros sin
  desfusionar (evita perder trazabilidad de a qué nivel pertenece cada
  cantidad — hay que redistribuir manualmente antes).

## Mapa y leyenda

**Mapa del Galpón:**
- Vista basada en grilla CSS (`grid-template-columns`/`rows` según
  `galpon.grid_columnas`/`grid_filas`), replicando el layout ya usado en el
  Excel — cada Rack ocupa una celda o rango de celdas según
  `grid_fila`/`grid_columna`/`ancho`/`alto`.
- Cada Rack se colorea según estado agregado: normal, con alertas de stock
  mínimo activas, o con niveles fusionados.
- Clic en un Rack → detalle: diagrama de Cuerpos × Ubicaciones × Niveles
  (grilla más chica), coloreado por `tipo`, ocupación, fusión y alertas.
- Búsqueda por código de producto resalta en el plano todos los Niveles
  donde está asignado (reutiliza el patrón de `buscar_producto` ya
  integrado en `PedidosAlmacen`).

**Leyenda:**
- Visual: junto al plano y al diagrama de Rack, explica colores/íconos
  (picking, almacenaje, ocupado/libre, bajo mínimo, fusionado).
- Nomenclatura: sección de ayuda que explica cómo leer un código completo
  (`1A0101.4` = Galpón 1 / Rack A / Cuerpo 01 / Ubicación 01 / Nivel 4).

## Importación del maestro real

- Management command `import_maestro_ubicaciones` que lee un CSV exportado
  del Excel (columnas G, R, C, U, N — ya presentes en la hoja "MAESTRO DE
  UBIC") y crea, en orden, Galpón → Rack → Cuerpo → Ubicación → Nivel,
  usando `get_or_create` en cada nivel de la jerarquía (idempotente,
  re-ejecutable sin duplicar).
- No importa `ProductoUbicacion` (el Excel no trae asignaciones de
  producto) — solo crea la estructura vacía.
- Las coordenadas de grilla del plano (`grid_fila`/`grid_columna`/
  `ancho`/`alto` de cada uno de los 11 Racks) no vienen en formato tabular
  limpio en el Excel (solo el layout visual de celdas combinadas) — se
  transcriben a mano una vez, vía fixture o el admin de Django.

## Arquitectura y servicios

- **`ubicaciones/services.py`** (mismo patrón que hoy): `UbicacionesService`
  con métodos `crear_galpon/rack/cuerpo/ubicacion`, `editar_*`,
  `desactivar_*` (soft-delete, valida hijos activos), `asignar_producto`,
  `editar_cantidad`, `quitar_producto` (con validación contra a2),
  `fusionar_niveles`, `desfusionar_nivel`. Todos `@transaction.atomic`,
  todos registran en `MovimientoUbicacion`.
- **Migraciones**: se elimina el modelo actual (3 niveles) y se genera una
  migración inicial limpia con el modelo de 5 niveles.
- **Permisos**: se mantiene el grupo `Pedidos Ubicaciones` ya existente;
  mismas vistas protegidas por ese grupo.
- **Integración con `PedidosAlmacen`**: `buscar_producto` sigue enriqueciendo
  resultados con `ubicaciones_internas`, ahora resolviendo hasta `Nivel`
  (código completo tipo `1A0101.4`) en vez de la `Ubicacion` genérica
  anterior. El template `pedidos-buscar-producto.html` no cambia su
  estructura, solo el formato del código mostrado.

## Testing

- Modelo: autogeneración de Cuerpos/Ubicaciones/Niveles al crear sus
  padres, `codigo_completo` reproduce el formato físico real, constraint de
  unicidad `(codigo_producto, nivel)`.
- Servicio: validación de cantidad vs. existencia DBISAM (mockeada — no
  depende de DBISAM real), stock mínimo solo editable en picking, fusión y
  desfusión de niveles (incluye caso de rechazo por stock no redistribuido),
  reducción de `max_niveles` con niveles ocupados.
- Alertas: query de alertas detecta correctamente `cantidad < stock_minimo`
  solo en niveles picking.
- Comando de importación: contra un CSV de muestra pequeño (no el maestro
  completo de 2676 filas), verifica idempotencia (correrlo dos veces no
  duplica) y jerarquía correcta.
- Integración: `buscar_producto` de `PedidosAlmacen` sigue devolviendo
  `ubicaciones_internas` con el nuevo formato de código.

## Fuera de alcance

- Sincronización en tiempo real de cantidad contra DBISAM (la validación es
  solo al momento de guardar).
- Alertas por correo (solo dashboard, según decisión 6).
- Importación de asignaciones de producto reales (el Excel no las trae).
- Editor visual drag-and-drop del plano (las coordenadas de grilla se
  configuran vía formulario/admin, no arrastrando racks en pantalla).

## Notas técnicas

- El Excel de referencia (`Lay-Out CD1-CD2 KSA HOME CENTER (1).xls`) tiene 5
  hojas: `Galpon 1 120516 V.02` y `Lay-Out KHC 200726-V.01` (layouts
  visuales por galpón), `MAESTRO DE UBIC` (2676 filas, columnas G/R/C/U/P/N
  — fuente para el import), `Descripcion Ubicacion-Etiqueta` (leyenda de
  nomenclatura y dimensiones de etiqueta física) y `Maestro Ubicacion
  Aplicativo` (lista plana de los 2676 códigos, redundante con
  `MAESTRO DE UBIC`).
- Datos reales confirmados: Galpón 1 con Racks A-G (6 a 27 cuerpos según
  rack), Galpón 2 con Racks A-D (8 a 25 cuerpos según rack); 223 cuerpos en
  total, 100% con exactamente 2 ubicaciones; 100% de las ubicaciones con
  exactamente 6 niveles.
