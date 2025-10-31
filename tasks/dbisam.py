import pyodbc
from django.conf import settings
from datetime import datetime


class DBISAMDatabase:
    def __init__(self):
        self.dsn = settings.DBISAM_DATABASE['DSN']
        self.catalog = settings.DBISAM_DATABASE['CatalogName']
        self.tmp_table_tasks = settings.DBISAM_DATABASE['TMP_TABLE_TASKS']
        

    def connect(self):
        return pyodbc.connect(f'DSN={self.dsn};CatalogName={self.catalog}')
    

    def search_order(self, order_number, proveedor):
        order_numbers ='(' +  ','.join(map(lambda x: f"'{x}'", order_number)) + ')'
        print(order_numbers)
        with self.connect() as conn:
            with conn.cursor() as cursor:
                rows = cursor.execute(f"""SELECT 
                                            FDI_CODIGO, 
                                            FDI_CANTIDADPENDIENTE, 
                                            FDI_DOCUMENTO,
                                            FDI_COSTOOPERACION,
                                            FDI_IMPUESTO1,
                                            FDI_MONEDA,
                                            FDI_DEPOSITOSOURCE    
                                         
                                        FROM SOPERACIONINV 
                                        INNER JOIN SDETALLECOMPRA ON FTI_AUTOINCREMENT = FDI_OPERACION_AUTOINCREMENT
                                        WHERE FDI_DOCUMENTO IN {order_numbers} AND FDI_CANTIDADPENDIENTE > 0 AND FDI_CLIENTEPROVEEDOR = '{proveedor}'
                                        AND FTI_TIPO = 5 AND FDI_STATUS = 4
                                    """).fetchall()
                print(rows)
                return rows
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
        with self.connect() as conn:
            with conn.cursor() as cursor:
                row = cursor.execute(f"SELECT FI_CODIGO, FI_DESCRIPCION, FI_CATEGORIA FROM SINVENTARIO WHERE FI_REFERENCIA = '{sku}' OR FI_CODIGO = '{sku}' ").fetchone()
                return row
    def search_product_by_description(self, description):
        with self.connect() as conn:
            with conn.cursor() as cursor:
                row = cursor.execute(f"SELECT FI_CODIGO, FI_DESCRIPCION, FI_CATEGORIA FROM SINVENTARIO WHERE FI_DESCRIPCION LIKE '%{description}%' ").fetchmany(200)
                return row            

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
    
    def insert_notas_entrega(self, request: dict):
        try:
           with self.connect() as conn:
                with conn.cursor() as cursor:
                    detalle_query = []
                    linea = 0
                    moneda_operacion = 0
                    ordenes_compra = []
                    for ordenes in request['ordenes']:
                        if ordenes['orden'] not in ordenes_compra:
                            ordenes_compra.append(ordenes['orden'])
                        moneda_operacion = ordenes['moneda']
                        detalle_query.append(f""" INSERT INTO SDETALLECOMPRA
                                             (FDI_DOCUMENTO,
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
                                                        )
                                             VALUES('TEST-NOTA',
                                                    '{ordenes['orden']}',
                                                    '{request['rif']}',
                                                    4,
                                                    {ordenes['moneda']},
                                                    1,
                                                    1,
                                                    1,
                                                    8, 
                                                    '{ordenes['codigo']}', 
                                                    {ordenes['cantidad']},
                                                    {ordenes['cantidad']}, 
                                                    {ordenes['costo']}, 
                                                    LASTAUTOINC('SOPERACIONINV'), 
                                                    {linea},
                                                    {ordenes['iva']},
                                                    {1 if ordenes['iva'] == 16 else 0},
                                                    {round(ordenes['costo'] * .16, 2) if ordenes['iva'] == 16 else 0},
                                                    0,
                                                    {ordenes['costo']},
                                                    {ordenes['costo']},
                                                    {ordenes['costo']},
                                                    {ordenes['costo']},
                                                    1,
                                                    1,
                                                    '{datetime.now().strftime('%Y-%m-%d')}');
                                                    """)
                        linea += 1
                update_depositos = [
                                    (f"UPDATE SINVDEP SET FT_EXISTENCIA = FT_EXISTENCIA + {orden['recibido']} WHERE FT_CODIGOPRODUCTO = '{orden['codigo']}' AND FT_CODIGODEPOSITO = {orden['deposito']}"
                                    if orden['diferencia'] <=0 
                                    else f"""UPDATE SINVDEP SET FT_EXISTENCIA = FT_EXISTENCIA + {orden['cantidad']} WHERE FT_CODIGOPRODUCTO = '{orden['codigo']}' AND FT_CODIGODEPOSITO = {orden['deposito']}; 
                                            UPDATE SINVDEP SET FT_EXISTENCIA = FT_EXISTENCIA + {orden['diferencia']} WHERE FT_CODIGOPRODUCTO = '{orden['codigo']}' AND FT_CODIGODEPOSITO = 2""" )
                                        for orden in request['ordenes'] ]
                query_update_depositos = ";\n".join(update_depositos)  + ';' 

                update_orden_compra = [f"""UPDATE SDETALLECOMPRA 
                                            SET FDI_CANTIDADPENDIENTE =
                                                CASE WHEN FDI_CANTIDADPENDIENTE < {orden['recibido']} THEN 0
                                                     ELSE FDI_CANTIDADPENDIENTE - {orden['recibido']}   
                                            END
                                            FROM SDETALLECOMPRA
                                            WHERE FDI_DOCUMENTO = '{orden['orden']}' 
                                            AND FDI_CLIENTEPROVEEDOR = '{request['rif']}' 
                                            AND FDI_CODIGO = '{orden['codigo']}'
                                            AND FDI_TIPOOPERACION = 5"""
                                       for orden in request['ordenes']] 
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
                                      VALUES('TEST-NOTA',
                                              8,
                                              4,
                                              1,
                                              '{datetime.now().strftime("%Y-%m-%d")}',
                                              1,
                                              2,
                                              2,
                                              {moneda_operacion},
                                              1,
                                              {sum(map(lambda x: float(x['costo']), request['ordenes']))},
                                              1,
                                              '{request['rif']}',
                                              1,
                                              {sum(map(lambda x: float(x['costo']), request['ordenes']))},
                                              0,
                                              0,
                                              {sum(map(lambda x: float(x['costo']), request['ordenes']))},
                                              16,
                                              0,
                                              {sum(map(lambda x: float(x['costo']), request['ordenes']))},
                                              '{request['proveedor']}',
                                              '{''.join(ordenes_compra)}',
                                              '{''.join(ordenes_compra)}',
                                              '{datetime.now().strftime("%I:%M:%S %p")}',
                                              '{datetime.now().strftime("%Y-%m-%d")}');                                     
                                      {''.join(detalle_query)}
                                      {''.join(query_update_depositos)}
                                    {';'.join(update_orden_compra)}
                                    """
                print(query)
                rows = cursor.execute(query)
                cursor.execute("COMMIT;")
                return rows
        except Exception as e:
            print(e)
            return str(e)    

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