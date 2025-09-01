from django import template
from django.contrib.auth.models import Group

register = template.Library()

@register.filter(name='has_group')
def has_group(user, group_name):
    """
    Verifica si el usuario pertenece a un grupo específico
    """
    if user.is_authenticated:
        return user.groups.filter(name=group_name).exists() or user.is_superuser
    return False

@register.filter(name='has_any_group')
def has_any_group(user, group_names):
    """
    Verifica si el usuario pertenece a alguno de los grupos especificados
    """
    if user.is_authenticated:
        if user.is_superuser:
            return True
            
        group_list = [name.strip() for name in group_names.split(',')]
        return user.groups.filter(name__in=group_list).exists()
    return False

@register.simple_tag
def user_groups(user):
    """
    Devuelve una lista de los nombres de los grupos del usuario
    """
    if user.is_authenticated:
        return list(user.groups.values_list('name', flat=True))
    return []