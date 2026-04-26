from django import forms
from django.core.exceptions import ValidationError
from .models import PontoExtra, Desbravador, AvaliacaoSemanal, Evento

# --- 1. FORMULÁRIO DE PONTO EXTRA ---
class PontoExtraForm(forms.ModelForm):
    class Meta:
        model = PontoExtra
        fields = ['desbravador', 'motivo', 'pontos']
        widgets = {
            'desbravador': forms.Select(attrs={'class': 'form-select'}),
            'motivo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Trouxe visitante'}),
            'pontos': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 5 ou -10'}),
        }

    # CORREÇÃO AQUI: Usamos *args, **kwargs e retiramos o user com pop()
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None) # Pega o usuário e remove dos argumentos
        super(PontoExtraForm, self).__init__(*args, **kwargs)
        
        # Filtro de Desbravadores
        if self.user:
            if self.user.is_diretoria:
                self.fields['desbravador'].queryset = Desbravador.objects.filter(ativo=True)
                self.fields['pontos'].widget.attrs['placeholder'] = 'Ex: 10 ou -10 (Punição)'
            else:
                # Conselheiro: Trava visual e filtro de unidade
                self.fields['pontos'].widget.attrs['min'] = '0'
                self.fields['pontos'].widget.attrs['placeholder'] = 'Apenas valores positivos'
                
                unidade = getattr(self.user, 'unidade_responsavel', None)
                if unidade:
                    self.fields['desbravador'].queryset = Desbravador.objects.filter(
                        unidade=unidade, ativo=True
                    )
                else:
                    self.fields['desbravador'].queryset = Desbravador.objects.none()

    def clean_pontos(self):
        pontos = self.cleaned_data.get('pontos')
        # Validação de segurança para pontos negativos
        if self.user and pontos is not None:
            if pontos < 0 and not self.user.is_diretoria:
                raise ValidationError("Apenas a Diretoria (Diretor/Vice) pode aplicar punições (pontos negativos).")
        return pontos

# --- 2. FORMULÁRIO DE AVALIAÇÃO SEMANAL ---
class AvaliacaoForm(forms.ModelForm):
    class Meta:
        model = AvaliacaoSemanal
        fields = '__all__'
        exclude = ['desbravador', 'autor'] 
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'observacao': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None) # Padronizado
        super(AvaliacaoForm, self).__init__(*args, **kwargs)
        
        # Estilização em massa
        for field_name, field in self.fields.items():
            if field_name not in ['ativo', 'concluida']:
                current_class = field.widget.attrs.get('class', '')
                if 'form-control' not in current_class and 'form-select' not in current_class:
                    field.widget.attrs['class'] = current_class + ' form-control'
                
                if isinstance(field.widget, forms.Select):
                    field.widget.attrs['class'] += ' form-select'

# --- 3. FORMULÁRIO DE CADASTRO DE DESBRAVADOR ---
class DesbravadorForm(forms.ModelForm):
    class Meta:
        model = Desbravador
        fields = ['nome_completo', 'data_nascimento', 'unidade', 'ativo', 'anotacoes_gerais']
        widgets = {
            'nome_completo': forms.TextInput(attrs={'class': 'form-control'}),
            'data_nascimento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'unidade': forms.Select(attrs={'class': 'form-select'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'anotacoes_gerais': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if 'anotacoes_gerais' in self.fields:
            self.fields['anotacoes_gerais'].required = False
            self.fields['anotacoes_gerais'].widget.attrs.update({
                'placeholder': 'Observações médicas, alergias, etc. (Opcional)'
            })

        # LOGICA DE VERIFICAÇÃO ROBUSTA DA DIRETORIA
        sou_diretor = False
        if self.user:
            if self.user.is_superuser or getattr(self.user, 'is_diretoria', False):
                sou_diretor = True

        if not sou_diretor:
            # Conselheiro: Trava a unidade e desobriga a validação no form
            if 'unidade' in self.fields:
                self.fields['unidade'].required = False
                self.fields['unidade'].widget.attrs['disabled'] = 'disabled'
        else:
            # Diretoria / Admin: Libera total
            if 'unidade' in self.fields:
                self.fields['unidade'].required = True
                self.fields['unidade'].disabled = False
                if 'disabled' in self.fields['unidade'].widget.attrs:
                    del self.fields['unidade'].widget.attrs['disabled']

    # O INTERCEPTADOR DE VALIDAÇÃO
    def clean_unidade(self):
        sou_diretor = False
        if self.user:
            if self.user.is_superuser or getattr(self.user, 'is_diretoria', False):
                sou_diretor = True

        unidade = self.cleaned_data.get('unidade')

        if not sou_diretor:
            # Se for conselheiro, injetamos a unidade do perfil dele à força
            if self.user and self.user.unidade_responsavel:
                return self.user.unidade_responsavel
            else:
                raise forms.ValidationError("Você não está vinculado a nenhuma unidade.")
        
        # Se for diretoria, ele PRECISA ter selecionado uma unidade na tela
        if not unidade:
            raise forms.ValidationError("Como Diretor, você precisa selecionar uma unidade na lista.")
        return unidade

# --- 4. FORMULÁRIO DE EVENTO (CORRIGIDO O ERRO DO USER) ---
class EventoForm(forms.ModelForm):
    class Meta:
        model = Evento
        fields = ['titulo', 'data_evento', 'descricao', 'unidade']
        widgets = {
            'titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Festa do Pijama'}),
            'data_evento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Detalhes do evento...'}),
            'unidade': forms.Select(attrs={'class': 'form-select'}),
        }
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None) # O user é extraído aqui
        super(EventoForm, self).__init__(*args, **kwargs) # O resto (request.POST) vai para o super
        
        # Lógica de Permissão para Unidade
        if user and not user.is_diretoria:
             # Conselheiro: campo hidden (oculto)
             self.fields['unidade'].widget = forms.HiddenInput()
             self.fields['unidade'].required = False
        else:
             # Diretor: campo visível e opcional (Global)
             self.fields['unidade'].required = False
             self.fields['unidade'].empty_label = "--- PARA TODO O CLUBE (GLOBAL) ---"