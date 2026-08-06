from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, Rack, Ubicacion


def _registrar(tipo: str, usuario, **kwargs) -> None:
    MovimientoUbicacion.objects.create(tipo=tipo, usuario=usuario, **kwargs)


class UbicacionesService:

    # ------------------------------------------------------------------ Galpón

    @staticmethod
    @transaction.atomic
    def crear_galpon(codigo: str, nombre: str, grid_filas: int, grid_columnas: int, usuario) -> Galpon:
        """Crea un galpón normalizando el código a mayúsculas."""
        codigo = codigo.strip().upper()
        if Galpon.objects.filter(codigo=codigo).exists():
            raise ValidationError(f"Ya existe un galpón con código '{codigo}'.")
        galpon = Galpon.objects.create(
            codigo=codigo, nombre=nombre,
            grid_filas=grid_filas, grid_columnas=grid_columnas,
            creado_por=usuario,
        )
        _registrar('CREACION_GALPON', usuario, galpon=galpon)
        return galpon

    @staticmethod
    @transaction.atomic
    def editar_galpon(galpon: Galpon, nombre: str, grid_filas: int, grid_columnas: int, usuario) -> Galpon:
        galpon.nombre = nombre
        galpon.grid_filas = grid_filas
        galpon.grid_columnas = grid_columnas
        galpon.save(update_fields=['nombre', 'grid_filas', 'grid_columnas', 'fecha_modificacion'])
        _registrar('EDICION_GALPON', usuario, galpon=galpon)
        return galpon

    @staticmethod
    @transaction.atomic
    def desactivar_galpon(galpon: Galpon, usuario) -> None:
        """Soft-delete de galpón. Rechaza si tiene racks activos."""
        if galpon.racks.filter(activo=True).exists():
            raise ValidationError(
                f"El galpón '{galpon.codigo}' tiene racks activos. "
                "Desactívalos antes de desactivar el galpón."
            )
        galpon.activo = False
        galpon.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_GALPON', usuario, galpon=galpon)

    # ------------------------------------------------------------------ Rack

    @staticmethod
    @transaction.atomic
    def crear_rack(
        galpon: Galpon, codigo: str, descripcion: str,
        grid_fila: int, grid_columna: int, ancho: int, alto: int,
        max_niveles: int, usuario,
    ) -> Rack:
        """Crea un rack normalizando el código a mayúsculas."""
        codigo = codigo.strip().upper()
        if not galpon.activo:
            raise ValidationError(f"El galpón '{galpon.codigo}' está desactivado.")
        if Rack.objects.filter(galpon=galpon, codigo=codigo).exists():
            raise ValidationError(
                f"Ya existe un rack con código '{codigo}' en el galpón '{galpon.codigo}'."
            )
        rack = Rack.objects.create(
            galpon=galpon, codigo=codigo, descripcion=descripcion,
            grid_fila=grid_fila, grid_columna=grid_columna, ancho=ancho, alto=alto,
            max_niveles=max_niveles, creado_por=usuario,
        )
        _registrar('CREACION_RACK', usuario, galpon=galpon, rack=rack)
        return rack

    @staticmethod
    @transaction.atomic
    def editar_rack(
        rack: Rack, descripcion: str,
        grid_fila: int, grid_columna: int, ancho: int, alto: int,
        max_niveles: int, usuario,
    ) -> Rack:
        """Edita un rack. `max_niveles` solo se puede cambiar si el rack aún no tiene cuerpos."""
        if max_niveles != rack.max_niveles and rack.cuerpos.exists():
            raise ValidationError(
                f"El rack '{rack.codigo}' ya tiene cuerpos creados; "
                "no se puede cambiar el máximo de niveles."
            )
        rack.descripcion = descripcion
        rack.grid_fila = grid_fila
        rack.grid_columna = grid_columna
        rack.ancho = ancho
        rack.alto = alto
        rack.max_niveles = max_niveles
        rack.save(update_fields=[
            'descripcion', 'grid_fila', 'grid_columna', 'ancho', 'alto',
            'max_niveles', 'fecha_modificacion',
        ])
        _registrar('EDICION_RACK', usuario, galpon=rack.galpon, rack=rack)
        return rack

    @staticmethod
    @transaction.atomic
    def desactivar_rack(rack: Rack, usuario) -> None:
        """Soft-delete de rack. Rechaza si tiene cuerpos activos."""
        if rack.cuerpos.filter(activo=True).exists():
            raise ValidationError(
                f"El rack '{rack.codigo}' tiene cuerpos activos. "
                "Desactívalos antes de desactivar el rack."
            )
        rack.activo = False
        rack.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_RACK', usuario, galpon=rack.galpon, rack=rack)

    # ------------------------------------------------------------------ Cuerpo

    @staticmethod
    @transaction.atomic
    def crear_cuerpo(rack: Rack, descripcion: str, usuario) -> Cuerpo:
        """
        Crea un cuerpo en el rack, autogenerando sus 2 Ubicaciones (numeración
        global no reiniciada por cuerpo, para calzar con las etiquetas físicas
        ya impresas) y, para cada una, sus Niveles según `rack.max_niveles`.
        """
        if not rack.activo:
            raise ValidationError(f"El rack '{rack.codigo}' está desactivado.")
        siguiente_num = rack.cuerpos.count() + 1
        cuerpo = Cuerpo.objects.create(
            rack=rack, codigo=f"{siguiente_num:02d}",
            descripcion=descripcion, creado_por=usuario,
        )
        for offset in (0, 1):
            ubicacion_num = 2 * siguiente_num - 1 + offset
            ubicacion = Ubicacion.objects.create(
                cuerpo=cuerpo, codigo=f"{ubicacion_num:02d}", creado_por=usuario,
            )
            Nivel.objects.bulk_create([
                Nivel(ubicacion=ubicacion, numero=n, creado_por=usuario)
                for n in range(1, rack.max_niveles + 1)
            ])
        _registrar('CREACION_CUERPO', usuario, galpon=rack.galpon, rack=rack, cuerpo=cuerpo)
        return cuerpo

    @staticmethod
    @transaction.atomic
    def desactivar_cuerpo(cuerpo: Cuerpo, usuario) -> None:
        """Soft-delete de cuerpo. Rechaza si tiene ubicaciones activas."""
        if cuerpo.ubicaciones.filter(activo=True).exists():
            raise ValidationError(
                f"El cuerpo '{cuerpo.codigo}' tiene ubicaciones activas. "
                "Desactívalas antes de desactivar el cuerpo."
            )
        cuerpo.activo = False
        cuerpo.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_CUERPO', usuario, galpon=cuerpo.rack.galpon, rack=cuerpo.rack, cuerpo=cuerpo)

    # ------------------------------------------------------------------ Ubicación

    @staticmethod
    @transaction.atomic
    def desactivar_ubicacion(ubicacion: Ubicacion, usuario) -> None:
        """Soft-delete de ubicación. Rechaza si tiene niveles activos."""
        if ubicacion.niveles.filter(activo=True).exists():
            raise ValidationError(
                f"La ubicación '{ubicacion.codigo}' tiene niveles activos. "
                "Desactívalos antes de desactivar la ubicación."
            )
        ubicacion.activo = False
        ubicacion.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar(
            'DESACTIVACION_UBICACION', usuario,
            galpon=ubicacion.rack.galpon, rack=ubicacion.rack, ubicacion=ubicacion,
        )

    # ------------------------------------------------------------------ Nivel

    @staticmethod
    @transaction.atomic
    def editar_nivel(nivel: Nivel, tipo: str, descripcion: str, usuario) -> Nivel:
        if nivel.esta_fusionado:
            raise ValidationError(
                f"El nivel '{nivel.codigo_completo}' está fusionado con "
                f"'{nivel.fusionado_en.codigo_completo}'; edítalo desde el nivel maestro."
            )
        nivel.tipo = tipo
        nivel.descripcion = descripcion
        nivel.save(update_fields=['tipo', 'descripcion', 'fecha_modificacion'])
        _registrar('EDICION_NIVEL', usuario, galpon=nivel.galpon, rack=nivel.rack, nivel=nivel)
        return nivel

    @staticmethod
    @transaction.atomic
    def desactivar_nivel(nivel: Nivel, usuario) -> None:
        """Soft-delete de nivel. Rechaza si tiene productos asignados."""
        if nivel.productos.exists():
            raise ValidationError(
                f"El nivel '{nivel.codigo_completo}' tiene productos asignados. "
                "Quítalos o trasládalos antes de desactivarlo."
            )
        nivel.activo = False
        nivel.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_NIVEL', usuario, galpon=nivel.galpon, rack=nivel.rack, nivel=nivel)
