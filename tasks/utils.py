import pandas as pd
from .dbisam import DBISAMDatabase
import win32print
from .labels import PrinterLabel
from django.conf import settings
import os
from .models import ProductsTasks, Tasks
from datetime import datetime, time, date
            


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
            print('Fecha de ejecucion', fecha_ejecucion)
            for fila in df.itertuples():
                if not isinstance(fila.SKU, str) or not isinstance(fila.PRECIO, (int, float)):
                    return ValueError("El archivo debe contener datos válidos, los datos del producto %s en la linea %s" %(fila.SKU , fila.Index + form.cleaned_data['header']))
                
                if ProductsTasks.objects.filter(sku=fila.SKU, fecha_ejecucion=form.cleaned_data['date_time']).exists():
                        list_products_exists.append(fila.SKU)
                else:
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
                dbisam_db.update_table_tmp(name_table)
                task = Tasks.objects.create(
                    user_id = user,
                    #rif_proveedor = form.cleaned_data['rif_proveedor'],
                    file = form.cleaned_data['file'],
                    date_to_execute = fecha_ejecucion,
                    header_file = form.cleaned_data['header'],
                    dbisam_table = name_table,  # Assuming filas is the name of the table created in DBISAM
                    is_oferta = is_oferta
                    )
                #if is_oferta:
                
                products = [ProductsTasks(task=task, **fila) for fila in list_products]   
                ProductsTasks.objects.bulk_create(products) 
            else:
                dbisam_db.update_table_tmp(name_table)
                if not is_oferta:
                    row_count = dbisam_db.update_a2precios(name_table)
                    duplicados = dbisam_db.update_tabla_tmp_productos_actualizados(name_table)
                    list_products_exists.extend(duplicados)
                else:
                    duplicados=dbisam_db.update_tabla_tmp_productos_actualizados(name_table)
                    row_count = dbisam_db.insert_into_sinvoferta(name_table, list_products)  
                    list_products_exists.extend(duplicados)

                task = Tasks.objects.create(
                    user_id = user,
                    #rif_proveedor = form.cleaned_data['rif_proveedor'],
                    file = form.cleaned_data['file'],
                    date_to_execute = fecha_ejecucion,
                    header_file = form.cleaned_data['header'],
                    dbisam_table = name_table,
                    check_process = True    
                    )          
            return len(list_products), task, list_products_exists, row_count #filas_validas if process else len(df)
        else:
            dbisam_db.delete_table(name_table)
            return ValueError("Todos los productos encontrados en el archivo están asignados a una lista pendiente. Los siguientes SKU ya existen: %s" % ', '.join(list_products_exists))
    except Exception as e:  
        print(e)      
        return ValueError("Error al leer el archivo: {}".format(e))

   
def print_labels(row, request):
    hPrinter=win32print.OpenPrinter(request.POST['so_printers'], {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
    static_path = os.path.join(settings.BASE_DIR, 'static', '%s.jpg' %request.POST['logo_etiquetas'])            
    
   

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


