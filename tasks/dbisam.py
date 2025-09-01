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