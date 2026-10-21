from django.contrib.auth.models import Group, Permission

# Cada permissão é uma "liberação" que o administrador pode dar a um usuário.
PERMISSOES = [
    ("registrar_entrada", "Receber carro (registrar a entrada)"),
    ("usar_saida", "Consultar carros e usar a tela Saída"),
    ("marcar_pago", "Marcar carro como PAGO (e desfazer)"),
    ("marcar_entregue", "Marcar carro como ENTREGUE"),
    ("ver_relatorios", "Ver relatórios"),
]

# Perfis prontos: um conjunto de liberações com nome.
PERFIS = {
    "Caixa": ["registrar_entrada", "usar_saida", "marcar_pago", "marcar_entregue", "ver_relatorios"],
    "Somente visualização": ["usar_saida", "ver_relatorios"],
}
DESCRICOES = {
    "Caixa": "Entrada, saída, pagamento e relatório.",
    "Somente visualização": "Consulta carros e relatórios, sem alterar nada.",
    "Personalizado": "Você escolhe as liberações marcando as caixas abaixo.",
}


def criar_perfis():
    for nome, codigos in PERFIS.items():
        grupo, _ = Group.objects.get_or_create(name=nome)
        grupo.permissions.set(
            Permission.objects.filter(content_type__app_label="operacao", codename__in=codigos)
        )
