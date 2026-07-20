from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0013_pedido_picker'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pedido',
            name='estado',
            field=models.CharField(
                choices=[
                    ('PENDIENTE', 'Pendiente'),
                    ('ASIGNADO', 'Asignado'),
                    ('PICKING', 'Picking'),
                    ('EN_PREPARACION', 'En Preparación'),
                    ('DESPACHADO', 'Despachado'),
                    ('PARCIAL', 'Parcial'),
                    ('RECIBIDO', 'Recibido'),
                    ('CERRADO', 'Cerrado'),
                ],
                default='PENDIENTE',
                max_length=20,
            ),
        ),
    ]
