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
    aprovar_membro  # <--- CORREÇÃO AQUI: Importamos a nova função!
)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # --- PREPARAÇÃO PARA A FUTURA LANDING PAGE ---
    path('', dashboard, name='landing_temporaria'),
    path('dashboard/', dashboard, name='dashboard'),
    
    # Rotas PWA
    path('manifest.json', manifest, name='manifest'),
    path('sw.js', service_worker, name='service_worker'),
    
    # Rotas do Conselheiro
    path('minha-unidade/', minha_unidade, name='minha_unidade'),
    path('avaliar/<int:id_desbravador>/', avaliar_membro, name='avaliar_membro'),
    path('cadastrar-dbv/', cadastrar_desbravador, name='cadastrar_desbravador'),
    
    # Rotas da Diretoria
    path('diretoria/', painel_diretoria, name='painel_diretoria'),
    path('relatorio/', relatorio_mensal, name='relatorio_mensal'),
    path('diretoria/relatorio/', relatorio_mensal, name='relatorio_mensal_legacy'),
    
    # Rotas de Gestão de Acesso, Senha e Aprovação
    path('alterar-senha/', alterar_senha, name='alterar_senha'),
    path('diretoria/acesso/<int:user_id>/', toggle_acesso, name='toggle_acesso'),
    path('diretoria/reset-senha/<int:user_id>/', reset_senha_diretoria, name='reset_senha_diretoria'),
    path('diretoria/aprovar/<int:id_dbv>/', aprovar_membro, name='aprovar_membro'), # <--- A rota que precisa da importação acima
    
    # Rotas do Calendário
    path('calendario/', calendario, name='calendario'),
    path('calendario/novo/', cadastrar_evento, name='cadastrar_evento'),
    
    # Login/Logout
    path('accounts/', include('django.contrib.auth.urls')),

    # Rota do Exportar CSV
    path('relatorio/exportar/', exportar_relatorio_csv, name='exportar_relatorio_csv'),
]