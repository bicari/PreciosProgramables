import logging
import pyodbc
from django.conf import settings
from datetime import datetime
from itertools import zip_longest
from uuid import uuid4
from notas_entrega.sanitize import quote_str, quote_date, to_int, to_decimal, escape_pascal_literal

logger = logging.getLogger(__name__)


class DBISAMDatabase:
    def __init__(self):
        self.dsn = settings.DBISAM_DATABASE['DSN']
        self.catalog = settings.DBISAM_DATABASE['CatalogName']
        self.tmp_table_tasks = settings.DBISAM_DATABASE['TMP_TABLE_TASKS']
        self.almacen_ppal = settings.ALMACEN_PPAL
        self.almacen_items_sin_oc = settings.ALMACEN_PRODUCTOS_SIN_OC
        

    def connect(self):
        return pyodbc.connect(f'DSN={self.dsn};CatalogName={self.catalog};PrivateDirectory={self.tmp_table_tasks}')
    

    def search_order(self, order_number, proveedor):
        order_numbers = order_number[0]
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                            FDI_CODIGO,
                                            SUM(FDI_CANTIDADPENDIENTE),
                                            FDI_DOCUMENTO,
                                            FDI_COSTOOPERACION,
                                            FDI_IMPUESTO1,
                                            FDI_MONEDA,
                                            FDI_DEPOSITOSOURCE,
                                            FI_DESCRIPCION,
                                            FTI_AUTOINCREMENT,
                                            FI_PUESTO,
                                            FI_REFERENCIA,
                                            ZZCAMPO_001,
                                            FDI_MONTOIMPUESTO1,
                                            FTI_DETALLECOMENTARIO
                                        FROM SOPERACIONINV
                                        INNER JOIN SDETALLECOMPRA ON FTI_AUTOINCREMENT = FDI_OPERACION_AUTOINCREMENT
                                        INNER JOIN SINVENTARIO ON FDI_CODIGO = FI_CODIGO
                                        WHERE FDI_CLIENTEPROVEEDOR = {quote_str(proveedor, max_len=20)}
                                        AND FDI_DOCUMENTO = {quote_str(order_numbers, max_len=20)}
                                        AND FDI_STATUS = 4
                                        AND FDI_CANTIDADPENDIENTE > 0 AND FTI_TIPO = 5
                                        GROUP BY FDI_CODIGO""").fetchall()
                    return rows
        except Exception as e:
            raise pyodbc.DatabaseError(e)

    def search_proveedor(self, codigo_proveedor):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                                FP_CODIGO,
                                                FP_DESCRIPCION,
                                                FP_DIRECCION1
                                          FROM SPROVEEDOR
                                          WHERE FP_CODIGO = {quote_str(codigo_proveedor, max_len=20)} AND FP_STATUS = 1
                                    """).fetchone()
                return rows
        except Exception as e:
            return str(e)

    def search_product(self, sku):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    sku_sql = quote_str(sku, max_len=50)
                    row = cursor.execute(f"""SELECT
                                                FI_CODIGO,
                                                FI_DESCRIPCION, FIC_COSTOACTBOLIVARES, FIC_COSTOACTEXTRANJERO,
                                                FIC_IMP01MONTO, FI_PUESTO, FI_REFERENCIA, ZZCAMPO_001
                                        FROM SINVENTARIO
                                        INNER JOIN A2INVCOSTOSPRECIOS ON FI_CODIGO = FIC_CODEITEM
                                        WHERE FI_REFERENCIA = {sku_sql} OR FI_CODIGO = {sku_sql}""").fetchone()
                    return row
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def search_product_by_description(self, description):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    desc_escaped = description.replace("'", "''")
                    row = cursor.execute(f"""SELECT
                                     FI_CODIGO,
                                     FI_DESCRIPCION,
                                     FI_CATEGORIA,
                                     FIC_COSTOACTBOLIVARES, FIC_COSTOACTEXTRANJERO, FIC_IMP01MONTO,
                                     FI_PUESTO,
                                     FI_REFERENCIA, ZZCAMPO_001
                                     FROM SINVENTARIO
                                     INNER JOIN A2INVCOSTOSPRECIOS ON FI_CODIGO = FIC_CODEITEM
                                     WHERE FI_DESCRIPCION LIKE '%{desc_escaped}%'""").fetchmany(200)
                    return row
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def search_proveedor_by_description(self, description):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    desc_escaped = description.replace("'", "''")
                    row = cursor.execute(f"""SELECT
                                        FP_CODIGO,
                                        FP_DESCRIPCION,
                                        FP_DIRECCION1
                                        FROM SPROVEEDOR
                                        WHERE FP_DESCRIPCION LIKE '%{desc_escaped}%'""").fetchmany(200)
                    return row
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def create_table_tmp(self, name_table):
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" ("SKU" VARCHAR(50), "CODBARRA" VARCHAR(50),"DESCRIPCION" VARCHAR(150),
                            "DESCRIPCION_OFERTA" VARCHAR(150),
                            "FECHA_INICIO" DATE,
                            "FECHA_FINAL" DATE,
                            "DEPARTAMENTO" VARCHAR(40),
                            "PRECIOANTES" FLOAT,
                            "PRECIO" FLOAT,
                            "EXISTENCIA" FLOAT DEFAULT 0.00,
                            "ACTUALIZADO" BOOLEAN DEFAULT FALSE,
                            "IVA" INTEGER);
                    CREATE INDEX IF NOT EXISTS "INDEX_SKU" ON "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" (SKU);
                """)

    def insert_data_tmp(self, data: dict):
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"""INSERT INTO "{self.tmp_table_tasks}\\TMPDJANGO{data['Tabla']}" (SKU, FECHA_INICIO, FECHA_FINAL, PRECIO, PRECIOANTES, DESCRIPCION_OFERTA)
                               VALUES ('{data['Sku']}', '{data['FechaInicio']}','{data['FechaFinal']}', {data['Precio']}, {data['PrecioAntes']}, '{data['Descripcion_Oferta']}')""")
                conn.commit()
    
    def notas_entrega_correlativo(self):
        """Devuelve el próximo correlativo sin reservarlo. Usar insert_notas_entrega para reservarlo atómicamente."""
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    row = cursor.execute("SELECT NO_NOTAENTREGAPROV FROM SSISTEMA WHERE DUMMYKEY=''").fetchone()
                    return row.NO_NOTAENTREGAPROV
        except Exception as e:
            logger.error('notas_entrega_correlativo error: %s', e)
            raise

    def insert_notas_entrega(self, request: dict):
        """Inserta nota de entrega de proveedor de forma atómica.

        El correlativo se reserva dentro de la transacción (UPDATE antes de SELECT)
        para evitar duplicados bajo concurrencia. Si cualquier execute falla se
        ejecuta ROLLBACK antes de propagar la excepción.

        Returns:
            dict: {'ok': True, 'nro_nota': int}
        Raises:
            pyodbc.Error: tras ROLLBACK si falla alguna operación DBISAM.
            ValueError: si algún campo del payload no supera la validación de sanitize.
        """
        with self.connect() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("START TRANSACTION;")

                    # Reservar correlativo bajo lock (previene race condition)
                    cursor.execute("UPDATE SSISTEMA SET NO_NOTAENTREGAPROV = NO_NOTAENTREGAPROV + 1 WHERE DUMMYKEY = ''")
                    row = cursor.execute("SELECT NO_NOTAENTREGAPROV FROM SSISTEMA WHERE DUMMYKEY = ''").fetchone()
                    nro_nota = row.NO_NOTAENTREGAPROV
                    nro_documento = str(nro_nota).rjust(8, '0')

                    # Sanitizar campos de cabecera
                    moneda_operacion = to_int(request['moneda'], 'moneda')
                    rif_sql = quote_str(request['rif'], max_len=20)
                    proveedor_sql = quote_str(request['proveedor'], max_len=120)
                    comentario_sql = escape_pascal_literal(request.get('comentario', ''), max_len=500)
                    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
                    hora_ahora = datetime.now().strftime("%I:%M:%S %p")
                    fecha_sql = quote_date(fecha_hoy)
                    hora_sql = quote_str(hora_ahora, max_len=12)
                    fecha_venc = request['fecha_vencimiento']
                    fecha_venc_sql = quote_date(fecha_venc.strftime('%Y-%m-%d') if hasattr(fecha_venc, 'strftime') else str(fecha_venc))
                    total_items = len(request['ordenes']) + len(request['productoSinOc'])
                    total_bruto_sql = to_decimal(request['total_bruto'], 'total_bruto')
                    base_imponible_sql = to_decimal(request['base_imponible'], 'base_imponible')
                    iva_sql = to_decimal(request['iva'], 'iva')
                    total_neto_sql = to_decimal(request['total_neto'], 'total_neto')
                    ordenes_ids = [str(o['orden']) for o in request['ordenes']]
                    ordenes_compra_sql = quote_str(''.join(ordenes_ids), max_len=200)

                    # INSERT cabecera SOPERACIONINV
                    cursor.execute(f"""
                        INSERT INTO SOPERACIONINV (
                            FTI_DOCUMENTO, FTI_TIPO, FTI_STATUS, FTI_VISIBLE,
                            FTI_FECHAEMISION, FTI_DEPOSITOSOURCE, FTI_TOTALITEMS,
                            FTI_TOTALITEMSINICIAL, FTI_MONEDA, FTI_FACTORCAMBIO,
                            FTI_TOTALCOSTO, FTI_USER, FTI_RESPONSABLE, FTI_UPDATEITEMS,
                            FTI_TOTALBRUTO, FTI_DESCUENTO1PORCENT, FTI_DESCUENTO1MONTO,
                            FTI_BASEIMPONIBLE, FTI_IMPUESTO1PORCENT, FTI_IMPUESTO1MONTO,
                            FTI_TOTALNETO, FTI_PERSONACONTACTO, FTI_ORDENCOMPRA,
                            FTI_DOCUMENTOORIGEN, FTI_HORA, FTI_FECHALIBRO, FTI_DETALLECOMENTARIO,
                            FTI_FECHAVENCIDO
                        ) VALUES (
                            '{nro_documento}', 8, 4, 1,
                            {fecha_sql}, 1, {total_items}, {total_items},
                            {moneda_operacion}, 1,
                            {total_bruto_sql}, 1, {rif_sql}, 1,
                            {total_bruto_sql}, 0, 0,
                            {base_imponible_sql}, 16, {iva_sql},
                            {total_neto_sql}, {proveedor_sql}, {ordenes_compra_sql},
                            {ordenes_compra_sql}, {hora_sql}, {fecha_sql}, {comentario_sql},
                            {fecha_venc_sql}
                        )
                    """)

                    # INSERT detalles SDETALLECOMPRA — ítems de orden de compra
                    linea = 0
                    for orden in request['ordenes']:
                        nro_oc_sql = quote_str(str(orden['orden']), max_len=20)
                        codigo_sql = quote_str(str(orden['codigo']), max_len=20)
                        cantidad = to_decimal(orden['recibido'], 'recibido')
                        costo = to_decimal(orden['costo'], 'costo')
                        iva_item = to_int(orden['iva'], 'iva')
                        impuesto_pct = 1 if iva_item == 16 else 0
                        monto_imp = to_decimal(orden['iva_16_monto'], 'iva_16_monto')
                        cursor.execute(f"""
                            INSERT INTO SDETALLECOMPRA (
                                FDI_DOCUMENTO, FDI_DOCUMENTOORIGEN, FDI_CLIENTEPROVEEDOR,
                                FDI_STATUS, FDI_MONEDA, FDI_VISIBLE, FDI_DEPOSITOSOURCE,
                                FDI_USADEPOSITOS, FDI_TIPOOPERACION, FDI_CODIGO,
                                FDI_CANTIDAD, FDI_CANTIDADPENDIENTE, FDI_COSTOOPERACION,
                                FDI_OPERACION_AUTOINCREMENT, FDI_LINEA, FDI_IMPUESTO1,
                                FDI_PORCENTIMPUESTO1, FDI_MONTOIMPUESTO1, FDI_PORCENTDESCPARCIAL,
                                FDI_DESCUENTOPARCIAL, FDI_PRECIOSINDESCUENTO, FDI_PRECIOCONDESCUENTO,
                                FDI_PRECIODEVENTA, FDI_UNDDESCARGA, FDI_UNDCAPACIDAD, FDI_FECHAOPERACION
                            ) VALUES (
                                '{nro_documento}', {nro_oc_sql}, {rif_sql},
                                4, {moneda_operacion}, 1, 1, 1, 8, {codigo_sql},
                                {cantidad}, {cantidad}, {costo},
                                LASTAUTOINC('SOPERACIONINV'), {linea}, {iva_item},
                                {impuesto_pct}, {monto_imp}, 0,
                                {costo}, {costo}, {costo}, {costo}, 1, 1, {fecha_sql}
                            )
                        """)
                        linea += 1

                    # INSERT detalles SDETALLECOMPRA — ítems sin orden de compra
                    for producto in request['productoSinOc']:
                        costo_sin_oc = to_decimal(
                            producto['costoBS'] if moneda_operacion == 1 else producto['costoUS'],
                            'costo'
                        )
                        codigo_sql = quote_str(str(producto['codigo']), max_len=20)
                        cant_sin_oc = to_decimal(producto['cantidad'], 'cantidad')
                        iva_sin_oc = to_int(producto['iva'], 'iva')
                        impuesto_pct_sin_oc = 1 if iva_sin_oc == 16 else 0
                        monto_imp_sin_oc = to_decimal(
                            round(float(costo_sin_oc) * 0.16, 4) if iva_sin_oc == 16 else 0,
                            'monto_impuesto'
                        )
                        cursor.execute(f"""
                            INSERT INTO SDETALLECOMPRA (
                                FDI_DOCUMENTO, FDI_DOCUMENTOORIGEN, FDI_CLIENTEPROVEEDOR,
                                FDI_STATUS, FDI_MONEDA, FDI_VISIBLE, FDI_DEPOSITOSOURCE,
                                FDI_USADEPOSITOS, FDI_TIPOOPERACION, FDI_CODIGO,
                                FDI_CANTIDAD, FDI_CANTIDADPENDIENTE, FDI_COSTOOPERACION,
                                FDI_OPERACION_AUTOINCREMENT, FDI_LINEA, FDI_IMPUESTO1,
                                FDI_PORCENTIMPUESTO1, FDI_MONTOIMPUESTO1, FDI_PORCENTDESCPARCIAL,
                                FDI_DESCUENTOPARCIAL, FDI_PRECIOSINDESCUENTO, FDI_PRECIOCONDESCUENTO,
                                FDI_PRECIODEVENTA, FDI_UNDDESCARGA, FDI_UNDCAPACIDAD, FDI_FECHAOPERACION
                            ) VALUES (
                                '{nro_documento}', '', {rif_sql},
                                4, {moneda_operacion}, 1, 1, 1, 8, {codigo_sql},
                                {cant_sin_oc}, {cant_sin_oc}, {costo_sin_oc},
                                LASTAUTOINC('SOPERACIONINV'), {linea}, {iva_sin_oc},
                                {impuesto_pct_sin_oc}, {monto_imp_sin_oc}, 0,
                                {costo_sin_oc}, {costo_sin_oc}, {costo_sin_oc}, {costo_sin_oc},
                                1, 1, {fecha_sql}
                            )
                        """)
                        linea += 1

                    # UPDATE stock en SINVDEP
                    for orden in request['ordenes']:
                        codigo_sql = quote_str(str(orden['codigo']), max_len=20)
                        deposito = to_int(orden['deposito'], 'deposito')
                        recibido = to_decimal(orden['recibido'], 'recibido')
                        diferencia = float(orden.get('diferencia', 0))
                        if diferencia <= 0:
                            cursor.execute(f"""
                                UPDATE SINVDEP SET FT_EXISTENCIA = COALESCE(FT_EXISTENCIA, 0) + {recibido}
                                WHERE FT_CODIGOPRODUCTO = {codigo_sql} AND FT_CODIGODEPOSITO = {deposito}
                            """)
                        else:
                            cantidad_ord = to_decimal(orden['cantidad'], 'cantidad')
                            diferencia_dec = to_decimal(diferencia, 'diferencia')
                            cursor.execute(f"""
                                UPDATE SINVDEP SET FT_EXISTENCIA = COALESCE(FT_EXISTENCIA, 0) + {cantidad_ord}
                                WHERE FT_CODIGOPRODUCTO = {codigo_sql} AND FT_CODIGODEPOSITO = {deposito}
                            """)
                            cursor.execute(f"""
                                UPDATE SINVDEP SET FT_EXISTENCIA = COALESCE(FT_EXISTENCIA, 0) + {diferencia_dec}
                                WHERE FT_CODIGOPRODUCTO = {codigo_sql} AND FT_CODIGODEPOSITO = {self.almacen_items_sin_oc}
                            """)

                    for producto in request['productoSinOc']:
                        codigo_sql = quote_str(str(producto['codigo']), max_len=20)
                        cant_sin_oc = to_decimal(producto['cantidad'], 'cantidad')
                        cursor.execute(f"""
                            UPDATE SINVDEP SET FT_EXISTENCIA = COALESCE(FT_EXISTENCIA, 0) + {cant_sin_oc}
                            WHERE FT_CODIGOPRODUCTO = {codigo_sql} AND FT_CODIGODEPOSITO = {self.almacen_items_sin_oc}
                        """)

                    # UPDATE cantidad pendiente en órdenes de compra originales
                    for orden in request['ordenes']:
                        nro_oc_sql = quote_str(str(orden['orden']), max_len=20)
                        codigo_sql = quote_str(str(orden['codigo']), max_len=20)
                        recibido = to_decimal(orden['recibido'], 'recibido')
                        cursor.execute(f"""
                            UPDATE SDETALLECOMPRA
                            SET FDI_CANTIDADPENDIENTE = CASE
                                WHEN FDI_CANTIDADPENDIENTE < {recibido} THEN 0
                                ELSE FDI_CANTIDADPENDIENTE - {recibido}
                            END
                            FROM SDETALLECOMPRA
                            WHERE FDI_DOCUMENTO = {nro_oc_sql}
                            AND FDI_CLIENTEPROVEEDOR = {rif_sql}
                            AND FDI_CODIGO = {codigo_sql}
                            AND FDI_TIPOOPERACION = 5
                        """)

                    # Cerrar OCs cuyas cantidades pendientes llegaron a cero
                    autoincrement_oc = set(to_int(oc['autoincrement'], 'autoincrement') for oc in request['ordenes'])
                    parse_autoinc = '(' + ','.join(map(str, autoincrement_oc)) + ')'
                    cursor.execute(f"""
                        UPDATE SOPERACIONINV
                        SET FTI_STATUS = 1
                        WHERE FTI_TIPO = 5 AND FTI_STATUS = 4
                        AND FTI_AUTOINCREMENT IN {parse_autoinc}
                        AND FTI_AUTOINCREMENT NOT IN (
                            SELECT FDI_OPERACION_AUTOINCREMENT
                            FROM SDETALLECOMPRA
                            WHERE FDI_OPERACION_AUTOINCREMENT IN {parse_autoinc}
                            AND FDI_TIPOOPERACION = 5 AND FDI_STATUS = 4 AND FDI_CANTIDADPENDIENTE <> 0
                        )
                    """)

                    cursor.execute("COMMIT;")
                    logger.info(
                        'nota_entrega insertada',
                        extra={
                            'nro_nota': nro_nota,
                            'rif': request.get('rif', ''),
                            'usuario': request.get('usuario', ''),
                            'total_neto': request.get('total_neto', ''),
                        }
                    )
                    return {'ok': True, 'nro_nota': nro_nota}

                except Exception as exc:
                    try:
                        cursor.execute("ROLLBACK;")
                    except Exception:
                        pass
                    logger.exception(
                        'rollback insert_notas_entrega',
                        extra={'rif': request.get('rif', ''), 'usuario': request.get('usuario', '')}
                    )
                    raise

    def consultar_notas_entrega(self, fecha_desde, fecha_hasta):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                                FTI_DOCUMENTO,
                                                FTI_TOTALITEMS,
                                                FTI_FECHAEMISION,
                                                FTI_RESPONSABLE,
                                                FP_DESCRIPCION,
                                                FTI_TOTALNETO,
                                                FTI_MONEDA
                                            FROM SOPERACIONINV
                                            LEFT JOIN SPROVEEDOR ON FTI_RESPONSABLE = FP_CODIGO
                                            WHERE FTI_TIPO = 8
                                            AND FTI_STATUS = 4
                                            AND FTI_FECHAEMISION BETWEEN {quote_date(fecha_desde)} AND {quote_date(fecha_hasta)}
                                            ORDER BY FTI_FECHAEMISION DESC, FTI_DOCUMENTO DESC
                                            """).fetchall()
                    return rows
        except Exception as e:
            raise e

    def update_table_tmp(self, name_table):
        conn = self.connect()
        cursor  =  conn.cursor()
        cursor.execute(f"""UPDATE "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" SET DESCRIPCION = FI_DESCRIPCION, DEPARTAMENTO = FD_DESCRIPCION, CODBARRA = FI_REFERENCIA, IVA = COALESCE(FIC_IMP01MONTO, 0.00)
                          FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}"
                          INNER JOIN "{self.catalog}\\SINVENTARIO" ON SKU = FI_CODIGO
                          INNER JOIN "{self.catalog}\\SCATEGORIA"  ON FI_CATEGORIA = FD_CODIGO
                          INNER JOIN "{self.catalog}\\A2INVCOSTOSPRECIOS" ON SKU = FIC_CODEITEM  """)
        
        conn.commit()
        conn.close()

    def get_table_tmp_count(self, name_table: str) -> int:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(f'SELECT COUNT(*) FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" ')
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_departamentos_tabla_tmp(self, name_table: str) -> list:
        """Devuelve los departamentos únicos presentes en la tabla temporal."""
        conn = self.connect()
        cursor = conn.cursor()
        rows = cursor.execute(
            f'SELECT DISTINCT DEPARTAMENTO FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" '
            f'WHERE DEPARTAMENTO IS NOT NULL ORDER BY DEPARTAMENTO'
        ).fetchall()
        conn.close()
        return [row[0] for row in rows if row[0]]

    def get_table_tmp_con_existencia(self, name_table, departamento: str = None):
        conn = self.connect()
        cursor = conn.cursor()
        where = 'WHERE EXISTENCIA > 0'
        if departamento:
            dept_sql = quote_str(departamento, max_len=40)
            where += f' AND DEPARTAMENTO = {dept_sql}'
        cursor.execute(f'SELECT * FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" {where} ORDER BY SKU')
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_table_tmp_sin_existencia(self, name_table, departamento: str = None):
        conn = self.connect()
        cursor = conn.cursor()
        where = ''
        if departamento:
            dept_sql = quote_str(departamento, max_len=40)
            where = f' WHERE DEPARTAMENTO = {dept_sql}'
        cursor.execute(f"""SELECT SKU,
                       IFNULL(CODBARRA THEN 'N/A' ELSE CODBARRA) AS CODBARRA,
                       IFNULL(DESCRIPCION THEN 'DESCRIPCION NO DISPONIBLE' ELSE DESCRIPCION) AS DESCRIPCION,
                       IFNULL(DESCRIPCION_OFERTA THEN 'DESCRIPCION NO DISPONIBLE' ELSE DESCRIPCION_OFERTA) AS DESCRIPCION_OFERTA,
                       FECHA_INICIO,
                       FECHA_FINAL,
                       IFNULL(DEPARTAMENTO THEN 'DESCRIPCION NO DISPONIBLE' ELSE DEPARTAMENTO) AS DEPARTAMENTO,
                       PRECIOANTES,
                       PRECIO,
                       EXISTENCIA,
                       ACTUALIZADO,
                       IFNULL(IVA THEN 16 ELSE IVA) AS IVA
                       FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}"{where} ORDER BY SKU""")
        rows = cursor.fetchall()
        conn.close()
        return rows

    def update_a2precios(self, name_table):
        conn = self.connect()
        cursor  =  conn.cursor()
        row_count = cursor.execute("""UPDATE A2INVCOSTOSPRECIOS SET FIC_P01PRECIOTOTALEXT = PRECIO
                          FROM A2INVCOSTOSPRECIOS
                          INNER JOIN "%s\\TMPDJANGO%s" ON SKU = FIC_CODEITEM 
                         WHERE FIC_CODEITEM NOT IN (SELECT FO_PRODUCTO FROM SINVOFERTA WHERE ('%s' BETWEEN FO_FECHAINICIO AND FO_FECHAFINAL) AND FO_VISIBLE = 1 ) """ 
                       % (self.tmp_table_tasks, name_table, datetime.now().strftime('%Y-%m-%d'))).rowcount
        print(f"Rows updated: {row_count}")
        conn.commit()
        return row_count
        
    def update_tabla_tmp_productos_actualizados(self, name_table, fecha_ejecucion=None):
        conn = self.connect()
        cursor  =  conn.cursor()
        cursor.execute(f"""UPDATE "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" SET ACTUALIZADO = TRUE
                            FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}"
                            LEFT OUTER JOIN SINVOFERTA ON SKU = FO_PRODUCTO
                           WHERE SKU NOT IN (SELECT FO_PRODUCTO FROM SINVOFERTA WHERE ('{datetime.now().strftime('%Y-%m-%d') if fecha_ejecucion is None else fecha_ejecucion }' BETWEEN FO_FECHAINICIO AND FO_FECHAFINAL) AND FO_VISIBLE = 1)""")
        conn.commit()
        duplicados = cursor.execute(f"""SELECT SKU FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" WHERE ACTUALIZADO = 0""").fetchall()
        conn.close()
        return duplicados


    def get_productos_actualizados(self, name_table):
        conn = self.connect()
        cursor  =  conn.cursor()
        productos = cursor.execute(f"""SELECT SKU FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" WHERE ACTUALIZADO = 1""").rowcount
        conn.close()
        return productos    

    def insert_into_sinvoferta(self, name_table, products: list[dict]):
        try:
            conn = self.connect()
            cursor  =  conn.cursor()
            products_chart ='(' +  ','.join(map(lambda x: f"'{x['sku']}'", products)) + ')'
            print(products_chart)
            row_count = cursor.execute(f"""INSERT INTO SINVOFERTA (FO_PRODUCTO, FO_DESCRIPCION, FO_PRECIODESC, FO_FECHAINICIO, FO_FECHAFINAL)
                                          SELECT SKU, DESCRIPCION_OFERTA, (PRECIOANTES - PRECIO) / PRECIOANTES * 100, FECHA_INICIO, FECHA_FINAL
                                          FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" WHERE ACTUALIZADO = 1""" ).rowcount
            print(f"Rows inserted into SINVOFERTA: {row_count}")
            if row_count > 0:
                cursor.execute(f"""UPDATE SINVOFERTA SET FO_TIPOOFERTA = 1, FO_TIPOROUND = 1, 
                                                               FO_UNDDESCARGA = 1, FO_HORAINICIO = '12:00:00', 
                                                               FO_INICIOPM = 0, FO_HORAFINAL = '11:59:00', 
                                                               FO_FINALPM = 1, FO_DIASSEMANAOFERTA = 2,
                                                               FO_TIPO = 8 , FO_VISIBLE = 1, 
                                                               FO_PORCENTCHAR = 1, FO_TIPOPRECIO = 0, 
                                                               FO_STATUS = 1
                                        WHERE FO_PRODUCTO IN {products_chart} """) 
            conn.commit()    
            #duplicados = cursor.execute(f"""SELECT SKU FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" WHERE ACTUALIZADO = 0""").fetchall()
            return row_count
                        
        except Exception as e:
            print(e)

    def update_table_existencia(self, name_table):
        conn = self.connect()
        cursor  =  conn.cursor()
        cursor.execute(f"""UPDATE "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" SET EXISTENCIA = COALESCE(FT_EXISTENCIA, 0.00)
                           FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}"
                           INNER JOIN "{self.catalog}\\SINVDEP" ON SKU = FT_CODIGOPRODUCTO
                           WHERE FT_CODIGODEPOSITO = 2 """ 
                     )
        conn.commit()
        conn.close()

    def get_skus_sin_inventario(self, name_table: str) -> list:
        """Retorna SKUs que no se encontraron en SINVENTARIO.

        Debe llamarse después de update_table_tmp, que completa DESCRIPCION
        sólo para los productos encontrados por INNER JOIN con SINVENTARIO.
        Los no encontrados quedan con DESCRIPCION NULL.
        """
        conn = self.connect()
        cursor = conn.cursor()
        rows = cursor.execute(
            f'SELECT SKU FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" WHERE DESCRIPCION IS NULL'
        ).fetchall()
        conn.close()
        return [row[0] for row in rows]

    def get_tabla_detalle(self, name_table: str) -> list:
        """Devuelve los items de la tabla temporal para el panel de detalle de lista."""
        conn = self.connect()
        cursor = conn.cursor()
        rows = cursor.execute(
            f'SELECT SKU, CODBARRA, DESCRIPCION, DEPARTAMENTO, PRECIOANTES, PRECIO, ACTUALIZADO, FECHA_INICIO, FECHA_FINAL '
            f'FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" ORDER BY SKU'
        ).fetchall()
        conn.close()
        return [
            {
                'sku': row[0] or '',
                'codbarra': row[1] or '',
                'descripcion': row[2] or 'Sin descripción',
                'departamento': row[3] or '',
                'precio_antes': float(row[4]) if row[4] is not None else None,
                'precio': float(row[5]) if row[5] is not None else None,
                'actualizado': bool(row[6]),
                'fecha_inicio': str(row[7]) if row[7] is not None else None,
                'fecha_final': str(row[8]) if row[8] is not None else None,
            }
            for row in rows
        ]

    def delete_table(self, name_table):
        conn = self.connect()
        cursor  =  conn.cursor()
        cursor.execute("""DROP TABLE IF EXISTS "%s\\TMPDJANGO%s" """
                        % (self.tmp_table_tasks, name_table))
        conn.commit()