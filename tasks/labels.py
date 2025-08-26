from PIL import Image
import zpl
import socket
import datetime

class PrinterLabel(zpl.Label):
    #def __init__(self, width, height):
    #    super().__init__(width, height)
    DEFAULT_WIDTH = 50.6
    DEFAULT_HEIGHT = 31.8
    DPM = 8

    @classmethod
    def generate_label(cls, width=None, height=None):
        width = width or cls.DEFAULT_WIDTH
        height = height or cls.DEFAULT_HEIGHT
        dpm = cls.DPM
        etiqueta_base = zpl.Label(height, width, dpm)
        return etiqueta_base
    
    @classmethod
    def label_ofertas_ksa(cls, datos: dict, width=None, height=None):
        ofertas = cls.generate_label(height, width)
        #DESCRIPCION PRODUCTO
        ofertas.origin(10.8, 2)
        ofertas.textblock(39, lines=4, justification='J')
        ofertas.write_text(datos['Descripcion'], char_height=3.5 if len(datos['Descripcion'] ) < 80 else 2.5, char_width=3.5 if len(datos['Descripcion'] ) < 80 else 2.5, justification='J')
        ofertas.endorigin()
        #LOGO EMPRESA
        ofertas.origin(1, 1.95)
        ofertas.write_graphic(
            Image.open(datos['Logo']),
            9.5,
            10
            )
        ofertas.endorigin()
        #SKU
        ofertas.origin(1, 13.5)
        ofertas.write_text(f"SKU: {datos['SKU']}", char_height=3, char_width=3, justification='L')
        ofertas.endorigin()

        ofertas.origin(30, 15)
        ofertas.write_text('DESCUENTO', char_height=3, char_width=3, justification='L')
        ofertas.endorigin()
        #LINEA DE DESCUENTO
        ofertas.origin(30, 17.5)
        ofertas.draw_box(115, 2,1)
        ofertas.endorigin()

        #Porcentaje de descuento
        ofertas.origin(35, 18)
        ofertas.write_text(f"{datos['DescuentoPorcentaje']}%", char_height=4, char_width=4, justification='L')
        ofertas.endorigin()

        #Precio Antes
        ofertas.origin(1, 18)
        ofertas.write_text('Antes: ', char_height=2.5, char_width=2.5, justification='L')
        ofertas.endorigin()
        ofertas.origin(9, 17.1)
        ofertas.write_text(f"$ {datos['PrecioAntes']}", char_height=3.5, char_width=3.5, justification='L')
        ofertas.endorigin()
        #Precio Ahora
        ofertas.origin(1, 22.5)
        ofertas.write_text('Ahora: ', char_height=2.5, char_width=2.5, justification='L')
        ofertas.endorigin()
        ofertas.origin(9, 21.8)
        ofertas.write_text(f"$ {datos['Precio']}", char_height=3.5, char_width=3.5, justification='L')
        ofertas.endorigin()

        ofertas.origin(1, 28)
        ofertas.write_text(f"{datos['Departamento']}", char_height=1, char_width=1, justification='L')
        ofertas.endorigin()    

        ofertas.origin(28, 28)
        ofertas.textblock(20, lines=2, justification='C')
        ofertas.write_text('Valido del 17/08/2025 al 01/09/2025 o hasta agotarse la existencia', char_height=1, char_width=1, justification='C')
        ofertas.endorigin()
        return ofertas.dumpZPL().encode('ascii', errors='ignore')   
    
    @classmethod
    def label_hablador(cls, datos: dict, width=None, height=None):
        hablador= cls.generate_label(width, height)
        #DESCRIPCION PRODUCTO
        hablador.origin(10.8, 1.8)
        hablador.textblock(39, lines=4, justification='J')
        hablador.write_text(datos['Descripcion'], char_height=3.8 if len(datos['Descripcion'] ) < 80 else 2.5, char_width=3.8 if len(datos['Descripcion'] ) < 80 else 2.5, justification='C')
        hablador.endorigin()
        #BORDES LINEAS ESQUINAS
        #hablador.origin(0.0, 0.25)
        #hablador.draw_box(cls.DEFAULT_WIDTH * 10,2,5)
        #hablador.endorigin()
        #LOGO EMPRESA
        hablador.origin(0.9, 0.65)
        hablador.write_graphic(
            Image.open(datos['Logo']),
            10,
            10
            )
        hablador.endorigin()
        #RIF EMPRESA
        hablador.origin(0.9, 10.8)
        hablador.write_text('J-50119245-6', char_height=0.85, char_width=0.85, justification='L')
        hablador.endorigin()
        #Etiqueta ref
        hablador.origin(22, 18)
        hablador.write_text(f"Ref. ", char_height=3, char_width=3, justification='L')
        hablador.endorigin()
        #Precio
        hablador.origin(27, 16.2)
        hablador.write_text(' %s' %datos['Precio'].replace('.', ','), char_height=5.5, char_width=5.5, justification='L')
        hablador.endorigin()
        #SKU
        hablador.origin(0.9, 23.7)
        hablador.write_text(f"SKU: {datos['SKU']}", char_height=2, char_width=2, justification='L')
        hablador.endorigin()
        #COD. BARRA
        hablador.origin(0.9, 26.7)
        hablador.write_text(f"Cod.Barra: {datos['CodBarra']}", char_height=2, char_width=2, justification='L')
        hablador.endorigin()
        #DEPARTAMENTO
        hablador.origin(38, 26.7)
        hablador.write_text(f"{datos['Departamento'].upper()}", char_height=1.4, char_width=1.4, justification='L')
        hablador.endorigin()
        #FECHA
        hablador.origin(38, 28)
        hablador.write_text(f"{datetime.date.today().strftime('%d/%m/%Y')}", char_height=1.4, char_width=1.4, justification='L')
        hablador.endorigin()

        return hablador.dumpZPL().encode('ascii', errors='ignore')


    @classmethod
    def label_hablador_bordes(cls, datos: dict, width=None, height=None):
        hablador= cls.generate_label(width, height)
        #DESCRIPCION PRODUCTO
        hablador.origin(10.8, 1.8)
        hablador.textblock(39, lines=4, justification='J')
        hablador.write_text(datos['Descripcion'], char_height=3.8 if len(datos['Descripcion'] ) < 80 else 2.5, char_width=3.8 if len(datos['Descripcion'] ) < 80 else 2.5, justification='C')
        hablador.endorigin()
        #BORDES LINEAS ESQUINAS
        #hablador.origin(0.0, 0.25)
        #hablador.draw_box(cls.DEFAULT_WIDTH * 10,2,5)
        #hablador.endorigin()
        #LOGO EMPRESA
        hablador.origin(0.9, 0.65)
        hablador.write_graphic(
            Image.open(datos['Logo']),
            10,
            10
            )
        hablador.endorigin()
        #RIF EMPRESA
        hablador.origin(0.9, 10.8)
        hablador.write_text('J-50119245-6', char_height=0.85, char_width=0.85, justification='L')
        hablador.endorigin()
        #Etiqueta ref
        hablador.origin(22, 18)
        hablador.write_text(f"Ref. ", char_height=3, char_width=3, justification='L')
        hablador.endorigin()
        #Precio
        hablador.origin(27, 17.3)
        hablador.write_text(' %s' %str(datos['precio']).replace(".",","), char_height=4, char_width=4, justification='L')
        hablador.endorigin()
        #SKU
        hablador.origin(0.9, 23.7)
        hablador.write_text(f"SKU: {datos['SKU']}", char_height=2, char_width=2, justification='L')
        hablador.endorigin()
        #COD. BARRA
        hablador.origin(0.9, 26.7)
        hablador.write_text(f"Cod.Barra: {datos['SKU']}", char_height=2, char_width=2, justification='L')
        hablador.endorigin()
        #DEPARTAMENTO
        hablador.origin(42, 26.7)
        hablador.write_text(f"{datos['Departamento'].upper()}", char_height=1, char_width=1, justification='L')
        hablador.endorigin()
        #FECHA
        hablador.origin(42, 28)
        hablador.write_text(f"{datetime.date.today().strftime('%d/%m/%Y')}", char_height=1, char_width=1, justification='L')
        hablador.endorigin()

        return hablador.dumpZPL().encode('ascii', errors='ignore')






# Si estás usando conexión de red por Ethernet:
TCP_IP = '127.0.0.1'  # IP de la impresora
TCP_PORT = 9102



#label_ksa = PrinterLabel.label_ofertas_ksa({'Logo': "ksahomelogo.jpg", "SKU":"01010001", "Descripcion":"PRODUCTO PRUEBA"},
#                                       width=50, height=31.8)
#s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#s.connect((TCP_IP, TCP_PORT))
#label_ksa_2 = PrinterLabel.label_ofertas_ksa({'Logo': "ksahomelogo.jpg", "SKU":"01010001", 
#                                           "Descripcion":"COMBO MOCHILA/MORRAL+LONCHERA+CARTUCHERATRANSFORMERS CAPI REF 959064/959095/959086", 
#                                           "precio":4385.54,
#                                           'Departamento':'Juguetes'})
#print(label_ksa_2)
#s.send(label_ksa_2)
#s.send(label_ksa_2)
#s.close()

#l.preview()