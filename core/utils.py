from calendar import HTMLCalendar
from datetime import date
from .models import Evento

class Calendar(HTMLCalendar):
    def __init__(self, ano=None, mes=None, unidade=None):
        self.year = ano
        self.month = mes
        self.unidade = unidade
        super(Calendar, self).__init__()

    # --- TRADUÇÃO MANUAL (Para não depender do sistema operacional) ---
    def formatweekheader(self):
        dias_pt = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
        header = ''.join(f'<th class="{self.cssclasses[i]}">{dias_pt[i]}</th>' for i in range(7))
        return f'<tr>{header}</tr>'

    def formatmonthname(self, theyear, themonth, withyear=True):
        meses_pt = {
            1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
            5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
            9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
        }
        s = f'{meses_pt[themonth]} {theyear}' if withyear else f'{meses_pt[themonth]}'
        return f'<tr><th colspan="7" class="month">{s}</th></tr>'
    # ------------------------------------------------------------------

    def formatday(self, day, weekday):
        # Dias vazios
        if day == 0:
            return '<td class="noday">&nbsp;</td>'

        # Busca eventos
        eventos = Evento.objects.filter(
            data_evento__day=day,
            data_evento__month=self.month,
            data_evento__year=self.year,
            unidade=self.unidade
        )

        # Verifica se é HOJE
        hoje = date.today()
        eh_hoje = (hoje.year == self.year and hoje.month == self.month and hoje.day == day)
        css_class = "today" if eh_hoje else ""

        d = ''
        for evento in eventos:
            descricao_texto = evento.descricao if evento.descricao else "Sem descrição."
            
            d += f'''
                <li class="evento-item" 
                    data-bs-toggle="modal" 
                    data-bs-target="#verEventoModal"
                    data-titulo="{evento.titulo}"
                    data-data="{evento.data_evento.strftime('%d/%m/%Y')}"
                    data-descricao="{descricao_texto}">
                    {evento.titulo}
                </li>
            '''

        if day != 0:
            return f"<td class='{css_class}'><span class='date'>{day}</span><ul> {d} </ul></td>"
        return '<td></td>'

    def formatweek(self, theweek):
        week = ''
        for d, weekday in theweek:
            week += self.formatday(d, weekday)
        return f'<tr> {week} </tr>'

    def formatmonth(self, withyear=True):
        cal = f'<table border="0" cellpadding="0" cellspacing="0" class="calendar table table-bordered">\n'
        # Aqui ele chama nossas funções traduzidas acima
        cal += f'{self.formatmonthname(self.year, self.month, withyear=withyear)}\n'
        cal += f'{self.formatweekheader()}\n'
        for week in self.monthdays2calendar(self.year, self.month):
            cal += f'{self.formatweek(week)}\n'
        cal += '</table>'
        return cal