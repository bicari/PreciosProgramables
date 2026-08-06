import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ubicaciones.models import Cuerpo, Galpon, Nivel, Rack, Ubicacion


class Command(BaseCommand):
    help = (
        "Importa la estructura Galpón/Rack/Cuerpo/Ubicación/Nivel desde un CSV "
        "con columnas G,R,C,U,N (una fila por Nivel, igual al maestro real del almacén). "
        "No importa asignaciones de producto."
    )

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str)

    def handle(self, *args, **options):
        path = options['csv_path']
        contadores = {'galpones': 0, 'racks': 0, 'cuerpos': 0, 'ubicaciones': 0, 'niveles': 0}

        try:
            archivo = open(path, newline='', encoding='utf-8')
        except OSError as e:
            raise CommandError(f"No se pudo abrir '{path}': {e}")

        with archivo, transaction.atomic():
            lector = csv.DictReader(archivo)
            for fila in lector:
                g_codigo = fila['G'].strip()
                r_codigo = fila['R'].strip()
                c_codigo = fila['C'].strip().zfill(2)
                u_codigo = fila['U'].strip().zfill(2)
                n_numero = int(fila['N'])

                galpon, creado = Galpon.objects.get_or_create(codigo=g_codigo)
                contadores['galpones'] += int(creado)
                rack, creado = Rack.objects.get_or_create(galpon=galpon, codigo=r_codigo)
                contadores['racks'] += int(creado)
                cuerpo, creado = Cuerpo.objects.get_or_create(rack=rack, codigo=c_codigo)
                contadores['cuerpos'] += int(creado)
                ubicacion, creado = Ubicacion.objects.get_or_create(cuerpo=cuerpo, codigo=u_codigo)
                contadores['ubicaciones'] += int(creado)
                _, creado = Nivel.objects.get_or_create(ubicacion=ubicacion, numero=n_numero)
                contadores['niveles'] += int(creado)

        self.stdout.write(self.style.SUCCESS(
            f"Importación completa: {contadores['galpones']} galpones, "
            f"{contadores['racks']} racks, {contadores['cuerpos']} cuerpos, "
            f"{contadores['ubicaciones']} ubicaciones, {contadores['niveles']} niveles creados."
        ))
