from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0014_add_estado_asignado'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='despacho',
            name='picker',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='despachos_pickeados',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='despacho',
            name='estado',
            field=models.CharField(
                choices=[
                    ('PENDIENTE_APROBACION', 'Pendiente de Aprobación'),
                    ('PREPARANDO', 'Preparando'),
                    ('ENVIADO', 'Enviado'),
                    ('RECIBIDO', 'Recibido'),
                    ('PARCIAL', 'Parcial'),
                ],
                default='PREPARANDO',
                max_length=20,
            ),
        ),
    ]
