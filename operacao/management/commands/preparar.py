from django.core.management.base import BaseCommand

from operacao.models import Andar
from operacao.perfis import criar_perfis

# Capacidades informadas. 1º e 2º subsolo ainda não definidos (ficam inativos).
CAPACIDADES = {1: 0, 2: 0, 3: 60, 4: 120, 5: 120, 6: 120, 7: 120, 8: 120}


class Command(BaseCommand):
    help = "Cria os perfis de acesso e os 8 subsolos. Pode rodar mais de uma vez."

    def handle(self, *args, **opts):
        criar_perfis()
        for n, cap in CAPACIDADES.items():
            Andar.objects.get_or_create(numero=n, defaults={"capacidade": cap, "ativo": cap > 0})
        self.stdout.write(self.style.SUCCESS("Pronto: perfis e subsolos criados."))
