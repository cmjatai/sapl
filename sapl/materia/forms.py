
from datetime import datetime
import os

from crispy_forms.bootstrap import Alert, InlineCheckboxes, FormActions,\
    InlineRadios
import django_filters
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Button, Column, Fieldset, Layout, Row,\
    Field, Submit
from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.files.base import File
from django.db import models, transaction
from django.db.models import Max
from django.forms import ModelForm, widgets
from django.forms.forms import Form
from django.utils.translation import ugettext_lazy as _

from sapl.base.models import Autor
from sapl.comissoes.models import Comissao
from sapl.crispy_layout_mixin import form_actions, to_row, to_column,\
    SaplFormLayout
from sapl.materia.models import TipoProposicao, RegimeTramitacao, TipoDocumento
from sapl.norma.models import (LegislacaoCitada, NormaJuridica,
                               TipoNormaJuridica)
from sapl.parlamentares.models import Parlamentar
from sapl.protocoloadm.models import Protocolo
from sapl.settings import MAX_DOC_UPLOAD_SIZE
from sapl.utils import (RANGE_ANOS, RangeWidgetOverride, autor_label,
                        autor_modal, models_with_gr_for_model,
                        ChoiceWithoutValidationField, YES_NO_CHOICES)
import sapl

from .models import (AcompanhamentoMateria, Anexada, Autoria, DespachoInicial,
                     DocumentoAcessorio, MateriaLegislativa, Numeracao,
                     Proposicao, Relatoria, TipoMateriaLegislativa, Tramitacao,
                     UnidadeTramitacao)


def ANO_CHOICES():
    return [('', '---------')] + RANGE_ANOS


def em_tramitacao():
    return [('', 'Tanto Faz'),
            (True, 'Sim'),
            (False, 'Não')]


class ReceberProposicaoForm(Form):
    cod_hash = forms.CharField(label='Código do Documento', required=True)

    def __init__(self, *args, **kwargs):
        row1 = to_row([('cod_hash', 12)])
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                _('Incorporar Proposição'), row1,
                form_actions(save_label='Buscar Proposição')
            )
        )
        super(ReceberProposicaoForm, self).__init__(*args, **kwargs)


class UnidadeTramitacaoForm(ModelForm):

    class Meta:
        model = UnidadeTramitacao
        fields = ['comissao', 'orgao', 'parlamentar']

    def clean(self):
        cleaned_data = self.cleaned_data

        for key in list(cleaned_data.keys()):
            if cleaned_data[key] is None:
                del cleaned_data[key]

        if len(cleaned_data) != 1:
            msg = _('Somente um campo deve preenchido!')
            raise ValidationError(msg)
        return cleaned_data


class ProposicaoOldForm(ModelForm):

    tipo_materia = forms.ModelChoiceField(
        label=_('Matéria Vinculada'),
        required=False,
        queryset=TipoMateriaLegislativa.objects.all(),
        empty_label='Selecione',
    )

    numero_materia = forms.CharField(
        label='Número', required=False)

    ano_materia = forms.CharField(
        label='Ano', required=False)

    def clean_texto_original(self):
        texto_original = self.cleaned_data.get('texto_original', False)
        if texto_original:
            if texto_original.size > MAX_DOC_UPLOAD_SIZE:
                raise ValidationError("Arquivo muito grande. ( > 5mb )")
            return texto_original

    def clean_data_envio(self):
        data_envio = self.cleaned_data.get('data_envio') or None
        if (not data_envio) and len(self.initial) > 1:
            data_envio = datetime.now()
        return data_envio

    def clean(self):
        cleaned_data = self.cleaned_data
        if 'tipo' in cleaned_data:
            if cleaned_data['tipo'].descricao == 'Parecer':
                if self.instance.materia:
                    cleaned_data['materia'] = self.instance.materia
                else:
                    try:
                        materia = MateriaLegislativa.objects.get(
                            tipo_id=cleaned_data['tipo_materia'],
                            ano=cleaned_data['ano_materia'],
                            numero=cleaned_data['numero_materia'])
                    except ObjectDoesNotExist:
                        msg = _('Matéria adicionada não existe!')
                        raise ValidationError(msg)
                    else:
                        cleaned_data['materia'] = materia
        return cleaned_data

    def save(self, commit=False):
        proposicao = super(ProposicaoOldForm, self).save(commit)
        if 'materia' in self.cleaned_data:
            proposicao.materia = self.cleaned_data['materia']
        proposicao.save()
        return proposicao

    class Meta:
        model = Proposicao
        fields = ['tipo', 'data_envio', 'descricao', 'texto_original', 'autor']
        widgets = {'autor': forms.HiddenInput()}


class AcompanhamentoMateriaForm(ModelForm):

    class Meta:
        model = AcompanhamentoMateria
        fields = ['email']

    def __init__(self, *args, **kwargs):

        row1 = to_row([('email', 10)])

        row1.append(
            Column(form_actions(save_label='Cadastrar'), css_class='col-md-2')
        )

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                _('Acompanhamento de Matéria por e-mail'), row1
            )
        )
        super(AcompanhamentoMateriaForm, self).__init__(*args, **kwargs)


class DocumentoAcessorioForm(ModelForm):

    class Meta:
        model = DocumentoAcessorio
        fields = ['tipo', 'nome', 'data', 'autor', 'ementa', 'arquivo']
        widgets = {'autor': forms.HiddenInput()}

    def clean_autor(self):
        autor_field = self.cleaned_data['autor']
        try:
            int(autor_field)
        except ValueError:
            return autor_field
        else:
            if autor_field:
                return str(Autor.objects.get(id=autor_field))


class RelatoriaForm(ModelForm):

    class Meta:
        model = Relatoria
        fields = ['data_designacao_relator', 'comissao', 'parlamentar',
                  'data_destituicao_relator', 'tipo_fim_relatoria']

        widgets = {'comissao': forms.Select(attrs={'disabled': 'disabled'})}

    def __init__(self, *args, **kwargs):
        super(RelatoriaForm, self).__init__(*args, **kwargs)
        self.fields['parlamentar'].queryset = Parlamentar.objects.filter(
            ativo=True).order_by('nome_completo')

    def clean(self):
        cleaned_data = self.cleaned_data

        try:
            comissao = Comissao.objects.get(id=self.initial['comissao'])
        except ObjectDoesNotExist:
            msg = _('A localização atual deve ser uma comissão.')
            raise ValidationError(msg)
        else:
            cleaned_data['comissao'] = comissao

        return cleaned_data


class TramitacaoForm(ModelForm):

    class Meta:
        model = Tramitacao
        fields = ['data_tramitacao',
                  'unidade_tramitacao_local',
                  'status',
                  'turno',
                  'urgente',
                  'unidade_tramitacao_destino',
                  'data_encaminhamento',
                  'data_fim_prazo',
                  'texto']

    def __init__(self, *args, **kwargs):
        super(TramitacaoForm, self).__init__(*args, **kwargs)
        self.fields['data_tramitacao'].initial = datetime.now()

    def clean(self):

        if 'data_encaminhamento' in self.data:
            data_enc_form = self.cleaned_data['data_encaminhamento']
        if 'data_fim_prazo' in self.data:
            data_prazo_form = self.cleaned_data['data_fim_prazo']
        if 'data_tramitacao' in self.data:
            data_tram_form = self.cleaned_data['data_tramitacao']

        if self.errors:
            return self.errors

        ultima_tramitacao = Tramitacao.objects.filter(
            materia_id=self.instance.materia_id).exclude(
            id=self.instance.id).last()

        if not self.instance.data_tramitacao:

            if ultima_tramitacao:
                destino = ultima_tramitacao.unidade_tramitacao_destino
                if (destino != self.cleaned_data['unidade_tramitacao_local']):
                    msg = _('A origem da nova tramitação deve ser igual ao '
                            'destino  da última adicionada!')
                    raise ValidationError(msg)

            if self.cleaned_data['data_tramitacao'] > datetime.now().date():
                msg = _(
                    'A data de tramitação deve ser ' +
                    'menor ou igual a data de hoje!')
                raise ValidationError(msg)

            if (ultima_tramitacao and
                    data_tram_form < ultima_tramitacao.data_tramitacao):
                msg = _('A data da nova tramitação deve ser ' +
                        'maior que a data da última tramitação!')
                raise ValidationError(msg)

        if data_enc_form:
            if data_enc_form < data_tram_form:
                msg = _('A data de encaminhamento deve ser ' +
                        'maior que a data de tramitação!')
                raise ValidationError(msg)

        if data_prazo_form:
            if data_prazo_form < data_tram_form:
                msg = _('A data fim de prazo deve ser ' +
                        'maior que a data de tramitação!')
                raise ValidationError(msg)

        return self.cleaned_data


class TramitacaoUpdateForm(TramitacaoForm):
    unidade_tramitacao_local = forms.ModelChoiceField(
        queryset=UnidadeTramitacao.objects.all(),
        widget=forms.HiddenInput())

    data_tramitacao = forms.DateField(widget=forms.HiddenInput())

    class Meta:
        model = Tramitacao
        fields = ['data_tramitacao',
                  'unidade_tramitacao_local',
                  'status',
                  'turno',
                  'urgente',
                  'unidade_tramitacao_destino',
                  'data_encaminhamento',
                  'data_fim_prazo',
                  'texto',
                  ]

        widgets = {
            'data_encaminhamento': forms.DateInput(format='%d/%m/%Y'),
            'data_fim_prazo': forms.DateInput(format='%d/%m/%Y'),
        }

    def clean(self):
        local = self.instance.unidade_tramitacao_local
        data_tram = self.instance.data_tramitacao

        self.cleaned_data['data_tramitacao'] = data_tram
        self.cleaned_data['unidade_tramitacao_local'] = local
        return super(TramitacaoUpdateForm, self).clean()


class LegislacaoCitadaForm(ModelForm):

    tipo = forms.ModelChoiceField(
        label=_('Tipo Norma'),
        required=True,
        queryset=TipoNormaJuridica.objects.all(),
        empty_label='Selecione',
    )

    numero = forms.CharField(label='Número', required=True)

    ano = forms.CharField(label='Ano', required=True)

    class Meta:
        model = LegislacaoCitada
        fields = ['tipo',
                  'numero',
                  'ano',
                  'disposicoes',
                  'parte',
                  'livro',
                  'titulo',
                  'capitulo',
                  'secao',
                  'subsecao',
                  'artigo',
                  'paragrafo',
                  'inciso',
                  'alinea',
                  'item']

    def clean(self):
        if self.errors:
            return self.errors

        cleaned_data = self.cleaned_data

        try:
            norma = NormaJuridica.objects.get(
                numero=cleaned_data['numero'],
                ano=cleaned_data['ano'],
                tipo=cleaned_data['tipo'])
        except ObjectDoesNotExist:
            msg = _('A norma a ser inclusa não existe no cadastro'
                    ' de Normas.')
            raise ValidationError(msg)
        else:
            cleaned_data['norma'] = norma

        filtro_base = LegislacaoCitada.objects.filter(
            materia=self.instance.materia,
            norma=self.cleaned_data['norma'],
            disposicoes=self.cleaned_data['disposicoes'],
            parte=self.cleaned_data['parte'],
            livro=self.cleaned_data['livro'],
            titulo=self.cleaned_data['titulo'],
            capitulo=self.cleaned_data['capitulo'],
            secao=self.cleaned_data['secao'],
            subsecao=self.cleaned_data['subsecao'],
            artigo=self.cleaned_data['artigo'],
            paragrafo=self.cleaned_data['paragrafo'],
            inciso=self.cleaned_data['inciso'],
            alinea=self.cleaned_data['alinea'],
            item=self.cleaned_data['item'])

        if not self.instance.id:
            if filtro_base.exists():
                msg = _('Essa Legislação já foi cadastrada.')
                raise ValidationError(msg)
        else:
            if filtro_base.exclude(id=self.instance.id).exists():
                msg = _('Essa Legislação já foi cadastrada.')
                raise ValidationError(msg)
        return cleaned_data

    def save(self, commit=False):
        legislacao = super(LegislacaoCitadaForm, self).save(commit)

        legislacao.norma = self.cleaned_data['norma']
        legislacao.save()
        return legislacao


class NumeracaoForm(ModelForm):

    class Meta:
        model = Numeracao
        fields = ['tipo_materia',
                  'numero_materia',
                  'ano_materia',
                  'data_materia']

    def clean(self):
        if self.errors:
            return self.errors

        try:
            MateriaLegislativa.objects.get(
                numero=self.cleaned_data['numero_materia'],
                ano=self.cleaned_data['ano_materia'],
                tipo=self.cleaned_data['tipo_materia'])
        except ObjectDoesNotExist:
            msg = _('A matéria a ser inclusa não existe no cadastro'
                    ' de matérias legislativas.')
            raise ValidationError(msg)

        if Numeracao.objects.filter(
            materia=self.instance.materia,
            tipo_materia=self.cleaned_data['tipo_materia'],
            ano_materia=self.cleaned_data['ano_materia'],
            numero_materia=self.cleaned_data['numero_materia']
        ).exists():
            msg = _('Essa numeração já foi cadastrada.')
            raise ValidationError(msg)

        return self.cleaned_data


class AnexadaForm(ModelForm):

    tipo = forms.ModelChoiceField(
        label='Tipo',
        required=True,
        queryset=TipoMateriaLegislativa.objects.all(),
        empty_label='Selecione',
    )

    numero = forms.CharField(label='Número', required=True)

    ano = forms.CharField(label='Ano', required=True)

    def __init__(self, *args, **kwargs):

        return super(AnexadaForm, self).__init__(*args, **kwargs)

    def clean(self):
        if self.errors:
            return self.errors

        cleaned_data = self.cleaned_data

        try:
            materia_anexada = MateriaLegislativa.objects.get(
                numero=cleaned_data['numero'],
                ano=cleaned_data['ano'],
                tipo=cleaned_data['tipo'])
        except ObjectDoesNotExist:
            msg = _('A matéria a ser anexada não existe no cadastro'
                    ' de matérias legislativas.')
            raise ValidationError(msg)
        else:
            cleaned_data['materia_anexada'] = materia_anexada

        return cleaned_data

    def save(self, commit=False):
        anexada = super(AnexadaForm, self).save(commit)
        anexada.materia_anexada = self.cleaned_data['materia_anexada']
        anexada.save()
        return anexada

    class Meta:
        model = Anexada
        fields = ['tipo', 'numero', 'ano', 'data_anexacao', 'data_desanexacao']


class MateriaLegislativaFilterSet(django_filters.FilterSet):

    filter_overrides = {models.DateField: {
        'filter_class': django_filters.DateFromToRangeFilter,
        'extra': lambda f: {
            'label': '%s (%s)' % (f.verbose_name, _('Inicial - Final')),
            'widget': RangeWidgetOverride}
    }}

    ano = django_filters.ChoiceFilter(required=False,
                                      label=u'Ano da Matéria',
                                      choices=ANO_CHOICES)

    autoria__autor = django_filters.CharFilter(widget=forms.HiddenInput())

    ementa = django_filters.CharFilter(lookup_expr='icontains')

    em_tramitacao = django_filters.ChoiceFilter(required=False,
                                                label=u'Ano da Matéria',
                                                choices=em_tramitacao)

    class Meta:
        model = MateriaLegislativa
        fields = ['numero',
                  'numero_protocolo',
                  'ano',
                  'tipo',
                  'data_apresentacao',
                  'data_publicacao',
                  'autoria__autor__tipo',
                  # 'autoria__autor__partido',
                  'relatoria__parlamentar_id',
                  'local_origem_externa',
                  'tramitacao__unidade_tramitacao_destino',
                  'tramitacao__status',
                  'em_tramitacao',
                  ]

        order_by = (
            ('', 'Selecione'),
            ('dataC', 'Data, Tipo, Ano, Numero - Ordem Crescente'),
            ('dataD', 'Data, Tipo, Ano, Numero - Ordem Decrescente'),
            ('tipoC', 'Tipo, Ano, Numero, Data - Ordem Crescente'),
            ('tipoD', 'Tipo, Ano, Numero, Data - Ordem Decrescente')
        )

    order_by_mapping = {
        '': [],
        'dataC': ['data_apresentacao', 'tipo__sigla', 'ano', 'numero'],
        'dataD': ['-data_apresentacao', '-tipo__sigla', '-ano', '-numero'],
        'tipoC': ['tipo__sigla', 'ano', 'numero', 'data_apresentacao'],
        'tipoD': ['-tipo__sigla', '-ano', '-numero', '-data_apresentacao'],
    }

    def get_order_by(self, order_value):
        if order_value in self.order_by_mapping:
            return self.order_by_mapping[order_value]
        else:
            return super(MateriaLegislativaFilterSet,
                         self).get_order_by(order_value)

    def __init__(self, *args, **kwargs):
        super(MateriaLegislativaFilterSet, self).__init__(*args, **kwargs)

        self.filters['tipo'].label = 'Tipo de Matéria'
        self.filters['autoria__autor__tipo'].label = 'Tipo de Autor'
        # self.filters['autoria__autor__partido'].label = 'Partido do Autor'
        self.filters['relatoria__parlamentar_id'].label = 'Relatoria'

        row1 = to_row(
            [('tipo', 12)])
        row2 = to_row(
            [('numero', 4),
             ('ano', 4),
             ('numero_protocolo', 4)])
        row3 = to_row(
            [('data_apresentacao', 6),
             ('data_publicacao', 6)])
        row4 = to_row(
            [('autoria__autor', 0),
             (Button('pesquisar',
                     'Pesquisar Autor',
                     css_class='btn btn-primary btn-sm'), 2),
             (Button('limpar',
                     'limpar Autor',
                     css_class='btn btn-primary btn-sm'), 10)])
        row5 = to_row(
            [('autoria__autor__tipo', 12),
             # ('autoria__autor__partido', 6)
             ])
        row6 = to_row(
            [('relatoria__parlamentar_id', 6),
             ('local_origem_externa', 6)])
        row7 = to_row(
            [('tramitacao__unidade_tramitacao_destino', 6),
             ('tramitacao__status', 6)])
        row8 = to_row(
            [('em_tramitacao', 6),
             ('o', 6)])
        row9 = to_row(
            [('ementa', 12)])

        self.form.helper = FormHelper()
        self.form.helper.form_method = 'GET'
        self.form.helper.layout = Layout(
            Fieldset(_('Pesquisa de Matéria'),
                     row1, row2, row3,
                     HTML(autor_label),
                     HTML(autor_modal),
                     row4, row5, row6, row7, row8, row9,
                     form_actions(save_label='Pesquisar'))
        )


def pega_ultima_tramitacao():
    ultimas_tramitacoes = Tramitacao.objects.values(
        'materia_id').annotate(data_encaminhamento=Max(
            'data_encaminhamento'),
        id=Max('id')).values_list('id')

    lista = [item for sublist in ultimas_tramitacoes for item in sublist]

    return lista


def filtra_tramitacao_status(status):
    lista = pega_ultima_tramitacao()
    return Tramitacao.objects.filter(
        id__in=lista,
        status=status).distinct().values_list('materia_id', flat=True)


def filtra_tramitacao_destino(destino):
    lista = pega_ultima_tramitacao()
    return Tramitacao.objects.filter(
        id__in=lista,
        unidade_tramitacao_destino=destino).distinct().values_list(
            'materia_id', flat=True)


def filtra_tramitacao_destino_and_status(status, destino):
    lista = pega_ultima_tramitacao()
    return Tramitacao.objects.filter(
        id__in=lista,
        status=status,
        unidade_tramitacao_destino=destino).distinct().values_list(
            'materia_id', flat=True)


class DespachoInicialForm(ModelForm):

    class Meta:
        model = DespachoInicial
        fields = ['comissao']

    def clean(self):
        if self.errors:
            return self.errors

        if DespachoInicial.objects.filter(
            materia=self.instance.materia,
            comissao=self.cleaned_data['comissao'],
        ).exists():
            msg = _('Esse Despacho já foi cadastrado.')
            raise ValidationError(msg)

        return self.cleaned_data


class AutoriaForm(ModelForm):

    class Meta:
        model = Autoria
        fields = ['autor', 'primeiro_autor']

    def clean(self):
        if self.errors:
            return self.errors

        if Autoria.objects.filter(
            materia=self.instance.materia,
            autor=self.cleaned_data['autor'],
        ).exists():
            msg = _('Esse Autor já foi cadastrado.')
            raise ValidationError(msg)

        return self.cleaned_data


class AcessorioEmLoteFilterSet(django_filters.FilterSet):

    filter_overrides = {models.DateField: {
        'filter_class': django_filters.DateFromToRangeFilter,
        'extra': lambda f: {
            'label': '%s (%s)' % (f.verbose_name, _('Inicial - Final')),
            'widget': RangeWidgetOverride}
    }}

    class Meta:
        model = MateriaLegislativa
        fields = ['tipo', 'data_apresentacao']

    def __init__(self, *args, **kwargs):
        super(AcessorioEmLoteFilterSet, self).__init__(*args, **kwargs)

        self.filters['tipo'].label = 'Tipo de Matéria'
        self.filters['data_apresentacao'].label = 'Data (Inicial - Final)'
        self.form.fields['tipo'].required = True
        self.form.fields['data_apresentacao'].required = True

        row1 = to_row([('tipo', 12)])
        row2 = to_row([('data_apresentacao', 12)])

        self.form.helper = FormHelper()
        self.form.helper.form_method = 'GET'
        self.form.helper.layout = Layout(
            Fieldset(_('Documentos Acessórios em Lote'),
                     row1, row2, form_actions(save_label='Pesquisar')))


class PrimeiraTramitacaoEmLoteFilterSet(django_filters.FilterSet):

    filter_overrides = {models.DateField: {
        'filter_class': django_filters.DateFromToRangeFilter,
        'extra': lambda f: {
            'label': '%s (%s)' % (f.verbose_name, _('Inicial - Final')),
            'widget': RangeWidgetOverride}
    }}

    class Meta:
        model = MateriaLegislativa
        fields = ['tipo', 'data_apresentacao']

    def __init__(self, *args, **kwargs):
        super(PrimeiraTramitacaoEmLoteFilterSet, self).__init__(
            *args, **kwargs)

        self.filters['tipo'].label = 'Tipo de Matéria'
        self.filters['data_apresentacao'].label = 'Data (Inicial - Final)'
        self.form.fields['tipo'].required = True
        self.form.fields['data_apresentacao'].required = True

        row1 = to_row([('tipo', 12)])
        row2 = to_row([('data_apresentacao', 12)])

        self.form.helper = FormHelper()
        self.form.helper.form_method = 'GET'
        self.form.helper.layout = Layout(
            Fieldset(_('Primeira Tramitação'),
                     row1, row2, form_actions(save_label='Pesquisar')))


class TramitacaoEmLoteFilterSet(django_filters.FilterSet):

    filter_overrides = {models.DateField: {
        'filter_class': django_filters.DateFromToRangeFilter,
        'extra': lambda f: {
            'label': '%s (%s)' % (f.verbose_name, _('Inicial - Final')),
            'widget': RangeWidgetOverride}
    }}

    class Meta:
        model = MateriaLegislativa
        fields = ['tipo', 'data_apresentacao', 'tramitacao__status',
                  'tramitacao__unidade_tramitacao_destino']

    def __init__(self, *args, **kwargs):
        super(TramitacaoEmLoteFilterSet, self).__init__(
            *args, **kwargs)

        self.filters['tipo'].label = 'Tipo de Matéria'
        self.filters['data_apresentacao'].label = 'Data (Inicial - Final)'
        self.filters['tramitacao__unidade_tramitacao_destino'
                     ].label = 'Unidade Destino (Último Destino)'
        self.form.fields['tipo'].required = True
        self.form.fields['data_apresentacao'].required = True
        self.form.fields['tramitacao__status'].required = True
        self.form.fields[
            'tramitacao__unidade_tramitacao_destino'].required = True

        row1 = to_row([
            ('tipo', 4),
            ('tramitacao__unidade_tramitacao_destino', 4),
            ('tramitacao__status', 4)])
        row2 = to_row([('data_apresentacao', 12)])

        self.form.helper = FormHelper()
        self.form.helper.form_method = 'GET'
        self.form.helper.layout = Layout(
            Fieldset(_('Tramitação em Lote'),
                     row1, row2, form_actions(save_label='Pesquisar')))


class TipoProposicaoForm(ModelForm):

    conteudo = forms.ModelChoiceField(
        queryset=ContentType.objects.all(),
        label=TipoProposicao._meta.get_field('conteudo').verbose_name,
        required=True)

    tipo_conteudo_related_radio = ChoiceWithoutValidationField(
        label="Seleção de Tipo",
        required=False,
        widget=forms.RadioSelect())

    tipo_conteudo_related = forms.IntegerField(
        widget=forms.HiddenInput(),
        required=True)

    class Meta:
        model = TipoProposicao
        fields = ['descricao',
                  'conteudo',
                  'tipo_conteudo_related_radio',
                  'tipo_conteudo_related']

        widgets = {'tipo_conteudo_related': forms.HiddenInput()}

    def __init__(self, *args, **kwargs):

        tipo_select = Fieldset(TipoProposicao._meta.verbose_name,
                               to_column(('descricao', 5)),
                               to_column(('conteudo', 7)),
                               to_column(('tipo_conteudo_related_radio', 12)))

        self.helper = FormHelper()
        self.helper.layout = SaplFormLayout(tipo_select)

        super(TipoProposicaoForm, self).__init__(*args, **kwargs)

        content_types = ContentType.objects.get_for_models(
            *models_with_gr_for_model(TipoProposicao))

        self.fields['conteudo'].choices = [
            (ct.pk, ct) for k, ct in content_types.items()]
        self.fields['conteudo'].choices.sort(key=lambda x: str(x[1]))

        if self.instance.pk:
            self.fields[
                'tipo_conteudo_related'].initial = self.instance.object_id

    def clean(self):
        cd = self.cleaned_data

        conteudo = cd['conteudo']

        if 'tipo_conteudo_related' not in cd or not cd['tipo_conteudo_related']:
            raise ValidationError(
                _('Seleção de Tipo não definida'))

        if not conteudo.model_class().objects.filter(
                pk=cd['tipo_conteudo_related']).exists():
            raise ValidationError(
                _('O Registro definido (%s) não está na base de %s.'
                  ) % (cd['tipo_conteudo_related'], cd['q'], conteudo))

        return self.cleaned_data

    @transaction.atomic
    def save(self, commit=False):

        tipo_proposicao = super(TipoProposicaoForm, self).save(commit)

        assert tipo_proposicao.conteudo

        tipo_proposicao.tipo_conteudo_related = \
            tipo_proposicao.conteudo.model_class(
            ).objects.get(pk=self.cleaned_data['tipo_conteudo_related'])

        tipo_proposicao.save()

        return tipo_proposicao


class ProposicaoForm(forms.ModelForm):

    TIPO_TEXTO_CHOICE = [
        ('D', _('Arquivo Digital')),
        ('T', _('Texto Articulado'))
    ]

    tipo_materia = forms.ModelChoiceField(
        label=TipoMateriaLegislativa._meta.verbose_name,
        required=False,
        queryset=TipoMateriaLegislativa.objects.all(),
        empty_label='Selecione')

    numero_materia = forms.CharField(
        label='Número', required=False)

    ano_materia = forms.CharField(
        label='Ano', required=False)

    tipo_texto = forms.MultipleChoiceField(
        label=_('Tipo do Texto da Proposição'),
        required=False,
        choices=TIPO_TEXTO_CHOICE,
        widget=widgets.CheckboxSelectMultiple())

    materia_de_vinculo = forms.ModelChoiceField(
        queryset=MateriaLegislativa.objects.all(),
        widget=widgets.HiddenInput(),
        required=False)

    class Meta:
        model = Proposicao
        fields = ['tipo',
                  'descricao',
                  'texto_original',
                  'materia_de_vinculo',

                  'tipo_materia',
                  'numero_materia',
                  'ano_materia',
                  'tipo_texto']

        widgets = {
            'descricao': widgets.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        self.texto_articulado_proposicao = sapl.base.models.AppConfig.attr(
            'texto_articulado_proposicao')

        if not self.texto_articulado_proposicao:
            if 'tipo_texto' in self._meta.fields:
                self._meta.fields.remove('tipo_texto')
        else:
            if 'tipo_texto' not in self._meta.fields:
                self._meta.fields.append('tipo_texto')

        fields = [
            to_column((Fieldset(
                TipoProposicao._meta.verbose_name, Field('tipo')), 3)),
            Fieldset(_('Vincular a Matéria Legislativa Existente'),
                     to_column(('tipo_materia', 4)),
                     to_column(('numero_materia', 4)),
                     to_column(('ano_materia', 4))
                     ),

            to_column(
                (Alert('teste',
                       css_class="ementa_materia hidden alert-info",
                       dismiss=False), 12)),
            to_column(('descricao', 12)),
        ]

        if self.texto_articulado_proposicao:
            fields.append(
                to_column((InlineCheckboxes('tipo_texto'), 5)),)

        fields.append(to_column((
            'texto_original', 7 if self.texto_articulado_proposicao else 12)))

        self.helper = FormHelper()
        self.helper.layout = SaplFormLayout(*fields)

        super(ProposicaoForm, self).__init__(*args, **kwargs)

        if self.instance.pk:
            self.fields['tipo_texto'].initial = []
            if self.instance.texto_original:
                self.fields['tipo_texto'].initial.append('D')
            if self.texto_articulado_proposicao:
                if self.instance.texto_articulado.exists():
                    self.fields['tipo_texto'].initial.append('T')

            if self.instance.materia_de_vinculo:
                self.fields[
                    'tipo_materia'].initial = self.instance.materia_de_vinculo.tipo
                self.fields[
                    'numero_materia'].initial = self.instance.materia_de_vinculo.numero
                self.fields[
                    'ano_materia'].initial = self.instance.materia_de_vinculo.ano

    def clean_texto_original(self):
        texto_original = self.cleaned_data.get('texto_original', False)
        if texto_original:
            if texto_original.size > MAX_DOC_UPLOAD_SIZE:
                raise ValidationError("Arquivo muito grande. ( > 5mb )")
            return texto_original

    def clean(self):
        cd = self.cleaned_data

        tm, am, nm = (cd.get('tipo_materia', ''),
                      cd.get('ano_materia', ''),
                      cd.get('numero_materia', ''))

        if tm and am and nm:
            try:
                materia_de_vinculo = MateriaLegislativa.objects.get(
                    tipo_id=tm,
                    ano=am,
                    numero=nm
                )
            except ObjectDoesNotExist:
                raise ValidationError(_('Matéria Vinculada não existe!'))
            else:
                cd['materia_de_vinculo'] = materia_de_vinculo
        return cd

    def save(self, commit=True):

        if self.instance.pk:
            return super().save(commit)

        self.instance.ano = datetime.now().year
        numero__max = Proposicao.objects.filter(
            autor=self.instance.autor,
            ano=datetime.now().year).aggregate(Max('numero_proposicao'))
        numero__max = numero__max['numero_proposicao__max']
        self.instance.numero_proposicao = (
            numero__max + 1) if numero__max else 1

        self.instance.save()

        return self.instance


class ConfirmarProposicaoForm(ProposicaoForm):

    tipo_readonly = forms.CharField(
        label=TipoProposicao._meta.verbose_name,
        required=False, widget=widgets.TextInput(
            attrs={'readonly': 'readonly'}))

    autor_readonly = forms.CharField(
        label=Autor._meta.verbose_name,
        required=False, widget=widgets.TextInput(
            attrs={'readonly': 'readonly'}))

    justificativa_devolucao = forms.CharField(
        required=False, widget=widgets.Textarea(attrs={'rows': 5}))

    regime_tramitacao = forms.ModelChoiceField(
        required=False, queryset=RegimeTramitacao.objects.all())

    gerar_protocolo = forms.ChoiceField(
        label=_('Gerar Protocolo na incorporação?'),
        choices=YES_NO_CHOICES,
        widget=widgets.RadioSelect())

    numero_de_paginas = forms.IntegerField(required=False,
                                           label=_('Número de Páginas'),)

    class Meta:
        model = Proposicao
        fields = [
            'data_envio',
            'descricao',
            'justificativa_devolucao',
            'gerar_protocolo',
            'numero_de_paginas'
        ]
        widgets = {
            'descricao': widgets.Textarea(
                attrs={'readonly': 'readonly', 'rows': 4}),
            'data_envio':  widgets.DateTimeInput(
                attrs={'readonly': 'readonly'}),

        }

    def __init__(self, *args, **kwargs):

        self.proposicao_incorporacao_obrigatoria = \
            sapl.base.models.AppConfig.attr(
                'proposicao_incorporacao_obrigatoria')

        if self.proposicao_incorporacao_obrigatoria != 'C':
            self.gerar_protocolo.required = False
            if 'gerar_protocolo' in self._meta.fields:
                self._meta.fields.remove('gerar_protocolo')
        else:
            if 'gerar_protocolo' not in self._meta.fields:
                self._meta.fields.append('gerar_protocolo')
                self.gerar_protocolo.required = False  # FIXME True

        if self.proposicao_incorporacao_obrigatoria == 'N':
            if 'numero_de_paginas' in self._meta.fields:
                self._meta.fields.remove('numero_de_paginas')
        else:
            if 'numero_de_paginas' not in self._meta.fields:
                self._meta.fields.append('numero_de_paginas')

        # esta chamada isola o __init__ de ProposicaoForm
        super(ProposicaoForm, self).__init__(*args, **kwargs)

        fields = [
            Fieldset(
                _('Dados Básicos'),
                to_column(('tipo_readonly', 4)),
                to_column(('data_envio', 3)),
                to_column(('autor_readonly', 5)),
                to_column(('descricao', 12)))]

        fields.append(
            Fieldset(_('Vinculado a Matéria Legislativa'),
                     to_column(('tipo_materia', 3)),
                     to_column(('numero_materia', 2)),
                     to_column(('ano_materia', 2)),
                     to_column(
                (Alert(_('O responsável pela incorporação pode '
                         'alterar a anexação. Limpar os campos '
                         'de Vinculação gera um %s independente '
                         'sem anexação se for possível para esta '
                         'Proposição. Não sendo, a rotina de incorporação '
                         'não permitirá estes campos serem vazios.'
                         ) % self.instance.tipo.conteudo,
                       css_class="alert-info",
                       dismiss=False), 5)),
                to_column(
                (Alert('',
                       css_class="ementa_materia hidden alert-info",
                       dismiss=False), 12))))

        submit_incorporar = Submit('incorporar', _('Incorporar'))
        itens_incorporacao = ['regime_tramitacao']
        if self.proposicao_incorporacao_obrigatoria == 'C':
            itens_incorporacao.append(InlineRadios('gerar_protocolo'))

        if self.proposicao_incorporacao_obrigatoria != 'N':
            itens_incorporacao.append('numero_de_paginas')

        fields.append(
            Fieldset(
                _('Registro de Incorporação'),
                *[to_column((itens, 4)) for itens in itens_incorporacao],
                FormActions(submit_incorporar, css_class='pull-right')
            ))

        fields.append(
            Fieldset(
                _('Registro de Devolução'),
                'justificativa_devolucao',
                FormActions(Submit(
                    'devolver', _('Devolver'),
                    css_class='btn-danger'), css_class='pull-right')
            ))
        self.helper = FormHelper()
        self.helper.layout = Layout(*fields)

        self.fields['tipo_readonly'].initial = self.instance.tipo.descricao
        self.fields['autor_readonly'].initial = str(self.instance.autor)

        if self.instance.materia_de_vinculo:
            self.fields[
                'tipo_materia'].initial = self.instance.materia_de_vinculo.tipo
            self.fields[
                'numero_materia'].initial = self.instance.materia_de_vinculo.numero
            self.fields[
                'ano_materia'].initial = self.instance.materia_de_vinculo.ano

        if self.proposicao_incorporacao_obrigatoria == 'C':
            self.fields['gerar_protocolo'].initial = True

    def clean(self):
        if 'incorporar' in self.data:
            cd = ProposicaoForm.clean(self)

            # FIXME em caso de incorporação validar regime e numero de páginas

            if self.instance.tipo.conteudo.model_class() == TipoDocumento and\
                    not cd['materia_de_vinculo']:

                raise ValidationError(
                    _('Documentos não podem ser incorporados sem definir '
                      'para qual Matéria Legislativa ele se destina.'))

        elif 'devolver' in self.data:
            cd = self.cleaned_data

            if 'justificativa_devolucao' not in cd or\
                    not cd['justificativa_devolucao']:
                # TODO Implementar notificação ao autor por email
                raise ValidationError(
                    _('Adicione uma Justificativa para devolução.'))
        else:
            raise ValidationError(
                _('Dados de Confirmação invalidos.'))
        return cd

    def save(self, commit=False):
        # TODO Implementar workflow entre protocolo e autores
        cd = self.cleaned_data

        if 'devolver' in self.data:
            self.instance.data_devolucao = datetime.now()
            self.instance.data_recebimento = None
            self.instance.data_envio = None
            self.instance.save()
            return self.instance

        elif 'incorporar' in self.data:
            self.instance.justificativa_devolucao = ''
            self.instance.data_devolucao = None
            self.instance.data_recebimento = datetime.now()

        self.instance.save()

        """
        TipoProposicao possui conteúdo genérico para a modelegam de tipos
        relacionados e, a esta modelagem, qual o objeto que está associado.
        Porem, cada registro a ser gerado pode possuir uma estrutura diferente,
        é os casos básicos já implementados,
        TipoDocumento e TipoMateriaLegislativa, que são modelos utilizados
        em DocumentoAcessorio e MateriaLegislativa geradas,
        por sua vez a partir de uma Proposição.
        Portanto para estas duas e para outras implementações que possam surgir
        possuindo com matéria prima uma Proposição, dada sua estrutura,
        deverá contar também com uma implementação particular aqui no código
        abaixo.
        """

        proposicao = self.instance
        conteudo_gerado = None

        if self.instance.tipo.conteudo.model_class() == TipoMateriaLegislativa:
            numero__max = MateriaLegislativa.objects.filter(
                tipo=proposicao.tipo.tipo_conteudo_related,
                ano=datetime.now().year).aggregate(Max('numero'))
            numero__max = numero__max['numero__max']

            # dados básicos
            materia = MateriaLegislativa()
            materia.numero = (numero__max + 1) if numero__max else 1
            materia.tipo = proposicao.tipo.tipo_conteudo_related
            materia.ementa = proposicao.descricao
            materia.ano = datetime.now().year
            materia.data_apresentacao = datetime.now()
            materia.em_tramitacao = True
            materia.regime_tramitacao = cd['regime_tramitacao']
            materia.texto_original = File(
                proposicao.texto_original,
                os.path.basename(proposicao.texto_original.path))
            materia.texto_articulo = proposicao.texto_articulado
            materia.save()
            conteudo_gerado = materia

            # autoria
            autoria = Autoria()
            autoria.autor = proposicao.autor
            autoria.materia = materia
            autoria.primeiro_autor = True
            autoria.save()

            # Matéria de vinlculo
            if proposicao.materia_de_vinculo:
                anexada = Anexada()
                anexada.materia_principal = proposicao.materia_de_vinculo
                anexada.materia_anexada = materia
                anexada.data_anexacao = datetime.now()
                anexada.save()

        elif self.instance.tipo.conteudo.model_class() == TipoDocumento:

            # dados básicos
            doc = DocumentoAcessorio()
            doc.materia = proposicao.materia_de_vinculo
            """
            FIXME Esta forma de registrar autoria é falha.
            Dificilmente o usuário que possui perfil de Autor será o autor
            de um Documento Acessório.
            Solução pode passar pela parametrização em TipoProposicao que
            possibilite abrir ou não espaço, dado o Tipo, para quem está
            incorporando a proposição rediga o nome do Autor do Doc Acessório.

            """
            doc.autor = str(proposicao.autor)
            doc.tipo = proposicao.tipo.tipo_conteudo_related

            doc.ementa = proposicao.descricao
            """ FIXME verificar questão de nome e data de documento,
            doc acessório. Possivelmente pode possuir data anterior a
            data de envio e/ou recebimento dada a incorporação.
            """
            doc.nome = str(proposicao.tipo.tipo_conteudo_related)[:30]
            doc.data = proposicao.data_envio

            doc.arquivo = proposicao.texto_original = File(
                proposicao.texto_original,
                os.path.basename(proposicao.texto_original.path))
            doc.save()
            conteudo_gerado = doc

        proposicao.conteudo_gerado_related = conteudo_gerado
        proposicao.save()

        # Nunca gerar protocolo
        if self.proposicao_incorporacao_obrigatoria == 'N':
            return self.instance

        # ocorre se proposicao_incorporacao_obrigatoria == 'C' (condicional)
        # and gerar_protocolo == False
        if 'gerar_protocolo' in cd or not cd['gerar_protocolo']:
            return self.instance

        # resta a opção proposicao_incorporacao_obrigatoria == 'C'
        # and gerar_protocolo == True
        # ou, proposicao_incorporacao_obrigatoria == 'O'
        # que são idênticas.

        """
        apesar de TipoProposicao estar com conteudo e tipo conteudo genérico,
        aqui na incorporação de proposições, para gerar protocolo, cada caso
        possível de conteudo em tipo de proposição deverá ser tratado
        isoladamente justamente por Protocolo não estar generalizado com
        GenericForeignKey
        """

        # FIXME - Implementar protocolo
        # protocolo = Protocolo()
        # protocolo.ano =

        return self.instance
