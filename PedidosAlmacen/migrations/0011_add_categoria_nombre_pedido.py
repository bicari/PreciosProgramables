from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0010_add_incidencias_despachoitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='categoria_nombre',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
    ]
