from datetime import date, datetime, timedelta
from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.safestring import mark_safe
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST 
from django.conf import settings
import calendar
import csv
from .models import Unidade, Desbravador, AvaliacaoSemanal, PontoExtra, Evento, Usuario, NotificacaoInApp 
from .forms import AvaliacaoForm, DesbravadorForm, EventoForm, PontoExtraForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache

# --- CONSTANTES ---
TOTAL_REGULAR_EXPR = (
    F('avaliacoes__biblia') + F('avaliacoes__uniforme') +
    F('avaliacoes__lenco') + F('avaliacoes__fazer_ideal') +
    F('avaliacoes__orar') + F('avaliacoes__participacao') +
    F('avaliacoes__itens_cartao') + F('avaliacoes__clube_visivel') +
    F('avaliacoes__estudo_biblico') + F('avaliacoes__escola_sabatina') +
    F('avaliacoes__pequeno_grupo') + F('avaliacoes__fanfarra') +
    F('avaliacoes__ordem_unida')
)

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

    # 1. Cria uma chave de cache única para o mês atual
    chave_cache = f'ranking_unidades_{mes_atual}_{ano_atual}'
    
    # 2. Tenta pegar o ranking pronto da memória RAM do servidor
    ranking = cache.get(chave_cache)

    # 3. Se o cache estiver vazio (ou tiver expirado), fazemos o cálculo pesado
    if not ranking:
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
            total_membros=Count('membros', filter=Q(membros__ativo=True, membros__aprovado=True), distinct=True)
        ).order_by('-pontos')
        
        # 4. Salva o resultado no cache por 10 minutos (600 segundos)
        cache.set(chave_cache, ranking, 600)

    return render(request, 'core/dashboard.html', {'ranking': ranking, 'mes': hoje.strftime('%B/%Y')})

# --- 2. LANÇAMENTO DE PONTOS ---
@login_required
def avaliar_membro(request, id_desbravador):
    membro = get_object_or_404(Desbravador, id=id_desbravador)
    
    if not request.user.is_diretoria and membro.unidade != request.user.unidade_responsavel:
        messages.error(request, "Você não tem permissão para pontuar membros de outra unidade.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = AvaliacaoForm(request.POST, user=request.user)
        if form.is_valid():
            avaliacao = form.save(commit=False)
            avaliacao.desbravador = membro
            avaliacao.autor = request.user 
            avaliacao.save()
            messages.success(request, f"Pontuação de {membro.nome_completo} salva com sucesso!")
            
            # Invalida o cache para que o ranking atualize imediatamente
            hoje = timezone.now()
            cache.delete(f'ranking_unidades_{hoje.month}_{hoje.year}')

            if request.user.is_diretoria:
                return redirect('painel_diretoria')
            return redirect('minha_unidade')
    else:
        form = AvaliacaoForm(initial={'desbravador': membro}, user=request.user)

    return render(request, 'core/avaliar.html', {'form': form, 'membro': membro})

# --- 3. PAINEL DA DIRETORIA ---
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
            
            # Invalida o cache para o ranking atualizar imediatamente
            hoje = timezone.now()
            cache.delete(f'ranking_unidades_{hoje.month}_{hoje.year}')
            
            messages.success(request, f"{count} desbravadores receberam {pontos} pontos!")
        else:
            messages.warning(request, "Preencha todos os campos e selecione os desbravadores.")
        return redirect('painel_diretoria')

    busca = request.GET.get('busca')
    unidade_filtro = request.GET.get('unidade')

    desbravadores = Desbravador.objects.filter(ativo=True, aprovado=True).select_related('unidade').order_by('unidade__nome', 'nome_completo')

    if busca:
        desbravadores = desbravadores.filter(nome_completo__icontains=busca)

    if unidade_filtro:
        desbravadores = desbravadores.filter(unidade_id=unidade_filtro)

    unidades = Unidade.objects.all()
    
    observacoes = (
        AvaliacaoSemanal.objects.select_related('desbravador', 'autor')
        .exclude(observacao__exact='')
        .exclude(observacao__isnull=True)
        .order_by('-data')[:30]
    )

    todos_usuarios = Usuario.objects.all().order_by('username')
    pendentes = Desbravador.objects.filter(ativo=True, aprovado=False).select_related('unidade').order_by('nome_completo')

    return render(request, 'core/painel_diretoria.html', {
        'desbravadores': desbravadores,
        'unidades': unidades,
        'observacoes': observacoes,
        'todos_usuarios': todos_usuarios,
        'pendentes': pendentes,
        'filtro_atual': int(unidade_filtro) if unidade_filtro and unidade_filtro.isdigit() else None
    })

# --- 4. RELATÓRIO MENSAL ---
@login_required
def relatorio_mensal(request):
    if not request.user.is_diretoria:
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    hoje = timezone.now()
    mes = int(request.GET.get('mes', hoje.month))
    ano = int(request.GET.get('ano', hoje.year))

    relatorio = Desbravador.objects.filter(ativo=True, aprovado=True).select_related('unidade').annotate(
        total_regular=Coalesce(Sum(TOTAL_REGULAR_EXPR, filter=Q(avaliacoes__data__month=mes, avaliacoes__data__year=ano)), 0),
        total_extra=Coalesce(Sum('pontos_extras__pontos', filter=Q(pontos_extras__data__month=mes, pontos_extras__data__year=ano)), 0)
    ).annotate(
        pontuacao_final=F('total_regular') + F('total_extra')
    ).order_by('-pontuacao_final', 'nome_completo')

    return render(request, 'core/relatorio_mensal.html', {
        'relatorio': relatorio,
        'mes_selecionado': mes,
        'ano_selecionado': ano,
    })

# --- 5. OUTRAS VIEWS ---
@login_required
def minha_unidade(request):
    unidade = request.user.unidade_responsavel
    if not unidade:
        messages.warning(request, "Você não é conselheiro de nenhuma unidade.")
        return redirect('dashboard')
        
    membros = Desbravador.objects.filter(unidade=unidade, ativo=True, aprovado=True)
    return render(request, 'core/minha_unidade.html', {'unidade': unidade, 'membros': membros})

@login_required
def cadastrar_desbravador(request):
    sou_diretor = request.user.is_diretoria or request.user.is_superuser
    
    # 1. Garante que o formulário visual já carregue com o "Ativo" marcado
    initial_data = {'ativo': True} 
    if not sou_diretor and request.user.unidade_responsavel:
        initial_data['unidade'] = request.user.unidade_responsavel.id

    if request.method == 'POST':
        form = DesbravadorForm(request.POST, user=request.user, initial=initial_data)
        
        if form.is_valid():
            dbv = form.save(commit=False)
            if sou_diretor:
                dbv.aprovado = True  
            else:
                dbv.aprovado = False 
                dbv.unidade = request.user.unidade_responsavel
            
            # 2. Força no backend! Se é um membro novo, ele TEM que nascer ativo na base de dados
            dbv.ativo = True 
            
            dbv.save()
            
            if dbv.aprovado:
                messages.success(request, f"{dbv.nome_completo} cadastrado com sucesso!")
            else:
                messages.warning(request, f"Cadastro de {dbv.nome_completo} enviado para aprovação.")
            return redirect('dashboard')
            
        else:
            # 3. Fim das falhas silenciosas: se der erro (ex: data inválida), o sistema avisa com banner vermelho!
            for field, erros in form.errors.items():
                for erro in erros:
                    nome_campo = form.fields[field].label if form.fields.get(field) else field
                    messages.error(request, f"Erro em {nome_campo}: {erro}")
    else:
        form = DesbravadorForm(user=request.user, initial=initial_data)
        
    return render(request, 'core/cadastrar_desbravador.html', {'form': form})

@login_required
def cadastrar_evento(request):
    if not request.user.is_diretoria and not request.user.unidade_responsavel:
        messages.error(request, "Sem permissão.")
        return redirect('calendario')

    if request.method == 'POST':
        form = EventoForm(request.POST, user=request.user)
        if form.is_valid():
            evento = form.save(commit=False)
            evento.autor = request.user
            if not request.user.is_diretoria:
                evento.unidade = request.user.unidade_responsavel
            evento.save()
            messages.success(request, "Evento criado!")
            return redirect('calendario')
    else:
        form = EventoForm(user=request.user)
    return render(request, 'core/cadastrar_evento.html', {'form': form})

# --- 7. EXPORTAÇÃO ---
@login_required
def exportar_relatorio_csv(request):
    if not request.user.is_diretoria:
        return redirect('dashboard')

    hoje = timezone.now()
    mes = int(request.GET.get('mes', hoje.month))
    ano = int(request.GET.get('ano', hoje.year))

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="pontuacao_dbv_{mes}_{ano}.csv"'
    response.write('\ufeff'.encode('utf8')) 

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Desbravador', 'Unidade', 'Pontos Regulares', 'Pontos Extras', 'Pontuacao Total'])

    desbravadores = Desbravador.objects.filter(ativo=True, aprovado=True).select_related('unidade').annotate(
        total_regular=Coalesce(Sum(TOTAL_REGULAR_EXPR, filter=Q(avaliacoes__data__month=mes, avaliacoes__data__year=ano)), 0),
        total_extra=Coalesce(Sum('pontos_extras__pontos', filter=Q(pontos_extras__data__month=mes, pontos_extras__data__year=ano)), 0)
    ).annotate(
        pontuacao_final=F('total_regular') + F('total_extra')
    ).order_by('unidade__nome', '-pontuacao_final')

    for dbv in desbravadores:
        writer.writerow([dbv.nome_completo, dbv.unidade.nome, dbv.total_regular, dbv.total_extra, dbv.pontuacao_final])
    return response

# --- 8. ACESSOS ---
@login_required
def alterar_senha(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  
            messages.success(request, 'Senha updated!')
            return redirect('dashboard')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'core/alterar_senha.html', {'form': form})

@login_required
def toggle_acesso(request, user_id):
    if not request.user.is_diretoria: return redirect('dashboard')
    usuario_alvo = get_object_or_404(Usuario, id=user_id)
    if usuario_alvo == request.user: return redirect('painel_diretoria')
        
    usuario_alvo.is_active = not usuario_alvo.is_active
    usuario_alvo.save()
    return redirect('painel_diretoria')

@login_required
def reset_senha_diretoria(request, user_id):
    if not request.user.is_diretoria: return redirect('dashboard')
    usuario = get_object_or_404(Usuario, id=user_id)
    usuario.set_password('dbv@123')
    usuario.save()
    return redirect('painel_diretoria')

@login_required
def aprovar_membro(request, id_dbv):
    if not request.user.is_diretoria: return redirect('dashboard')
    membro = get_object_or_404(Desbravador, id=id_dbv)
    membro.aprovado = True
    membro.save()
    return redirect('painel_diretoria')

@login_required
def recusar_membro(request, id_dbv):
    if not request.user.is_diretoria: return redirect('dashboard')
    membro = get_object_or_404(Desbravador, id=id_dbv)
    membro.delete() 
    return redirect('painel_diretoria')

# --- 9. NOVO MURAL DE NOTIFICAÇÕES (DEDICADO) ---
@login_required
def mural_notificacoes(request):
    # Avalia a lista IMEDIATAMENTE antes de mudar o banco (mantém o destaque visual de "Nova")
    notificacoes = list(NotificacaoInApp.objects.filter(usuario=request.user).order_by('-data_criacao'))
    # Atualiza em massa para "Lida"
    NotificacaoInApp.objects.filter(usuario=request.user, lida=False).update(lida=True)
    return render(request, 'core/notificacoes.html', {'notificacoes': notificacoes})

@login_required
def api_notificacoes(request):
    """ Mantemos essa rota leve apenas para o contador numérico (Badge) do topo funcionar """
    count = NotificacaoInApp.objects.filter(usuario=request.user, lida=False).count()
    return JsonResponse({'count': count})

@login_required
@require_POST
def marcar_notificacao_lida(request, id_notificacao):
    NotificacaoInApp.objects.filter(id=id_notificacao, usuario=request.user).update(lida=True)
    return JsonResponse({'status': 'ok'})

@login_required
@require_POST
def marcar_todas_lidas(request):
    NotificacaoInApp.objects.filter(usuario=request.user, lida=False).update(lida=True)
    return JsonResponse({'status': 'ok'})

# --- 9. CALENDÁRIO ---
@login_required
def calendario(request):
    hoje = date.today()
    ano = int(request.GET.get('ano', hoje.year))
    mes = int(request.GET.get('mes', hoje.month))

    if mes > 12:
        mes = 1; ano += 1
    elif mes < 1:
        mes = 12; ano -= 1

    if request.user.is_diretoria:
        eventos = Evento.objects.select_related('unidade', 'autor').filter(data_evento__year=ano, data_evento__month=mes)
    else:
        unidade_usuario = request.user.unidade_responsavel
        eventos = Evento.objects.select_related('unidade', 'autor').filter(
            Q(unidade=unidade_usuario) | Q(unidade__isnull=True),
            data_evento__year=ano, data_evento__month=mes
        )

    cal = calendar.Calendar()
    semanas_cruas = cal.monthdays2calendar(ano, mes)
    semanas = []
    for semana in semanas_cruas:
        dias_semana = []
        for dia, dia_semana in semana:
            if dia == 0:
                dias_semana.append(None) 
            else:
                eventos_do_dia = eventos.filter(data_evento__day=dia)
                dias_semana.append({
                    'dia': dia,
                    'hoje': (dia == hoje.day and mes == hoje.month and ano == hoje.year),
                    'eventos': eventos_do_dia
                })
        semanas.append(dias_semana)

    context = {
        'semanas': semanas,
        'mes_atual': date(ano, mes, 1),
        'prox_mes': 1 if mes == 12 else mes + 1,
        'prox_ano': ano + 1 if mes == 12 else ano,
        'ant_mes': 12 if mes == 1 else mes - 1,
        'ant_ano': ano - 1 if mes == 1 else ano,
    }
    return render(request, 'core/calendario.html', context)