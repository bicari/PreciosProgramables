from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0007_add_estado_parcial'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedidoitem',
            name='cantidad_back_order',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='pedidoitem',
            name='estado',
            field=models.CharField(
                choices=[
                    ('PENDIENTE', 'Pendiente'),
                    ('DESPACHADO', 'Despachado'),
                    ('PARCIAL', 'Parcial'),
                    ('RECIBIDO', 'Recibido'),
                    ('BACK_ORDER', 'Back Order'),
                    ('INCIDENCIA', 'Incidencia'),
                ],
                default='PENDIENTE',
                max_length=20,
            ),
        ),
    ]
