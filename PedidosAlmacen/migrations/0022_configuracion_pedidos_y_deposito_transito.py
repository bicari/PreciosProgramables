from django.db import migrations, models

DEPOSITO_TRANSITO_VIGENTE = 10  # valor histórico hardcodeado en dbisam.py


def crear_config_y_backfill(apps, schema_editor):
    """Crea la fila singleton de configuración y backfillea los pedidos.

    Los pedidos ya despachados usaron el depósito 10 como tránsito, por lo que
    su snapshot debe apuntar a 10 para que la recepción salga del depósito
    correcto aunque la configuración cambie después.
    """
    ConfiguracionPedidos = apps.get_model('PedidosAlmacen', 'ConfiguracionPedidos')
    Pedido = apps.get_model('PedidosAlmacen', 'Pedido')

    ConfiguracionPedidos.objects.get_or_create(
        pk=1, defaults={'deposito_transito': DEPOSITO_TRANSITO_VIGENTE}
    )
    Pedido.objects.filter(deposito_transito__isnull=True).update(
        deposito_transito=DEPOSITO_TRANSITO_VIGENTE
    )


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0021_add_estado_anulado'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfiguracionPedidos',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('deposito_transito', models.IntegerField(help_text='Código de depósito de tránsito en a2 (SDEPOSITOS.FDP_CODIGO).')),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Configuración de pedidos',
                'verbose_name_plural': 'Configuración de pedidos',
            },
        ),
        migrations.AddField(
            model_name='pedido',
            name='deposito_transito',
            field=models.IntegerField(blank=True, help_text='Depósito de tránsito usado en el despacho de este pedido (snapshot de la configuración al despachar).', null=True),
        ),
        migrations.RunPython(crear_config_y_backfill, migrations.RunPython.noop),
    ]
