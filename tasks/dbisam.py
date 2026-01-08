import pyodbc
from django.conf import settings
from datetime import datetime
from itertools import zip_longest
from uuid import uuid4
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
        order_numbers = order_number[0] #'(' +  ','.join(map(lambda x: f"'{x}'", order_number)) + ')'
        name_table_temp = f'TEMP_TABLE_ORDENES_{uuid4().hex.upper()}'
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT 
                                            FDI_CODIGO, 
                                            FDI_CANTIDADPENDIENTE, 
                                            FDI_DOCUMENTO,
                                            FDI_COSTOOPERACION,
                                            FDI_IMPUESTO1,
                                            FDI_MONEDA,
                                            FDI_DEPOSITOSOURCE,
                                            FI_DESCRIPCION,
                                            FTI_AUTOINCREMENT     
                                        --INTO "{self.tmp_table_tasks}\\{name_table_temp}"
                                        FROM SOPERACIONINV 
                                        INNER JOIN SDETALLECOMPRA ON FTI_AUTOINCREMENT = FDI_OPERACION_AUTOINCREMENT
                                        INNER JOIN SINVENTARIO ON FDI_CODIGO = FI_CODIGO
                                        WHERE FDI_CLIENTEPROVEEDOR = '{proveedor}' AND FDI_DOCUMENTO = '{order_numbers}' AND FDI_STATUS = 4
                                        AND FDI_CANTIDADPENDIENTE > 0 AND FTI_TIPO = 5;
                                        --INDICE PARA EL CAMPO FDI_CODIGO
                                        --CREATE INDEX IF NOT EXISTS "INDEX_CODIGO" ON "{self.tmp_table_tasks}\\{name_table_temp}" (FDI_CODIGO);
                                        --SELECCION DE LOS DATOS""").fetchall()
                    # rows = cursor.execute(f"""SELECT
                    #                          FDI_CODIGO,
                    #                          FDI_CANTIDADPENDIENTE,
                    #                          FDI_DOCUMENTO,
                    #                          FDI_COSTOOPERACION,
                    #                          FDI_IMPUESTO1,   
                    #                          FDI_MONEDA,
                    #                          FDI_DEPOSITOSOURCE,
                    #                          FI_DESCRIPCION
                    #                     FROM "{self.tmp_table_tasks}\\{name_table_temp}"
                    #                     INNER JOIN SINVENTARIO ON FDI_CODIGO = FI_CODIGO""").fetchall()
                    print("Filas Recuperadas en la consulta: ", rows)
                    #cursor.execute(f"""DROP TABLE IF EXISTS "{self.tmp_table_tasks}\\{name_table_temp}" """)
                    return rows
        except Exception as e:
            print(e)
            raise pyodbc.DatabaseError(e)        
        
    def search_proveedor(self, codigo_proveedor):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT 
                                                FP_CODIGO,
                                                FP_DESCRIPCION
                                          FROM SPROVEEDOR
                                          WHERE FP_CODIGO = '{codigo_proveedor}' and FP_STATUS = 1
                                    """).fetchone()
                return rows
        except  Exception as e:
            return str(e)            
    def search_product(self, sku):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    row = cursor.execute(f"""SELECT 
                                                FI_CODIGO, 
                                                FI_DESCRIPCION, FIC_COSTOACTBOLIVARES, FIC_COSTOACTEXTRANJERO, FIC_IMP01MONTO
                                        FROM SINVENTARIO
                                        INNER JOIN A2INVCOSTOSPRECIOS ON FI_CODIGO = FIC_CODEITEM  
                                        WHERE FI_REFERENCIA = '{sku}' OR FI_CODIGO = '{sku}' """).fetchone()
                    return row
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))
         
    def search_product_by_description(self, description):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    row = cursor.execute(f"""SELECT 
                                     FI_CODIGO, 
                                     FI_DESCRIPCION, 
                                     FI_CATEGORIA,
                                     FIC_COSTOACTBOLIVARES, FIC_COSTOACTEXTRANJERO, FIC_IMP01MONTO 
                                     FROM SINVENTARIO
                                     INNER JOIN A2INVCOSTOSPRECIOS ON FI_CODIGO = FIC_CODEITEM  
                                     WHERE FI_DESCRIPCION LIKE '%{description}%' """).fetchmany(200)
                    return row 
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))                   

    def create_table_tmp(self, name_table):
        conn = self.connect()
        cursor = conn.cursor()
        print(name_table)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" ("SKU" VARCHAR(50), "CODBARRA" VARCHAR(50),"DESCRIPCION" VARCHAR(150),
                    "DESCRIPCION_OFERTA" VARCHAR(150),
                    "FECHA_INICIO" DATE, 
                    "FECHA_FINAL" DATE,
                    "DEPARTAMENTO" VARCHAR(40),
                    "PRECIOANTES" FLOAT, 
                    "PRECIO" FLOAT, 
                    "EXISTENCIA" FLOAT DEFAULT 0.00,
                    "ACTUALIZADO" BOOLEAN DEFAULT FALSE);
            CREATE INDEX IF NOT EXISTS "INDEX_SKU" ON "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" (SKU);           
        """)
        print(f"Tabla temporal {self.tmp_table_tasks}\\TMPDJANGO{name_table} creada.")

    def insert_data_tmp(self, data: dict):
        conn = self.connect()
        cursor  =  conn.cursor()
        cursor.execute(f"""INSERT INTO "{self.tmp_table_tasks}\\TMPDJANGO{data['Tabla']}" (SKU, FECHA_INICIO, FECHA_FINAL, PRECIO, PRECIOANTES, DESCRIPCION_OFERTA) 
                       VALUES ('{data['Sku']}', '{data['FechaInicio']}','{data['FechaFinal']}', {data['Precio']}, {data['PrecioAntes']}, '{data['Descripcion_Oferta']}')""" 
                     )
        conn.commit()
        conn.close()
    
    def notas_entrega_correlativo(self):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    row = cursor.execute("""SELECT NO_NOTAENTREGAPROV FROM SSISTEMA WHERE DUMMYKEY='' """).fetchone()
                    return row.NO_NOTAENTREGAPROV
        except Exception as e:
            print(e)
            return e

    def insert_notas_entrega(self, request: dict, nro_nota: int):
        try:
           with self.connect() as conn:
                with conn.cursor() as cursor:
                    detalle_query = []
                    nro_documento = str(nro_nota).rjust(8,'0')
                    linea = 0
                    moneda_operacion = 1
                    ordenes_compra = []
                    total_items = len(request['ordenes']) + len(request['productoSinOc'])
                    for ordenes, productos_sin_ordenes in zip_longest(request['ordenes'], request['productoSinOc'], fillvalue=None):
                        #moneda = ordenes['moneda']
                        if ordenes is not None:
                            nro_oc = ordenes['orden']
                            codigo = ordenes['codigo']
                            cantidad = ordenes['cantidad']
                            moneda_operacion = ordenes['moneda']
                            costo = ordenes['costo']
                            iva = ordenes['iva']
                            
                            fecha = datetime.now().strftime("%Y-%m-%d")
                            impuesto_porcentaje = 1 if iva == 16 else 0
                            monto_impuesto = round(costo * 0.16, 2) if iva == 16 else 0

                            sql = """
                                    INSERT INTO SDETALLECOMPRA (
                                        FDI_DOCUMENTO,
                                        FDI_DOCUMENTOORIGEN,
                                        FDI_CLIENTEPROVEEDOR,
                                        FDI_STATUS,
                                        FDI_MONEDA,
                                        FDI_VISIBLE,
                                        FDI_DEPOSITOSOURCE,
                                        FDI_USADEPOSITOS,
                                        FDI_TIPOOPERACION,
                                        FDI_CODIGO,
                                        FDI_CANTIDAD,
                                        FDI_CANTIDADPENDIENTE,
                                        FDI_COSTOOPERACION,
                                        FDI_OPERACION_AUTOINCREMENT,
                                        FDI_LINEA,
                                        FDI_IMPUESTO1,
                                        FDI_PORCENTIMPUESTO1,
                                        FDI_MONTOIMPUESTO1,
                                        FDI_PORCENTDESCPARCIAL,
                                        FDI_DESCUENTOPARCIAL,
                                        FDI_PRECIOSINDESCUENTO,
                                        FDI_PRECIOCONDESCUENTO,
                                        FDI_PRECIODEVENTA,
                                        FDI_UNDDESCARGA,
                                        FDI_UNDCAPACIDAD,
                                        FDI_FECHAOPERACION
                                    ) VALUES (
                                        '{nro_nota}',
                                        '{orden_id}',
                                        '{rif}',
                                        4,
                                        {moneda},
                                        1,
                                        1,
                                        1,
                                        8,
                                        '{codigo}',
                                        {cantidad},
                                        {cantidad},
                                        {costo},
                                        LASTAUTOINC('SOPERACIONINV'),
                                        {linea},
                                        {iva},
                                        {impuesto_porcentaje},
                                        {monto_impuesto},
                                        0,
                                        {costo},
                                        {costo},
                                        {costo},
                                        {costo},
                                        1,
                                        1,
                                        '{fecha}'
                                    );
                                    """.format(
                                        orden_id=nro_oc,
                                        rif=request['rif'],
                                        moneda=moneda_operacion,
                                        codigo=codigo,
                                        cantidad=cantidad,
                                        costo=costo,
                                        linea=linea,
                                        iva=iva,
                                        impuesto_porcentaje=impuesto_porcentaje,
                                        monto_impuesto=monto_impuesto,
                                        fecha=fecha,
                                        nro_nota=nro_documento
                                    )
                            linea +=1
                            detalle_query.append(sql)
                        if productos_sin_ordenes is not None:
                            iva = productos_sin_ordenes['iva']
                            costo = productos_sin_ordenes['costoBS'] if moneda_operacion == 1 else productos_sin_ordenes['costoUS']
                            fecha = datetime.now().strftime("%Y-%m-%d")
                            impuesto_porcentaje = 1 if iva == 16 else 0
                            monto_impuesto = round(costo * 0.16, 2) if iva == 16 else 0
                            sql_productos_sin_oc = """
                                    INSERT INTO SDETALLECOMPRA (
                                        FDI_DOCUMENTO,
                                        FDI_DOCUMENTOORIGEN,
                                        FDI_CLIENTEPROVEEDOR,
                                        FDI_STATUS,
                                        FDI_MONEDA,
                                        FDI_VISIBLE,
                                        FDI_DEPOSITOSOURCE,
                                        FDI_USADEPOSITOS,
                                        FDI_TIPOOPERACION,
                                        FDI_CODIGO,
                                        FDI_CANTIDAD,
                                        FDI_CANTIDADPENDIENTE,
                                        FDI_COSTOOPERACION,
                                        FDI_OPERACION_AUTOINCREMENT,
                                        FDI_LINEA,
                                        FDI_IMPUESTO1,
                                        FDI_PORCENTIMPUESTO1,
                                        FDI_MONTOIMPUESTO1,
                                        FDI_PORCENTDESCPARCIAL,
                                        FDI_DESCUENTOPARCIAL,
                                        FDI_PRECIOSINDESCUENTO,
                                        FDI_PRECIOCONDESCUENTO,
                                        FDI_PRECIODEVENTA,
                                        FDI_UNDDESCARGA,
                                        FDI_UNDCAPACIDAD,
                                        FDI_FECHAOPERACION
                                    )VALUES (
                                        '{nro_nota}',
                                        '{orden_id}',
                                        '{rif}',
                                        4,
                                        {moneda},
                                        1,
                                        1,
                                        1,
                                        8,
                                        '{codigo}',
                                        {cantidad},
                                        {cantidad},
                                        {costo},
                                        LASTAUTOINC('SOPERACIONINV'),
                                        {linea},
                                        {iva},
                                        {impuesto_porcentaje},
                                        {monto_impuesto},
                                        0,
                                        {costo},
                                        {costo},
                                        {costo},
                                        {costo},
                                        1,
                                        1,
                                        '{fecha}'
                                    );""".format(
                                        orden_id="",
                                        rif=request['rif'],
                                        moneda=moneda_operacion,
                                        codigo=productos_sin_ordenes['codigo'],
                                        cantidad = productos_sin_ordenes['cantidad'],
                                        linea=linea,
                                        iva=iva,
                                        impuesto_porcentaje = impuesto_porcentaje,
                                        monto_impuesto = monto_impuesto,
                                        costo = costo,
                                        fecha= fecha,
                                        nro_nota=nro_documento)
                            detalle_query.append(sql_productos_sin_oc)
                            linea += 1
                update_depositos = [
                                    (f"UPDATE SINVDEP SET FT_EXISTENCIA = FT_EXISTENCIA + {orden['recibido']} WHERE FT_CODIGOPRODUCTO = '{orden['codigo']}' AND FT_CODIGODEPOSITO = {orden['deposito']};"
                                    if orden['diferencia'] <= 0 
                                    else f"""UPDATE SINVDEP SET FT_EXISTENCIA = FT_EXISTENCIA + {orden['cantidad']} WHERE FT_CODIGOPRODUCTO = '{orden['codigo']}' AND FT_CODIGODEPOSITO = {orden['deposito']};
                                            UPDATE SINVDEP SET FT_EXISTENCIA = FT_EXISTENCIA + {orden['diferencia']} WHERE FT_CODIGOPRODUCTO = '{orden['codigo']}' AND FT_CODIGODEPOSITO = {self.almacen_items_sin_oc};""" )
                                        for orden in request['ordenes'] ]
                update_depositos_productos_sin_oc = [(f"UPDATE SINVDEP SET FT_EXISTENCIA = FT_EXISTENCIA + {products['cantidad']}WHERE FT_CODIGOPRODUCTO = '{products['codigo']}' AND FT_CODIGODEPOSITO = {self.almacen_items_sin_oc};") 
                                                     for products in request['productoSinOc']]
                
                query_update_depositos = "\n".join(update_depositos) 
                query_update_depositos_sin_oc = "\n".join(update_depositos_productos_sin_oc) 
                update_orden_compra = [f"""UPDATE SDETALLECOMPRA 
                                            SET FDI_CANTIDADPENDIENTE =
                                                CASE WHEN FDI_CANTIDADPENDIENTE < {orden['recibido']} THEN 0
                                                     ELSE FDI_CANTIDADPENDIENTE - {orden['recibido']}   
                                            END
                                            FROM SDETALLECOMPRA
                                            WHERE FDI_DOCUMENTO = '{orden['orden']}' 
                                            AND FDI_CLIENTEPROVEEDOR = '{request['rif']}' 
                                            AND FDI_CODIGO = '{orden['codigo']}'
                                            AND FDI_TIPOOPERACION = 5 \n"""
                                       for orden in request['ordenes']]
                total_sin_oc ={1:sum(map(lambda x: float(x['costoBS']), request['productoSinOc'])), 
                                 2:sum(map(lambda x: float(x['costoUS']), request['productoSinOc']))} 
                print(total_sin_oc, moneda_operacion)
                total_neto = sum(map(lambda x: float(x['costo']), request['ordenes'])) + total_sin_oc[int(moneda_operacion)]
                query = f"""
                                          ---INICIO DE LA TRANSACCION---
                                          START TRANSACTION;
                                          ---INSERCION NOTA DE ENTREGA---
                                          INSERT INTO SOPERACIONINV 
                                                (FTI_DOCUMENTO,
                                                FTI_TIPO,
                                                FTI_STATUS,
                                                FTI_VISIBLE,
                                                FTI_FECHAEMISION,
                                                FTI_DEPOSITOSOURCE,
                                                FTI_TOTALITEMS,
                                                FTI_TOTALITEMSINICIAL,
                                                FTI_MONEDA,
                                                FTI_FACTORCAMBIO,
                                                FTI_TOTALCOSTO,
                                                FTI_USER,
                                                FTI_RESPONSABLE,
                                                FTI_UPDATEITEMS,
                                                FTI_TOTALBRUTO,
                                                FTI_DESCUENTO1PORCENT,
                                                FTI_DESCUENTO1MONTO,
                                                FTI_BASEIMPONIBLE,
                                                FTI_IMPUESTO1PORCENT,
                                                FTI_IMPUESTO1MONTO,
                                                FTI_TOTALNETO,
                                                FTI_PERSONACONTACTO,
                                                FTI_ORDENCOMPRA,
                                                FTI_DOCUMENTOORIGEN,
                                                FTI_HORA,
                                                FTI_FECHALIBRO)
                                      VALUES('{nro_documento}',
                                              8,
                                              4,
                                              1,
                                              '{datetime.now().strftime("%Y-%m-%d")}',
                                              1,
                                              {total_items},
                                              {total_items},
                                              {moneda_operacion},
                                              1,
                                              {total_neto},
                                              1,
                                              '{request['rif']}',
                                              1,
                                              {total_neto},
                                              0,
                                              0,
                                              {total_neto},
                                              16,
                                              0,
                                              {total_neto},
                                              '{request['proveedor']}',
                                              '{''.join(ordenes_compra)}',
                                              '{''.join(ordenes_compra)}',
                                              '{datetime.now().strftime("%I:%M:%S %p")}',
                                              '{datetime.now().strftime("%Y-%m-%d")}');                                     
                                      {''.join(detalle_query)}
                                      {''.join(query_update_depositos)}
                                      {''.join(query_update_depositos_sin_oc)}  
                                    {';'.join(update_orden_compra)}
                                    """
                #print(query)
                rows = cursor.execute(query)
                cursor.execute(f"""UPDATE SSISTEMA SET NO_NOTAENTREGAPROV = {nro_nota} + 1 WHERE DUMMYKEY = '' """)
                autoincrement_oc = set(oc['autoincrement'] for oc in request['ordenes']) 
                parse_autoinc = '(' +  ','.join(map(lambda x: str(x), autoincrement_oc)) + ')'
                cursor.execute(f"""UPDATE SOPERACIONINV
                                        SET FTI_STATUS = 1
                                    WHERE FTI_TIPO = 5
                                    AND FTI_STATUS = 4
                                    AND FTI_AUTOINCREMENT IN {parse_autoinc}
                                    AND FTI_AUTOINCREMENT NOT IN(
                                            SELECT FDI_OPERACION_AUTOINCREMENT
                                            FROM SDETALLECOMPRA
                                            WHERE FDI_OPERACION_AUTOINCREMENT IN {parse_autoinc}
                                            AND FDI_TIPOOPERACION = 5 AND FDI_STATUS = 4 AND FDI_CANTIDADPENDIENTE <> 0
                                            )""")
                cursor.execute("COMMIT;")
                return rows
        except Exception as e:
            print(e)
            return e    

    def update_table_tmp(self, name_table):
        conn = self.connect()
        cursor  =  conn.cursor()
        cursor.execute(f"""UPDATE "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" SET DESCRIPCION = FI_DESCRIPCION, DEPARTAMENTO = FD_DESCRIPCION, CODBARRA = FI_REFERENCIA
                          FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}"
                          INNER JOIN "{self.catalog}\\SINVENTARIO" ON SKU = FI_CODIGO
                          INNER JOIN "{self.catalog}\\SCATEGORIA"  ON FI_CATEGORIA = FD_CODIGO""")
        
        conn.commit()
        conn.close()

    def get_table_tmp_con_existencia(self, name_table):
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" WHERE ACTUALIZADO = 1 AND EXISTENCIA > 0')
        rows = cursor.fetchall()
        conn.close()
        return rows
    
    def get_table_tmp_sin_existencia(self, name_table):
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM "{self.tmp_table_tasks}\\TMPDJANGO{name_table}" WHERE ACTUALIZADO = 1')
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

    def delete_table(self, name_table):
        conn = self.connect()
        cursor  =  conn.cursor()
        cursor.execute("""DROP TABLE IF EXISTS "%s\\TMPDJANGO%s" """ 
                        % (self.tmp_table_tasks, name_table))
        conn.commit()