# -*- coding: utf-8 -*-
# Generated by Django 1.11.24 on 2019-09-24 11:30
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('compilacao', '0012_bug_auto_inserido'),
    ]

    operations = [
        migrations.AlterField(
            model_name='textoarticulado',
            name='editable_only_by_owners',
            field=models.BooleanField(choices=[(True, 'Sim'), (False, 'Não')], default=True,
                                      verbose_name='Editável apenas pelos donos do Texto Articulado?'),
        ),
        migrations.AlterField(
            model_name='textoarticulado',
            name='editing_locked',
            field=models.BooleanField(choices=[(
                True, 'Sim'), (False, 'Não')], default=True, verbose_name='Texto Articulado em Edição?'),
        ),
    ]
