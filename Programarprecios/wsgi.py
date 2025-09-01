"""
WSGI config for Programarprecios project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
import site
import sys

venv_path = r"C:/Proyectos/Python/Precios-KsaHome/venv/Lib/site-packages"
site.addsitedir(venv_path)

# Asegurar que el proyecto está en sys.path
sys.path.insert(0, r"C:/Proyectos/Python/Precios-KsaHome")

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Programarprecios.settings')

application = get_wsgi_application()
