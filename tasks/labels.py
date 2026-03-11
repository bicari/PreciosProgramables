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
    LOGO_NAME = "LOGO.GRF"
    @classmethod
    def generate_label(cls, width=None, height=None):
        width = width or cls.DEFAULT_WIDTH
        height = height or cls.DEFAULT_HEIGHT
        dpm = cls.DPM
        etiqueta_base = zpl.Label(height, width, dpm)
        return etiqueta_base
    
    @classmethod
    def get_logo_storage_zpl(cls, logo_path):
        """
        Genera el código ZPL para guardar el logo en la RAM de la impresora.
        Se usa ~DG (Download Graphic) en lugar de ^GF.
        """
        l = zpl.Label(10, 10, cls.DPM)
        # Usamos el conversor interno de la librería pero cambiamos el comando
        image = Image.open(logo_path)
        # write_graphic genera un ^GF, lo convertiremos a ~DG manualmente
        zpl_image = l.write_graphic(image, 9.5, 10)
        
        # Truco: Reemplazamos el comando de impresión inmediata (^GF) 
        # por el de almacenamiento (~DG)
        logo_storage = zpl_image.replace("^GF", "~DG")
        # El formato es ~DGR:NOMBRE.GRF, bytes_total, bytes_por_linea, datos...
        logo_storage = logo_storage.replace("A,1,1,", f"R:{cls.LOGO_NAME},")
        
        return logo_storage.encode('ascii')

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
        ofertas.write_text(f"Valido del {datos['Desde']} al {datos['Hasta']} o hasta agotarse la existencia", char_height=1, char_width=1, justification='C')
        ofertas.endorigin()
        return ofertas.dumpZPL().encode('utf-8', errors='ignore')   
    
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

        return hablador.dumpZPL().encode('utf-8', errors='ignore')


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


    @classmethod
    def label_zpl_ofertas(cls, datos:dict, width=None, heigth=None):
        KSA_CONSTRUCTOR_LOGO = "^GFA,481,728,8,:Z64:eJyt0TFqwzAUBuDnKlQZQpRmyhBsF3KAjAmIiNDSq/QI9VCQunfICZKjVKFLj2HoBQRdFDBW33vy0natwf4sW8+//ATQAB/FxbOii3nc9dneOnLUW54wGVwm05Klze7sKZDGvLHWpPjDU0psSsn9tBueh0HOM6lX2WAc6ysKrnpQFFhFkFRQeScowEhcKropATgIv0orF4HmABfRSfdUyO9inlt0VKsbHOAj1DqcghqPJYs1FlYf9E0Z7CuN76Kd4vvi3PXK6Ub4LkqvG+mfg6Ac0G2BGSVMPGCGhhFdcqtLKPhHlRPcOOklN1S0Kjc8lHlHos7qYYcqLpPYt0T/88v/P4TjPKXaHTmtArvUjSG1ri250cA2xj1hhYxVeCQ7FT9ZkT1CQ+uUx9mWVZvtO2suZ2yElKevF/RayDO0fxazGFwBrKEAqG/ub+fFrK4PD8V8P4fVYc8u4Go2hjF8A9d1qUY=:3398"
        KSA_HOME_LOGO = "^GFA,545,1128,12,:Z64:eJzN0jFOwzAUgOGXGuGCAGfs1FyBA6BWKktHuAHtORBxFIkwNeUCnITBUKSMXZlQJAbWsGWIYp4d+yUTYsRD+1VN/rovBsA1gX5dDHw3sO4ZaEnmWpGFLsmRrsnzr4Yc79o+k1CUtUBR3sDch0QNUeWTlfnokqW5zCWlub3fpYsGbfedS+I9yiexVfok+Kj9TReNVbcn+uOBdkm2U91OWWNto1gwtlFMGovKJzFqfiB+s740UZ3Za160CXOJDpRxwxWaqRhdsxLN1RxdBXafUqBLsPsHjpZwC+YpMTTADN0Y2O8h8HMTCpifJ8e5KT9/nKefOUannhjtD8EM+ucYURJDaUlmhSIPz0Zvrs1Sv/o/L5EmLbjzJrJUk3OupfeGZ4k7h+KJy8D7Gf3h3PB6YM1y55bplAx6l8vOe4gKsmSFm6jI8qH53s1QZHu9Yc5poc/In+2UDsGf1si93eDLAUBovJLb8/H94WSFz3y9eN+Oj47DRwmj9WJZjU8h/AZrefIAYWKuf11ecQ6Ta4Af3zS+sw==:68F5"   
        zpl_command = f"""^XA
^MMT
^PW456
^LL248
^LS0
^FO9,10{KSA_HOME_LOGO if datos['Logo'] == 'KsaHome' else KSA_CONSTRUCTOR_LOGO}
^FT13,155^A0N,14,15^FH\^CI28^FDSKU:^FS^CI27
^FT13,180^A0N,14,15^FH\^CI28^FDPRECIO ANTES:^FS^CI27
^FT56,152^A0N,25,25^FH\^CI28^FD{datos['SKU']}^FS^CI27
^FT124,181^A0N,20,20^FH\^CI28^FD{datos['PrecioAntes']}^FS^CI27
^FT14,209^A0N,14,15^FH\^CI28^FDAHORA:^FS^CI27
^FT70,210^A0N,25,25^FH\^CI28^FD{datos['Precio']}^FS^CI27
^FT280,132^A0N,20,20^FH\^CI28^FDDESCUENTO^FS^CI27
^FO280,134^GB105,0,2^FS
^FT295,157^A0N,17,18^FH\^CI28^FD{datos['DescuentoPorcentaje']}%^FS^CI27
^FT192,218^A0N,15,12^FH\^CI28^FDVálido del {datos['Desde']} al {datos['Hasta']}^FS^CI27
^FT41,234^A0N,15,12^FB463,1,3,C^FH\^CI28^FDo hasta agotarse la existencia^FS^CI27
^FT0,243^A0N,14,10^FB127,1,3,C^FH\^CI28^FD{datos['Departamento']}^FS^CI27
^FO95,14
^FB300,4,0,L,0^A0N,28,28^FD{datos['Descripcion']}^FS
^LRY^FO14,185^GB139,0,28^FS^LRN
^PQ1,0,1,Y
^XZ

"""
        return zpl_command.encode('utf-8')


    @classmethod
    def label_zpl_hablador(cls, datos:dict, width=None, heigth=None):
        KSA_CONSTRUCTOR_LOGO = "^GFA,481,728,8,:Z64:eJyt0TFqwzAUBuDnKlQZQpRmyhBsF3KAjAmIiNDSq/QI9VCQunfICZKjVKFLj2HoBQRdFDBW33vy0natwf4sW8+//ATQAB/FxbOii3nc9dneOnLUW54wGVwm05Klze7sKZDGvLHWpPjDU0psSsn9tBueh0HOM6lX2WAc6ysKrnpQFFhFkFRQeScowEhcKropATgIv0orF4HmABfRSfdUyO9inlt0VKsbHOAj1DqcghqPJYs1FlYf9E0Z7CuN76Kd4vvi3PXK6Ub4LkqvG+mfg6Ac0G2BGSVMPGCGhhFdcqtLKPhHlRPcOOklN1S0Kjc8lHlHos7qYYcqLpPYt0T/88v/P4TjPKXaHTmtArvUjSG1ri250cA2xj1hhYxVeCQ7FT9ZkT1CQ+uUx9mWVZvtO2suZ2yElKevF/RayDO0fxazGFwBrKEAqG/ub+fFrK4PD8V8P4fVYc8u4Go2hjF8A9d1qUY=:3398"
        KSA_HOME_LOGO = "^GFA,545,1128,12,:Z64:eJzN0jFOwzAUgOGXGuGCAGfs1FyBA6BWKktHuAHtORBxFIkwNeUCnITBUKSMXZlQJAbWsGWIYp4d+yUTYsRD+1VN/rovBsA1gX5dDHw3sO4ZaEnmWpGFLsmRrsnzr4Yc79o+k1CUtUBR3sDch0QNUeWTlfnokqW5zCWlub3fpYsGbfedS+I9yiexVfok+Kj9TReNVbcn+uOBdkm2U91OWWNto1gwtlFMGovKJzFqfiB+s740UZ3Za160CXOJDpRxwxWaqRhdsxLN1RxdBXafUqBLsPsHjpZwC+YpMTTADN0Y2O8h8HMTCpifJ8e5KT9/nKefOUannhjtD8EM+ucYURJDaUlmhSIPz0Zvrs1Sv/o/L5EmLbjzJrJUk3OupfeGZ4k7h+KJy8D7Gf3h3PB6YM1y55bplAx6l8vOe4gKsmSFm6jI8qH53s1QZHu9Yc5poc/In+2UDsGf1si93eDLAUBovJLb8/H94WSFz3y9eN+Oj47DRwmj9WJZjU8h/AZrefIAYWKuf11ecQ6Ta4Af3zS+sw==:68F5"   
        zpl_command = f"""^XA
^MMT
^PW400
^LL248
^LS0
^FO2,1{KSA_HOME_LOGO if datos['Logo'] == 'Ksa Home' else KSA_CONSTRUCTOR_LOGO}
^FT238,156^A0N,45,46^FH\^CI28^FD{datos['Precio'].replace(".",",")}^FS^CI27
^FT201,156^A0N,23,23^FH\^CI28^FDRef^FS^CI27
^FT11,109^A0N,11,10^FH\^CI28^FDJ-5019245-6^FS^CI27
^FT16,202^A0N,14,15^FH\^CI28^FDSKU:^FS^CI27
^FT16,225^A0N,14,15^FH\^CI28^FDCOD. BARRA:^FS^CI27
^FT50,202^A0N,14,15^FH\^CI28^FD{datos['SKU']}^FS^CI27
^FT111,225^A0N,14,15^FH\^CI28^FD{datos['CodBarra']}^FS^CI27
^FT273,224^A0N,11,10^FH\^CI28^FD{datos['Departamento']}^FS^CI27
^FT273,238^A0N,11,10^FH\^CI28^FD{datetime.date.today().strftime('%d/%m/%Y')}^FS^CI27
^FO86,14
^FB312,4,0,L,0^A0N,30,30^FD{datos['Descripcion']}
^PQ1,0,1,Y
^XZ
"""
        return zpl_command.encode('utf-8')



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