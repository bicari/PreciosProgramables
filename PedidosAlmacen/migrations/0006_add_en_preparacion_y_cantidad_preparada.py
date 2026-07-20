from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0005_add_deposito_codigo_pedido'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pedido',
            name='estado',
            field=models.CharField(
                choices=[
                    ('PENDIENTE', 'Pendiente'),
                    ('PICKING', 'Picking'),
                    ('EN_PREPARACION', 'En Preparación'),
                    ('DESPACHADO', 'Despachado'),
                    ('RECIBIDO', 'Recibido'),
                    ('CERRADO', 'Cerrado'),
                ],
                default='PENDIENTE',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='pedidoitem',
            name='cantidad_preparada',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
