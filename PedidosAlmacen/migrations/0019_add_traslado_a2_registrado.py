from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0018_add_cantidad_mayor_incidencia'),
    ]

    operations = [
        migrations.AddField(
            model_name='despacho',
            name='traslado_a2_registrado',
            field=models.BooleanField(default=False),
        ),
    ]
