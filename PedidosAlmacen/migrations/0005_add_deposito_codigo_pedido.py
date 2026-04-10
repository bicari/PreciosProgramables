from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0004_add_campos_producto_pedidoitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='deposito_codigo',
            field=models.IntegerField(null=True, blank=True),
        ),
    ]
