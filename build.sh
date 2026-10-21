#!/usr/bin/env bash
# Roda a cada atualização no servidor (Render)
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py preparar
# Cria o administrador na primeira vez (usa as variáveis DJANGO_SUPERUSER_*)
python manage.py createsuperuser --no-input || echo "Administrador já existe."
