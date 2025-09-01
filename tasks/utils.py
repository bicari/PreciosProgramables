import pandas as pd
from .dbisam import DBISAMDatabase
import win32print
from .labels import PrinterLabel
from django.conf import settings
import os
from .models import ProductsTasks, Tasks
from datetime import datetime, time
import openpyxl
from openpyxl.styles import Font, PatternFill            


def read_excel_file(form, file, name_table, user, inmediato=False, is_oferta=False):
    try:
        with pd.ExcelFile(file) as excel_file:
            df = pd.read_excel(excel_file, header= form.cleaned_data['header'] - 1, dtype={'SKU': str})
            if df.empty:
                return ValueError("El archivo está vacio o no contiene datos válidos.")
            df = df.dropna(how='all')
            dbisam_db = DBISAMDatabase()
            dbisam_db.create_table_tmp(name_table)
            fecha_ejecucion=datetime.combine(form.cleaned_data['date_time'], time.fromisoformat(settings.HORA_EJECUCION) )  #datetime.strptime(request.POST['date_time'], "%Y-%m-%d")
            list_products = []
            list_products_exists = []
            fecha_oferta = None
            #print('Fecha de ejecucion', fecha_ejecucion)
            for fila in df.itertuples():
                if not isinstance(fila.SKU, str) or not isinstance(fila.PRECIO, (int, float)):
                    return ValueError("El archivo debe contener datos válidos, los datos del producto %s en la linea %s" %(fila.SKU , fila.Index + form.cleaned_data['header']))
                
                if ProductsTasks.objects.filter(sku=fila.SKU, fecha_ejecucion=form.cleaned_data['date_time']).exists():
                        list_products_exists.append(fila.SKU)
                else:
                    fecha_oferta = fila.DESDE.strftime("%Y-%m-%d") if hasattr(fila, 'DESDE') else None
                    dbisam_db.insert_data_tmp({'Sku':fila.SKU, 
                                               'FechaInicio': fila.DESDE.strftime("%Y-%m-%d") if hasattr(fila, 'DESDE') else '1991-02-01',
                                               'FechaFinal': fila.HASTA.strftime("%Y-%m-%d") if hasattr(fila, 'HASTA') else '1991-02-01',
                                               'Precio':fila.PRECIO, 
                                               'PrecioAntes':fila.PRECIOANTES if hasattr(fila, 'PRECIOANTES') else fila.PRECIO - 2, 
                                               'Descripcion_Oferta': fila.DESCRIPCION if hasattr(fila, 'DESCRIPCION') else 'NO ES OFERTA',
                                               'Tabla':name_table})
                            
                    list_products.append(
                        dict(sku=fila.SKU, fecha_ejecucion=fecha_ejecucion,
                            is_oferta=is_oferta)
                                    )

                #if process:
                #    filas_validas.append(fila)
        
        if len(list_products) > 0:
            if not inmediato:
                if not is_oferta:
                    dbisam_db.update_table_tmp(name_table)
                
                    duplicados=dbisam_db.update_tabla_tmp_productos_actualizados(name_table, fecha_ejecucion=form.cleaned_data['date_time'])
                    row_count=dbisam_db.get_productos_actualizados(name_table)
                    list_products_exists.extend(duplicados)
                else:
                    dbisam_db.update_table_tmp(name_table)
                    duplicados=dbisam_db.update_tabla_tmp_productos_actualizados(name_table, fecha_ejecucion=fecha_oferta)
                    row_count=dbisam_db.get_productos_actualizados(name_table)
                    list_products_exists.extend(duplicados)
            else:
                
                dbisam_db.update_table_tmp(name_table)
                if not is_oferta:
                    row_count = dbisam_db.update_a2precios(name_table)
                    duplicados = dbisam_db.update_tabla_tmp_productos_actualizados(name_table)
                    list_products_exists.extend(duplicados)
                else:
                    duplicados=dbisam_db.update_tabla_tmp_productos_actualizados(name_table, fecha_ejecucion=fecha_oferta)
                    row_count = dbisam_db.insert_into_sinvoferta(name_table, list_products)  
                    list_products_exists.extend(duplicados)
            resaltar_sku_actualizados(file, list_products, header_row=form.cleaned_data['header'])
            return list_products, list_products_exists, row_count #filas_validas if process else len(df)
        else:
            dbisam_db.delete_table(name_table)
            return ValueError("Todos los productos encontrados en el archivo están asignados a una lista pendiente. Los siguientes SKU ya existen: %s" % ', '.join(list_products_exists))
    except Exception as e:  
        print(e)      
        return ValueError("Error al leer el archivo: {}".format(e))

   
def print_labels(row, request):
    hPrinter=win32print.OpenPrinter(request.POST['so_printers'], {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
    static_path = os.path.join(settings.BASE_DIR, 'static', '%s.jpg' %request.POST['logo_etiquetas'])            
    etiquetas_impresas = 0    
    for producto in row: 
        match request.POST['formato_label']:
            case 'Ofertas':
                text=PrinterLabel.label_ofertas_ksa({'Logo': f"{static_path}", "SKU":f"{producto.SKU}",  
                                           "Descripcion":f"{producto.DESCRIPCION}",
                                           "PrecioAntes": f"{str(producto.PRECIOANTES)}", 
                                           "DescuentoPorcentaje": f"{str(round((producto.PRECIOANTES - producto.PRECIO) / producto.PRECIOANTES * 100, 2))}",
                                           "Precio": f"{str(producto.PRECIO)}",
                                           'Departamento':f"{producto.DEPARTAMENTO}"})
            case 'Hablador':
                text=PrinterLabel.label_hablador({'Logo': f"{static_path}", "SKU":f"{producto.SKU}",  
                                           "Descripcion":f"{producto.DESCRIPCION}",
                                           "PrecioAntes": f"{str(producto.PRECIOANTES)}", 
                                           "CodBarra": f"{producto.CODBARRA}",
                                           "Precio": f"{{:.2f}}".format(producto.PRECIO),
                                           'Departamento':f"{producto.DEPARTAMENTO}"})
    
        win32print.StartDocPrinter(hPrinter, 1, ('1',None,'RAW'))
        win32print.WritePrinter(hPrinter, text)
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
        etiquetas_impresas += 1
    return etiquetas_impresas


def resaltar_sku_actualizados(excel_path, lista_skus_actualizados, header_row, sku_col_name='SKU'):
    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active
    sku_col_idx = None
    for idx, cell in enumerate(ws[header_row]):
        if str(cell.value).strip().upper() == sku_col_name.strip().upper():
            sku_col_idx = idx
            break

    if sku_col_idx is None:
        print(f"No se encontró la columna '{sku_col_name}' en el encabezado.")
        wb.close()
        return

    green_fill = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
    green_font = Font(color='006100')
    lista_productos = [producto['sku'] for producto in lista_skus_actualizados]
    # Iterar sobre las filas debajo del encabezado
    for row in ws.iter_rows(min_row=header_row + 1):  # +2 porque openpyxl es 1-based y header_row es 0-based
        sku_cell = row[sku_col_idx]
        print(lista_skus_actualizados)
        if str(sku_cell.value) in lista_productos:
            sku_cell.fill = green_fill
            sku_cell.font = green_font

    wb.save(excel_path)
    wb.close()