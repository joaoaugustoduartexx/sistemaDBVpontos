🏕️ Sistema de Gestão para Clube de Desbravadores (DBV)
Um sistema web completo, responsivo e instalável (PWA) focado em resolver as dores reais da gestão de um Clube de Desbravadores.

📖 A História do Projeto
Este sistema nasceu da necessidade prática no campo. Desenvolvido por um diretor de clube que, lidando com os desafios do dia a dia, percebeu uma lacuna no controle de atividades, presença e engajamento das crianças. A ideia central é substituir planilhas complexas e papéis perdidos por uma ferramenta digital acessível na palma da mão (Mobile-First), facilitando a vida tanto dos conselheiros quanto da diretoria sênior.

🚀 Principais Funcionalidades
👥 Para o Conselheiro (Gestão de Unidade)
O conselheiro é a linha de frente do clube e precisa de agilidade.

Avaliação Semanal: Controle rápido de requisitos (Bíblia, Uniforme, Voto/Lei, presença em cultos e reuniões regulares).

Diário de Observações: Um campo dedicado para registrar pedidos de oração, comportamentos ou notas importantes sobre o desenvolvimento do desbravador.

Calendário da Unidade: Autonomia para agendar eventos específicos da sua unidade (ex: Festa do pijama, acampamento de unidade).

Lançamento de Pontos: Sistema de pontuação positiva para recompensar o bom desempenho.

👑 Para a Diretoria Sênior (Acesso Global)
Visão macro e controle total do clube para diretores, vice-diretores e secretários.

Ação em Massa: Possibilidade de pontuar (positiva ou negativamente) múltiplos desbravadores de uma vez (ex: "As 5 crianças selecionadas ganharam 10 pontos por limparem o chão sem ser pedido").

Gestão Disciplinar: Lançamento de pontos negativos caso haja desrespeito às Leis, Voto ou regras do clube, mantendo um histórico claro.

Calendário Global: Criação de eventos que aparecem automaticamente para todos os conselheiros e unidades.

Relatórios de Desempenho: Geração de relatórios mensais e rankings de pontuação formatados para impressão e reuniões de diretoria.

⚙️ Automatizações do Sistema
Ranking Dinâmico: O ranking de unidades é fechado mensalmente. O histórico de meses anteriores permanece salvo e acessível no banco de dados, mas a competição vira a página para um novo ciclo todo mês 1.

🛠️ Tecnologias Utilizadas
Backend: Python + Django

Frontend: HTML5, CSS3, Bootstrap 5 (Mobile-First)

Banco de Dados: SQLite (Fácil portabilidade e deploy)

PWA (Progressive Web App): O sistema pode ser "instalado" diretamente na tela inicial do celular do conselheiro, funcionando como um aplicativo nativo.

⚙️ Como executar o projeto localmente
Clone o repositório:

Bash
git clone https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
Crie e ative um ambiente virtual:

Bash
python -m venv venv
source venv/bin/activate  # No Windows use: venv\Scripts\activate
Instale as dependências (certifique-se de ter um arquivo requirements.txt):

Bash
pip install -r requirements.txt
Realize as migrações do banco de dados:

Bash
python manage.py migrate
Crie um superusuário para acessar a área da Diretoria:

Bash
python manage.py createsuperuser
Inicie o servidor local:

Bash
python manage.py runserver
Acesse http://localhost:8000 no seu navegador.

**Desenvolvido com dedicação por [João Duarte](https://joaoaugustoduartexx.github.io/Curriculo/).**