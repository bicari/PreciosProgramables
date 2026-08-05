from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0027_pedido_cerrado_por_pedido_fecha_cierre_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='despachoitem',
            name='tipo_incidencia',
            field=models.CharField(blank=True, choices=[('PRODUCTO_ERRONEO', 'Producto Erróneo'), ('SKU_NO_CONTEMPLADO', 'SKU No Contemplado'), ('CANTIDAD_MENOR', 'Cantidad Menor a lo Despachado'), ('CANTIDAD_MAYOR', 'Cantidad Mayor a lo Despachado'), ('RECIBIDO_SIN_DESPACHAR', 'Recibido sin haber sido despachado')], default='', max_length=30),
        ),
    ]
