/* ============================================================================
   DETECCIÓN DE RECEPCIONES CON DEPÓSITO TRÁNSITO INCORRECTO
   ============================================================================

   Incidente: la constante DEPOSITO_TRANSITO (PedidosAlmacen/dbisam.py) se
   cambió de 10 a 15. Los despachos hechos ANTES del cambio movieron stock
   almacén (1) -> tránsito 10, pero las recepciones hechas DESPUÉS del cambio
   descargaron del tránsito 15 -> depósito destino de la tienda.

   Efecto en a2:
     - Stock atascado en el depósito 10 (entró por despacho y nunca salió).
     - Existencias NEGATIVAS en el depósito 15 (la app inserta fila negativa
       en SINVDEP cuando el producto no existe en el depósito origen).

   No hay vínculo por documento entre despacho y recepción en a2 (el despacho
   usa numero_despacho y la recepción usa numero_pedido como FTI_DOCUMENTO),
   por lo que la detección se hace por BALANCE POR PRODUCTO en cada depósito
   tránsito, no por matching 1:1 de documentos.

   Compatibilidad DBISAM (SQL92): sin CTE, sin EXISTS, sin derived tables.
   Quirks verificados contra el motor real (2026-07-05):
     - HAVING debe referenciar el ALIAS de la columna del SELECT, no repetir
       la expresión (error 11949 si se repite el SUM(CASE...)).
     - Toda columna usada en ORDER BY debe estar presente en el SELECT.
     - CASE WHEN funciona en SELECT/HAVING (verificado en este motor).
   Si alguna versión del driver rechazara CASE, usar la sintaxis nativa
   DBISAM:  IF(condición THEN valor ELSE valor)
   Ejemplo: SUM(IF(FDI_DEPOSITOTARGET = 15 THEN FDI_CANTIDAD ELSE 0))

   Ejecutar Q1..Q4 (solo lectura) y revisar antes de aplicar cualquier ajuste.
   ============================================================================ */


/* ----------------------------------------------------------------------------
   Q1 — EXCESO RETIRADO DEL TRÁNSITO 15, AGRUPADO POR PRODUCTO
   ----------------------------------------------------------------------------
   Balance de traslados (FDI_TIPOOPERACION = 1) sobre el depósito 15:
   salidas (recepciones) menos entradas (despachos). Un EXCESO_RETIRADO > 0
   significa que se recibieron unidades descargando del 15 sin que ningún
   despacho las hubiera puesto ahí => recepciones con tránsito incorrecto.

   ESTA ES LA CANTIDAD A AJUSTAR POR PRODUCTO.

   Caveat: despachos nuevos al 15 aún PENDIENTES de recibir suman entradas
   sin salidas y pueden enmascarar parte del exceso. Cruzar siempre con Q2
   (atascado en 10) y Q4 (SINVDEP) antes de decidir el ajuste.
---------------------------------------------------------------------------- */

SELECT FDI_CODIGO,
       SUM(CASE WHEN FDI_DEPOSITOTARGET = 15 THEN FDI_CANTIDAD ELSE 0 END) AS ENTRADAS_15,
       SUM(CASE WHEN FDI_DEPOSITOSOURCE = 15 THEN FDI_CANTIDAD ELSE 0 END) AS SALIDAS_15,
       SUM(CASE WHEN FDI_DEPOSITOSOURCE = 15 THEN FDI_CANTIDAD ELSE -FDI_CANTIDAD END) AS EXCESO_RETIRADO
FROM SDETALLEINV
WHERE FDI_TIPOOPERACION = 1
  AND (FDI_DEPOSITOSOURCE = 15 OR FDI_DEPOSITOTARGET = 15)
GROUP BY FDI_CODIGO
HAVING EXCESO_RETIRADO > 0
ORDER BY FDI_CODIGO;


/* ----------------------------------------------------------------------------
   Q2 — SALDO ATASCADO EN EL TRÁNSITO 10, AGRUPADO POR PRODUCTO
   ----------------------------------------------------------------------------
   Espejo de Q1 sobre el depósito 10: lo que entró por despachos y nunca
   salió (porque las recepciones descargaron del 15). Tras el cambio de
   constante ya ninguna recepción descarga del 10, así que todo saldo
   positivo aquí es candidato a ajuste.

   En condiciones normales ATASCADO_EN_10 (Q2) == EXCESO_RETIRADO (Q1) por
   producto. Si difieren, investigar el producto antes de ajustar.
---------------------------------------------------------------------------- */

SELECT FDI_CODIGO,
       SUM(CASE WHEN FDI_DEPOSITOTARGET = 10 THEN FDI_CANTIDAD ELSE 0 END) AS ENTRADAS_10,
       SUM(CASE WHEN FDI_DEPOSITOSOURCE = 10 THEN FDI_CANTIDAD ELSE 0 END) AS SALIDAS_10,
       SUM(CASE WHEN FDI_DEPOSITOTARGET = 10 THEN FDI_CANTIDAD ELSE -FDI_CANTIDAD END) AS ATASCADO_EN_10
FROM SDETALLEINV
WHERE FDI_TIPOOPERACION = 1
  AND (FDI_DEPOSITOSOURCE = 10 OR FDI_DEPOSITOTARGET = 10)
GROUP BY FDI_CODIGO
HAVING ATASCADO_EN_10 > 0
ORDER BY FDI_CODIGO;


/* ----------------------------------------------------------------------------
   Q3 — DETALLE POR DOCUMENTO: RECEPCIONES QUE SALIERON DEL 15 (AUDITORÍA)
   ----------------------------------------------------------------------------
   FTI_DOCUMENTO aquí es el NÚMERO DE PEDIDO de la app (padded a 8 dígitos),
   lo que permite cruzar contra Postgres (tabla Pedido/Despacho) para saber
   a qué despacho correspondía cada recepción y con qué tránsito se despachó.

   Para acotar al período del incidente, descomentar el filtro de fecha y
   poner la fecha del deploy del cambio de constante.
---------------------------------------------------------------------------- */

SELECT S.FTI_DOCUMENTO AS NRO_PEDIDO,
       S.FTI_FECHAEMISION,
       S.FTI_HORA,
       S.FTI_RESPONSABLE,
       S.FTI_DEPOSITODESTINO,
       D.FDI_CODIGO,
       I.FI_DESCRIPCION,
       D.FDI_CANTIDAD,
       D.FDI_LINEA
FROM SOPERACIONINV S
INNER JOIN SDETALLEINV D ON S.FTI_AUTOINCREMENT = D.FDI_OPERACION_AUTOINCREMENT
INNER JOIN SINVENTARIO I ON D.FDI_CODIGO = I.FI_CODIGO
WHERE S.FTI_TIPO = 1
  AND S.FTI_DEPOSITOSOURCE = 15
  /* AND S.FTI_FECHAEMISION >= 'YYYY-MM-DD' */
ORDER BY S.FTI_FECHAEMISION, S.FTI_DOCUMENTO, D.FDI_LINEA;


/* ----------------------------------------------------------------------------
   Q4 — VERIFICACIÓN CRUZADA CONTRA SINVDEP (ESTADO ACTUAL)
   ----------------------------------------------------------------------------
   Si nada más mueve los depósitos 10 y 15:
     - Los negativos en 15 deben cuadrar con EXCESO_RETIRADO de Q1.
     - Los positivos en 10 deben cuadrar con ATASCADO_EN_10 de Q2.
   Cualquier producto que no cuadre debe investigarse antes de ajustar.
---------------------------------------------------------------------------- */

SELECT FT_CODIGOPRODUCTO, FT_CODIGODEPOSITO, FT_EXISTENCIA
FROM SINVDEP
WHERE (FT_CODIGODEPOSITO = 15 AND FT_EXISTENCIA < 0)
   OR (FT_CODIGODEPOSITO = 10 AND FT_EXISTENCIA <> 0)
ORDER BY FT_CODIGOPRODUCTO, FT_CODIGODEPOSITO;


/* ============================================================================
   Q5 — AJUSTE PROPUESTO (PLANTILLA — EJECUCIÓN MANUAL TRAS REVISAR Q1..Q4)
   ============================================================================
   Un solo movimiento por producto corrige ambos depósitos: transferir el
   EXCESO_RETIRADO (Q1) de 10 -> 15. Esto elimina el stock atascado en 10 y
   cancela el negativo en 15, dejando saldo correcto para los despachos al 15
   que sigan legítimamente pendientes de recepción.

   OPCIÓN RECOMENDADA:
     Registrar el traslado correctivo 10 -> 15 desde el propio a2 (módulo de
     traslados), producto por producto con las cantidades de Q1. Deja
     documento auditable en SOPERACIONINV / SDETALLEINV.

   OPCIÓN SQL DIRECTA (sin documento — solo si se acepta ajustar existencias
   sin rastro de operación). Reemplazar <CODIGO> y <EXCESO> por producto:

   ADVERTENCIA: usar las cantidades de Q1 (EXCESO_RETIRADO), no las de Q2,
   cuando difieran — y si difieren, investigar el producto antes de ajustar
   (probable despacho al 15 pendiente de recepción, que NO debe ajustarse).
---------------------------------------------------------------------------- */

/*
UPDATE SINVDEP SET FT_EXISTENCIA = COALESCE(FT_EXISTENCIA, 0) - <EXCESO>
WHERE FT_CODIGOPRODUCTO = '<CODIGO>' AND FT_CODIGODEPOSITO = 10;

UPDATE SINVDEP SET FT_EXISTENCIA = COALESCE(FT_EXISTENCIA, 0) + <EXCESO>
WHERE FT_CODIGOPRODUCTO = '<CODIGO>' AND FT_CODIGODEPOSITO = 15;
*/
