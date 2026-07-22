from django.db import migrations


def crear_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name='Pedidos Receptor')


def borrar_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='Pedidos Receptor').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('PedidosAlmacen', '0024_depositopermitido_receptores'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]
    operations = [
        migrations.RunPython(crear_grupo, borrar_grupo),
    ]
