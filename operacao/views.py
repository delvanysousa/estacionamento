import re
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, Permission, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import ATIVOS, Andar, Carro
from .perfis import DESCRICOES, PERFIS, PERMISSOES, criar_perfis

# Aceita placa antiga (ABC1234) e Mercosul (ABC1D23)
PADRAO_PLACA = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")


# ---------------------------------------------------------------- acesso
def precisa(codigo):
    """Só deixa entrar quem tem a liberação (o administrador sempre tem)."""

    def decorador(view):
        @login_required
        @wraps(view)
        def interno(request, *args, **kwargs):
            if not request.user.has_perm(f"operacao.{codigo}"):
                messages.error(request, "Você não tem liberação para acessar essa tela.")
                return redirect("painel")
            return view(request, *args, **kwargs)

        return interno

    return decorador


def so_admin(view):
    @login_required
    @wraps(view)
    def interno(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Só o administrador acessa essa tela.")
            return redirect("painel")
        return view(request, *args, **kwargs)

    return interno


def fmt_tempo(td):
    if td is None:
        return "-"
    minutos = max(int(td.total_seconds() // 60), 0)
    h, m = divmod(minutos, 60)
    return f"{h}h {m:02d}min" if h else f"{m} min"


def contexto(request, **extra):
    base = {"qtd_pagos": Carro.objects.filter(status="PAGO").count()}
    base.update(extra)
    return base


# ---------------------------------------------------------------- operação
@login_required
def painel(request):
    andares = Andar.objects.filter(ativo=True)
    return render(request, "operacao/painel.html", contexto(request, andares=andares))


@precisa("registrar_entrada")
def receber(request):
    andares = list(Andar.objects.filter(ativo=True))
    sugerido = next((a for a in andares if not a.cheio()), None)
    if request.method == "POST":
        ticket = request.POST.get("ticket", "").strip().upper()
        placa = re.sub(r"[^A-Z0-9]", "", request.POST.get("placa", "").upper())
        andar = get_object_or_404(Andar, pk=request.POST.get("andar"))
        if not ticket and not placa:
            messages.error(request, "Informe a placa ou o número do ticket.")
        elif placa and not PADRAO_PLACA.match(placa):
            messages.error(request, "Placa inválida. Confira e digite de novo.")
        elif placa and Carro.objects.filter(placa=placa).exclude(status="ENTREGUE").exists():
            messages.error(request, "Essa placa já está registrada no estacionamento.")
        elif andar.cheio():
            messages.error(request, f"O {andar} está CHEIO. Escolha outro andar.")
        else:
            try:
                Carro.objects.create(ticket=ticket, placa=placa, andar=andar, recebido_por=request.user)
                messages.success(request, f"Carro {placa or ticket} registrado no {andar}.")
                return redirect("receber")
            except IntegrityError:
                messages.error(request, "Esse ticket já está em uso por outro carro.")
    return render(request, "operacao/receber.html", contexto(request, andares=andares, sugerido=sugerido))


@precisa("usar_saida")
def andar_detalhe(request, numero):
    andar = get_object_or_404(Andar, numero=numero)
    carros = andar.carros.filter(status__in=ATIVOS).order_by("placa")
    return render(request, "operacao/andar.html", contexto(request, andar=andar, carros=carros))


@precisa("usar_saida")
def pagos(request):
    carros = Carro.objects.filter(status__in=["PAGO", "EM_RETIRADA"]).order_by("pago_em")
    return render(request, "operacao/pagos.html", contexto(request, carros=carros))


@precisa("usar_saida")
def busca(request):
    q = request.GET.get("q", "").strip()
    carros = []
    if q:
        placa = re.sub(r"[^A-Z0-9]", "", q.upper())
        filtro = Q(ticket__iexact=q)
        if placa:
            filtro |= Q(placa__icontains=placa)
        carros = Carro.objects.filter(filtro).exclude(status="ENTREGUE").select_related("andar")[:20]
    pagos_lista = (
        Carro.objects.filter(status__in=["PAGO", "EM_RETIRADA"]).select_related("andar").order_by("pago_em")
    )
    return render(request, "operacao/busca.html", contexto(request, q=q, carros=carros, pagos_lista=pagos_lista))


@login_required
@require_POST
def acao(request, pk, acao):
    agora = timezone.now()
    u = request.user
    carros = Carro.objects.filter(pk=pk)
    perdeu = "Esse carro já mudou de situação (outra pessoa pode ter feito antes)."
    exigidas = {"pagar": "marcar_pago", "desfazer": "marcar_pago", "entregar": "marcar_entregue"}
    codigo = exigidas.get(acao)

    if not codigo or not u.has_perm(f"operacao.{codigo}"):
        messages.error(request, "Você não tem liberação para fazer isso.")
    elif acao == "pagar":
        if carros.filter(status="ESTACIONADO").update(status="PAGO", pago_por=u, pago_em=agora):
            c = carros.select_related("andar").first()
            messages.success(request, f"PAGO. Mande o manobrista buscar {c.placa or c.ticket} no {c.andar}.")
        else:
            messages.error(request, perdeu)
    elif acao == "entregar":
        if carros.filter(status__in=["PAGO", "EM_RETIRADA"]).update(status="ENTREGUE", entregue_em=agora):
            messages.success(request, "Carro entregue. Vaga liberada.")
        else:
            messages.error(request, perdeu)
    elif acao == "desfazer":
        motivo = request.POST.get("motivo", "").strip()
        carro = carros.filter(status="PAGO").first()
        if not motivo:
            messages.error(request, "Informe o motivo para desfazer o pagamento.")
        elif carro:
            carro.status = "ESTACIONADO"
            carro.pago_por = None
            carro.pago_em = None
            carro.historico += f"{timezone.localtime(agora):%d/%m %H:%M} - {u.username} desfez o pago: {motivo}\n"
            carro.save()
            messages.success(request, "Pagamento desfeito.")
        else:
            messages.error(request, perdeu)

    destino = request.POST.get("voltar", "")
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        destino = "/"
    return redirect(destino)


# ---------------------------------------------------------------- relatório
def _periodo(request):
    hoje = timezone.localdate()

    def ler_data(valor, padrao):
        try:
            return date.fromisoformat(valor)
        except (TypeError, ValueError):
            return padrao

    ini = ler_data(request.GET.get("ini"), hoje)
    fim = ler_data(request.GET.get("fim"), hoje)
    if fim < ini:
        ini, fim = fim, ini
    return ini, fim, hoje


def dados_relatorio(ini, fim):
    agora = timezone.now()
    n_entraram = Carro.objects.filter(recebido_em__date__range=(ini, fim)).count()
    n_pagos_periodo = Carro.objects.filter(pago_em__date__range=(ini, fim)).count()
    entregues = (
        Carro.objects.filter(status="ENTREGUE", entregue_em__date__range=(ini, fim))
        .select_related("andar")
        .order_by("-entregue_em")
    )
    no_momento = list(Carro.objects.filter(status__in=ATIVOS).select_related("andar").order_by("recebido_em"))
    for c in no_momento:
        espera = agora - c.recebido_em
        c.tempo_txt = fmt_tempo(espera)
        c.minutos = max(int(espera.total_seconds() // 60), 0)

    saidos, permanencias, atendimentos = [], [], []
    for c in entregues:
        c.tempo = c.entregue_em - c.recebido_em
        c.tempo_txt = fmt_tempo(c.tempo)
        c.minutos = max(int(c.tempo.total_seconds() // 60), 0)
        permanencias.append(c.tempo)
        if c.pago_em:
            atendimentos.append(c.entregue_em - c.pago_em)
        saidos.append(c)

    def media(lista):
        return sum(lista, timedelta()) / len(lista) if lista else None

    return dict(
        n_entraram=n_entraram, n_pagos_periodo=n_pagos_periodo,
        n_entregues=len(saidos), n_no_momento=len(no_momento),
        n_pagos=sum(1 for c in no_momento if c.status == "PAGO"),
        media_txt=fmt_tempo(media(permanencias)),
        maior_txt=fmt_tempo(max(permanencias) if permanencias else None),
        atendimento_txt=fmt_tempo(media(atendimentos)),
        no_momento=no_momento, saidos=saidos,
        andares=Andar.objects.filter(ativo=True),
    )


@precisa("ver_relatorios")
def relatorios(request):
    ini, fim, hoje = _periodo(request)
    d = dados_relatorio(ini, fim)
    d.update(
        ini=ini.isoformat(), fim=fim.isoformat(), hoje=hoje.isoformat(),
        ontem=(hoje - timedelta(days=1)).isoformat(), sete=(hoje - timedelta(days=6)).isoformat(),
    )
    return render(request, "operacao/relatorios.html", contexto(request, **d))


def _local(dt):
    return timezone.localtime(dt).replace(tzinfo=None) if dt else None


def para_exportar(d, ini, fim, quem):
    """Transforma os dados do relatório em listas simples para PDF e Excel."""
    return {
        "ini": ini, "fim": fim, "quem": quem,
        "gerado_em": timezone.localtime(timezone.now()).replace(tzinfo=None),
        "resumo": [
            ("Carros que chegaram", d["n_entraram"]),
            ("Carros pagos", d["n_pagos_periodo"]),
            ("Carros que saíram", d["n_entregues"]),
            ("No estacionamento agora", d["n_no_momento"]),
            ("Pagos, ainda não saíram", d["n_pagos"]),
            ("Tempo médio no local", d["media_txt"]),
            ("Maior permanência", d["maior_txt"]),
            ("Tempo médio do pago até a entrega", d["atendimento_txt"]),
        ],
        "saidas": [
            {"placa": c.placa or "-", "ticket": c.ticket or "-", "subsolo": f"{c.andar.numero}º",
             "entrada": _local(c.recebido_em), "pago": _local(c.pago_em), "saida": _local(c.entregue_em),
             "tempo": c.tempo_txt, "minutos": c.minutos}
            for c in d["saidos"]
        ],
        "no_momento": [
            {"placa": c.placa or "-", "ticket": c.ticket or "-", "subsolo": f"{c.andar.numero}º",
             "situacao": c.get_status_display(), "entrada": _local(c.recebido_em), "pago": _local(c.pago_em),
             "tempo": c.tempo_txt, "minutos": c.minutos}
            for c in d["no_momento"]
        ],
        "ocupacao": [
            {"subsolo": str(a), "carros": a.ocupados(), "capacidade": a.capacidade, "livres": a.livres(),
             "situacao": "CHEIO" if a.cheio() else "Com vaga"}
            for a in d["andares"]
        ],
    }


@precisa("ver_relatorios")
def exportar(request, formato):
    if formato not in ("pdf", "excel"):
        raise Http404()
    ini, fim, _ = _periodo(request)
    try:
        from . import exportacao  # só carrega aqui, para não travar o resto do sistema
    except ImportError:
        messages.error(
            request,
            "Falta instalar o pacote de exportação. No terminal (com o venv ligado), rode: pip install -r requirements.txt",
        )
        return redirect("relatorios")
    quem = request.user.get_full_name() or request.user.username
    pacote = para_exportar(dados_relatorio(ini, fim), ini, fim, quem)
    if formato == "excel":
        conteudo = exportacao.gerar_excel(pacote)
        tipo, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    else:
        conteudo = exportacao.gerar_pdf(pacote)
        tipo, ext = "application/pdf", "pdf"
    resposta = HttpResponse(conteudo, content_type=tipo)
    resposta["Content-Disposition"] = f'attachment; filename="relatorio_{ini}_a_{fim}.{ext}"'
    return resposta


# ---------------------------------------------------------------- tela dos manobristas (telão)
JANELA_DESCER_MIN = 5   # por quantos minutos o carro novo aparece na coluna "pode descer"
URGENTE_MIN = 10        # a partir de quantos minutos esperando o carro pago fica vermelho


@precisa("usar_saida")
def telao(request):
    return render(request, "operacao/telao.html")


@precisa("usar_saida")
@never_cache
def telao_dados(request):
    """Dados que a tela dos manobristas busca a cada poucos segundos."""
    agora = timezone.now()
    subir = list(Carro.objects.filter(status__in=["PAGO", "EM_RETIRADA"]).select_related("andar"))
    subir.sort(key=lambda c: (c.status == "EM_RETIRADA", c.pago_em or agora))
    lista_subir = []
    for c in subir:
        espera = max(int((agora - (c.pago_em or agora)).total_seconds() // 60), 0)
        lista_subir.append({
            "id": c.pk, "placa": c.placa, "ticket": c.ticket, "andar": c.andar.numero,
            "status": c.status, "espera": espera,
            "urgente": c.status == "PAGO" and espera >= URGENTE_MIN,
        })
    limite = agora - timedelta(minutes=JANELA_DESCER_MIN)
    descer = Carro.objects.filter(status="ESTACIONADO", recebido_em__gte=limite).select_related("andar").order_by("recebido_em")
    return JsonResponse({
        "subir": lista_subir,
        "descer": [{"id": c.pk, "placa": c.placa, "ticket": c.ticket, "andar": c.andar.numero} for c in descer],
        "andares": [
            {"numero": a.numero, "livres": a.livres(), "cheio": a.cheio(), "cor": a.cor()}
            for a in Andar.objects.filter(ativo=True)
        ],
        "hora": timezone.localtime(agora).strftime("%H:%M:%S"),
    })


# ---------------------------------------------------------------- usuários (só administrador)
def rotulo_perfil(u):
    if u.is_superuser:
        return "Administrador"
    grupos = [g.name for g in u.groups.all()]
    if grupos and grupos[0] in PERFIS:
        return grupos[0]
    if u.user_permissions.exists():
        return "Personalizado"
    return "Só vê os andares"


@so_admin
def usuarios(request):
    lista = list(User.objects.order_by("username").prefetch_related("groups", "user_permissions"))
    for u in lista:
        u.perfil_txt = rotulo_perfil(u)
    return render(request, "operacao/usuarios.html", contexto(request, usuarios=lista))


def aplicar_perfil(u, perfil, marcadas):
    if perfil in PERFIS:
        u.groups.set(Group.objects.filter(name=perfil))
        u.user_permissions.clear()
    else:
        u.groups.clear()
        u.user_permissions.set(
            Permission.objects.filter(content_type__app_label="operacao", codename__in=marcadas)
        )


@so_admin
def usuario_form(request, pk=None):
    criar_perfis()  # garante que os perfis prontos existem
    alvo = get_object_or_404(User, pk=pk) if pk else None
    if alvo and alvo.is_superuser:
        messages.error(request, "Administradores são gerenciados no menu Admin.")
        return redirect("usuarios")

    f = {"username": "", "nome": "", "ativo": True}
    perfil_sel, marcadas = "Caixa", list(PERFIS["Caixa"])
    if alvo:
        f = {"username": alvo.username, "nome": alvo.first_name, "ativo": alvo.is_active}
        grupos = [g.name for g in alvo.groups.all()]
        if grupos and grupos[0] in PERFIS:
            perfil_sel, marcadas = grupos[0], list(PERFIS[grupos[0]])
        else:
            perfil_sel = "Personalizado"
            marcadas = list(
                alvo.user_permissions.filter(content_type__app_label="operacao").values_list("codename", flat=True)
            )

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        nome = request.POST.get("nome", "").strip()
        senha = request.POST.get("senha", "")
        perfil_sel = request.POST.get("perfil", "Caixa")
        marcadas = [c for c, _ in PERMISSOES if request.POST.get("perm_" + c)]
        ativo = request.POST.get("ativo") == "on"
        f = {"username": username if not alvo else alvo.username, "nome": nome, "ativo": ativo}
        erros = []
        if not alvo:
            if not username:
                erros.append("Informe o login (nome usado para entrar).")
            elif User.objects.filter(username__iexact=username).exists():
                erros.append("Já existe um usuário com esse login.")
        if perfil_sel not in PERFIS and perfil_sel != "Personalizado":
            erros.append("Escolha um perfil.")
        if alvo and alvo.pk == request.user.pk and not ativo:
            erros.append("Você não pode desativar o seu próprio usuário.")
        if not alvo or senha:
            try:
                validate_password(senha, user=alvo)
            except ValidationError as e:
                erros.extend(e.messages)
        if not erros:
            if not alvo:
                alvo = User(username=username)
            alvo.first_name = nome
            alvo.is_active = ativo
            alvo.is_staff = False
            alvo.is_superuser = False
            if senha:
                alvo.set_password(senha)
            alvo.save()
            aplicar_perfil(alvo, perfil_sel, marcadas)
            messages.success(request, f"Usuário {alvo.username} salvo.")
            return redirect("usuarios")
        for e in erros:
            messages.error(request, e)

    perfis = [
        {"nome": n, "descricao": DESCRICOES[n], "marcado": n == perfil_sel}
        for n in list(PERFIS) + ["Personalizado"]
    ]
    permissoes = [{"codigo": c, "rotulo": r, "marcada": c in marcadas} for c, r in PERMISSOES]
    return render(request, "operacao/usuario_form.html", contexto(
        request, alvo=alvo, f=f, perfis=perfis, permissoes=permissoes))
