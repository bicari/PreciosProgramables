from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0003_add_condicion_deposito_pedido'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedidoitem',
            name='referencia',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='pedidoitem',
            name='puesto',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='pedidoitem',
            name='ref_proveedor',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
