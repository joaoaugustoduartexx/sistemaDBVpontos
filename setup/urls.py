from django.contrib import admin
from django.urls import path, include
# Importamos cadastrar_evento aqui
from core.views import (
    dashboard, 
    minha_unidade, 
    avaliar_membro, 
    cadastrar_desbravador, 
    calendario,
    cadastrar_evento, # <--- NOVO
    painel_diretoria, 
    manifest,
    service_worker,
    relatorio_mensal
)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Rota da Página Inicial
    path('', dashboard, name='dashboard'),
    
    # Rotas PWA
    path('manifest.json', manifest, name='manifest'),
    path('sw.js', service_worker, name='service_worker'),
    
    # Rotas do Conselheiro
    path('minha-unidade/', minha_unidade, name='minha_unidade'),
    path('avaliar/<int:id_desbravador>/', avaliar_membro, name='avaliar_membro'),
    path('cadastrar-dbv/', cadastrar_desbravador, name='cadastrar_desbravador'),
    
    # Rotas da Diretoria
    path('diretoria/', painel_diretoria, name='painel_diretoria'),
    path('diretoria/relatorio/', relatorio_mensal, name='relatorio_mensal'),
    
    # Rotas do Calendário
    path('calendario/', calendario, name='calendario'),
    path('calendario/novo/', cadastrar_evento, name='cadastrar_evento'), # <--- NOVA ROTA
    
    # Login/Logout
    path('accounts/', include('django.contrib.auth.urls')),
]