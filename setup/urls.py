from django.contrib import admin
from django.urls import path, include
from core.views import (
    dashboard,
    exportar_relatorio_csv,
    minha_unidade, 
    avaliar_membro, 
    cadastrar_desbravador, 
    calendario,
    cadastrar_evento, 
    painel_diretoria, 
    manifest,
    service_worker,
    relatorio_mensal,
    alterar_senha,
    toggle_acesso,
    reset_senha_diretoria,
    aprovar_membro,
    recusar_membro, 
    mural_notificacoes, # <--- IMPORTAÇÃO DA NOVA TELA
    api_notificacoes,           
    marcar_notificacao_lida,
    marcar_todas_lidas
)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    path('', dashboard, name='landing_temporaria'),
    path('dashboard/', dashboard, name='dashboard'),
    
    # PWA
    path('manifest.json', manifest, name='manifest'),
    path('sw.js', service_worker, name='service_worker'),
    
    # Conselheiro
    path('minha-unidade/', minha_unidade, name='minha_unidade'),
    path('avaliar/<int:id_desbravador>/', avaliar_membro, name='avaliar_membro'),
    path('cadastrar-dbv/', cadastrar_desbravador, name='cadastrar_desbravador'),
    
    # Diretoria
    path('diretoria/', painel_diretoria, name='painel_diretoria'),
    path('relatorio/', relatorio_mensal, name='relatorio_mensal'),
    path('diretoria/relatorio/', relatorio_mensal, name='relatorio_mensal_legacy'),
    
    # Senhas e Acessos
    path('alterar-senha/', alterar_senha, name='alterar_senha'),
    path('diretoria/acesso/<int:user_id>/', toggle_acesso, name='toggle_acesso'),
    path('diretoria/reset-senha/<int:user_id>/', reset_senha_diretoria, name='reset_senha_diretoria'),
    path('diretoria/aprovar/<int:id_dbv>/', aprovar_membro, name='aprovar_membro'),
    path('diretoria/recusar/<int:id_dbv>/', recusar_membro, name='recusar_membro'),
    
    # Calendário
    path('calendario/', calendario, name='calendario'),
    path('calendario/novo/', cadastrar_evento, name='cadastrar_evento'),
    
    # Autenticação
    path('accounts/', include('django.contrib.auth.urls')),
    path('relatorio/exportar/', exportar_relatorio_csv, name='exportar_relatorio_csv'),
    path('webpush/', include('webpush.urls')),

    # Central de Notificações
    path('notificacoes/', mural_notificacoes, name='mural_notificacoes'), # <--- NOVA ROTA NATIVA
    path('notificacoes/api/', api_notificacoes, name='api_notificacoes'),
    path('notificacoes/ler/<int:id_notificacao>/', marcar_notificacao_lida, name='marcar_notificacao_lida'),
    path('notificacoes/ler-todas/', marcar_todas_lidas, name='marcar_todas_lidas'),
    path('notificacoes/massa/', enviar_notificacao_massa, name='enviar_notificacao_massa'),
]