from datetime import date, datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.safestring import mark_safe
from django.http import HttpResponse, JsonResponse
from django.conf import settings
import calendar

# ADICIONADO 'Evento' aqui para corrigir o NameError
from .models import Unidade, Desbravador, AvaliacaoSemanal, PontoExtra, Evento 
from .forms import AvaliacaoForm, DesbravadorForm, EventoForm, PontoExtraForm

# --- CONFIGURAÇÃO PWA ---
def manifest(request):
    return render(request, 'manifest.json', content_type='application/json')

def service_worker(request):
    return render(request, 'sw.js', content_type='application/javascript')

# --- 1. DASHBOARD / RANKING ---
@login_required
def dashboard(request):
    hoje = timezone.now()
    mes_atual = hoje.month
    ano_atual = hoje.year

    # Cálculo do Ranking
    ranking = Unidade.objects.annotate(
        pontos=Coalesce(Sum(
            F('membros__avaliacoes__biblia') + F('membros__avaliacoes__uniforme') +
            F('membros__avaliacoes__lenco') + F('membros__avaliacoes__fazer_ideal') +
            F('membros__avaliacoes__orar') + F('membros__avaliacoes__participacao') +
            F('membros__avaliacoes__itens_cartao') + F('membros__avaliacoes__clube_visivel') +
            F('membros__avaliacoes__estudo_biblico') + F('membros__avaliacoes__escola_sabatina') +
            F('membros__avaliacoes__pequeno_grupo') + F('membros__avaliacoes__fanfarra') +
            F('membros__avaliacoes__ordem_unida'),
            filter=Q(membros__avaliacoes__data__month=mes_atual, membros__avaliacoes__data__year=ano_atual)
        ), 0) + Coalesce(Sum(
            'membros__pontos_extras__pontos',
            filter=Q(membros__pontos_extras__data__month=mes_atual, membros__pontos_extras__data__year=ano_atual)
        ), 0),
        # CORREÇÃO: total_membros para não conflitar com o related_name
        total_membros=Count('membros', filter=Q(membros__ativo=True), distinct=True)
    ).order_by('-pontos')

    return render(request, 'core/dashboard.html', {'ranking': ranking, 'mes': hoje.strftime('%B/%Y')})

# --- 2. LANÇAMENTO DE PONTOS (AVALIAÇÃO) ---
@login_required
def avaliar_membro(request, id_desbravador):
    membro = get_object_or_404(Desbravador, id=id_desbravador)
    
    # REGRA: Diretor pode tudo. Conselheiro só a própria unidade.
    if not request.user.is_diretoria and membro.unidade != request.user.unidade_responsavel:
        messages.error(request, "Você não tem permissão para pontuar membros de outra unidade.")
        return redirect('dashboard')

    if request.method == 'POST':
        # Passamos user=request.user para o formulário
        form = AvaliacaoForm(request.POST, user=request.user)
        if form.is_valid():
            avaliacao = form.save(commit=False)
            avaliacao.desbravador = membro
            avaliacao.autor = request.user # Salva quem fez a avaliação
            avaliacao.save()
            messages.success(request, f"Pontuação de {membro.nome_completo} salva com sucesso!")
            
            if request.user.is_diretoria:
                return redirect('painel_diretoria')
            return redirect('minha_unidade')
    else:
        form = AvaliacaoForm(initial={'desbravador': membro}, user=request.user)

    return render(request, 'core/avaliar.html', {'form': form, 'membro': membro})

# --- 3. PAINEL DA DIRETORIA (SÊNIOR) ---
@login_required
def painel_diretoria(request):
    if not request.user.is_diretoria:
        messages.error(request, "Acesso Negado: Área restrita à Diretoria.")
        return redirect('dashboard')

    if request.method == 'POST':
        ids_selecionados = request.POST.getlist('selecionados')
        pontos = request.POST.get('pontos')
        motivo = request.POST.get('motivo')

        if ids_selecionados and pontos and motivo:
            count = 0
            for dbv_id in ids_selecionados:
                PontoExtra.objects.create(
                    desbravador_id=dbv_id,
                    autor=request.user,
                    pontos=int(pontos),
                    motivo=motivo,
                    data=date.today()
                )
                count += 1
            messages.success(request, f"{count} desbravadores receberam {pontos} pontos!")
        else:
            messages.warning(request, "Preencha todos os campos e selecione os desbravadores.")
        return redirect('painel_diretoria')

    # Filtros e Busca
    busca = request.GET.get('busca')
    unidade_filtro = request.GET.get('unidade')
    
    desbravadores = Desbravador.objects.filter(ativo=True).select_related('unidade').order_by('unidade__nome', 'nome_completo')
    
    if busca:
        desbravadores = desbravadores.filter(nome_completo__icontains=busca)
    
    if unidade_filtro:
        desbravadores = desbravadores.filter(unidade_id=unidade_filtro)

    unidades = Unidade.objects.all()

    return render(request, 'core/painel_diretoria.html', {
        'desbravadores': desbravadores,
        'unidades': unidades,
        'filtro_atual': int(unidade_filtro) if unidade_filtro and unidade_filtro.isdigit() else None
    })

# --- 4. RELATÓRIO MENSAL (SECRETARIA) ---
@login_required
def relatorio_mensal(request):
    if not request.user.is_diretoria:
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    hoje = timezone.now()
    
    # CORREÇÃO: Removemos 'models.' e usamos Sum/F/Q direto
    relatorio = Desbravador.objects.filter(ativo=True).annotate(
        total_avaliacoes=Coalesce(Sum(
            F('avaliacoes__biblia') + F('avaliacoes__uniforme') + 
            F('avaliacoes__lenco') + F('avaliacoes__fazer_ideal') +
            F('avaliacoes__orar') + F('avaliacoes__participacao') +
            F('avaliacoes__itens_cartao') + F('avaliacoes__clube_visivel') + 
            F('avaliacoes__estudo_biblico') + F('avaliacoes__escola_sabatina') +
            F('avaliacoes__pequeno_grupo') + F('avaliacoes__fanfarra') + 
            F('avaliacoes__ordem_unida'),
            filter=Q(avaliacoes__data__month=hoje.month, avaliacoes__data__year=hoje.year)
        ), 0),
        total_extras=Coalesce(Sum(
            'pontos_extras__pontos',
            filter=Q(pontos_extras__data__month=hoje.month, pontos_extras__data__year=hoje.year)
        ), 0)
    ).annotate(
        pontuacao_final=F('total_avaliacoes') + F('total_extras')
    ).order_by('unidade__nome', 'nome_completo')

    return render(request, 'core/relatorio_mensal.html', {
        'relatorio': relatorio,
        'mes': hoje.strftime('%m/%Y')
    })

# --- 5. OUTRAS VIEWS (Manutenção) ---
@login_required
def minha_unidade(request):
    unidade = request.user.unidade_responsavel
    if not unidade:
        messages.warning(request, "Você não é conselheiro de nenhuma unidade.")
        return redirect('dashboard')
        
    membros = Desbravador.objects.filter(unidade=unidade, ativo=True)
    return render(request, 'core/minha_unidade.html', {'unidade': unidade, 'membros': membros})

@login_required
def cadastrar_desbravador(request):
    if request.method == 'POST':
        form = DesbravadorForm(request.POST)
        if form.is_valid():
            dbv = form.save(commit=False)
            if not request.user.is_diretoria and request.user.unidade_responsavel:
                dbv.unidade = request.user.unidade_responsavel
            dbv.save()
            messages.success(request, "Desbravador cadastrado com sucesso!")
            return redirect('minha_unidade')
    else:
        initial_data = {}
        if not request.user.is_diretoria and request.user.unidade_responsavel:
            initial_data['unidade'] = request.user.unidade_responsavel
        form = DesbravadorForm(initial=initial_data)
        
    return render(request, 'core/cadastrar_desbravador.html', {'form': form})

# --- 6. CALENDÁRIO E EVENTOS ---
@login_required
@login_required
def calendario(request):
    # 1. Definir o mês e ano atual (ou o solicitado na URL)
    hoje = date.today()
    ano = int(request.GET.get('ano', hoje.year))
    mes = int(request.GET.get('mes', hoje.month))

    # Ajuste de navegação (Anterior/Próximo)
    if mes > 12:
        mes = 1
        ano += 1
    elif mes < 1:
        mes = 12
        ano -= 1

    # 2. Buscar eventos
    if request.user.is_diretoria:
        eventos = Evento.objects.filter(
            data_evento__year=ano, 
            data_evento__month=mes
        )
    else:
        unidade_usuario = request.user.unidade_responsavel
        eventos = Evento.objects.filter(
            Q(unidade=unidade_usuario) | Q(unidade__isnull=True),
            data_evento__year=ano, 
            data_evento__month=mes
        )

    # 3. Montar a estrutura do calendário
    cal = calendar.Calendar()
    # weeks é uma lista de listas: [[(1, 0), (2, 1)...], ...] onde (dia, dia_semana)
    semanas_cruas = cal.monthdays2calendar(ano, mes)
    
    semanas = []
    for semana in semanas_cruas:
        dias_semana = []
        for dia, dia_semana in semana:
            if dia == 0:
                dias_semana.append(None) # Dia vazio (mês anterior/próximo)
            else:
                # Pega os eventos deste dia específico
                eventos_do_dia = eventos.filter(data_evento__day=dia)
                dias_semana.append({
                    'dia': dia,
                    'hoje': (dia == hoje.day and mes == hoje.month and ano == hoje.year),
                    'eventos': eventos_do_dia
                })
        semanas.append(dias_semana)

    # Dados para os botões de navegação
    data_atual = date(ano, mes, 1)
    mes_anterior = mes - 1
    ano_anterior = ano
    if mes_anterior < 1:
        mes_anterior = 12
        ano_anterior -= 1
        
    mes_proximo = mes + 1
    ano_proximo = ano
    if mes_proximo > 12:
        mes_proximo = 1
        ano_proximo += 1

    context = {
        'semanas': semanas,
        'mes_atual': data_atual,
        'prox_mes': mes_proximo,
        'prox_ano': ano_proximo,
        'ant_mes': mes_anterior,
        'ant_ano': ano_anterior,
    }

    return render(request, 'core/calendario.html', context)

# ADICIONADO: View para cadastrar evento
@login_required
def cadastrar_evento(request):
    # Verifica se pode criar eventos (Diretoria ou Conselheiro)
    if not request.user.is_diretoria and not request.user.unidade_responsavel:
        messages.error(request, "Você não tem permissão para criar eventos.")
        return redirect('calendario')

    if request.method == 'POST':
        form = EventoForm(request.POST, user=request.user)
        if form.is_valid():
            evento = form.save(commit=False)
            evento.autor = request.user
            
            # Se não for diretoria, força a unidade do usuário
            if not request.user.is_diretoria:
                evento.unidade = request.user.unidade_responsavel
            
            # Se for diretoria e o campo unidade vier vazio, ele salva como NULL (Global)
            
            evento.save()
            messages.success(request, "Evento cadastrado com sucesso!")
            return redirect('calendario')
    else:
        form = EventoForm(user=request.user)

    return render(request, 'core/cadastrar_evento.html', {'form': form})