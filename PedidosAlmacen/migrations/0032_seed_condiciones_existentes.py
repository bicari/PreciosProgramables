from django.db import migrations


CONDICIONES_INICIALES = [
    # codigo, nombre, color_badge, icono, orden
    ('URGENTE', 'Urgente', 'danger', 'fa-bolt', 1),
    ('SURTIDO', 'Surtido', 'success', '', 2),
    ('CLIENTE_RETIRA', 'Cliente Retira', 'info', '', 3),
    ('INSUMOS', 'Insumos', 'secondary', '', 4),
]


def sembrar_condiciones(apps, schema_editor):
    Condicion = apps.get_model('PedidosAlmacen', 'Condicion')
    for codigo, nombre, color_badge, icono, orden in CONDICIONES_INICIALES:
        Condicion.objects.get_or_create(
            codigo=codigo,
            defaults={'nombre': nombre, 'color_badge': color_badge, 'icono': icono, 'orden': orden},
        )


def eliminar_condiciones(apps, schema_editor):
    Condicion = apps.get_model('PedidosAlmacen', 'Condicion')
    codigos = [c[0] for c in CONDICIONES_INICIALES]
    Condicion.objects.filter(codigo__in=codigos).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0031_condicion_alter_pedido_condicion'),
    ]

    operations = [
        migrations.RunPython(sembrar_condiciones, eliminar_condiciones),
    ]
