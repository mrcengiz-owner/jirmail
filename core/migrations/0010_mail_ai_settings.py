# AI alanları — 0009 sonrası (0004 numarası repo'da zaten kullanılıyor)
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_maildomain_dns_credentials_maildomain_dns_provider_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='maildomain',
            name='ai_enabled',
            field=models.BooleanField(default=False, help_text='Domain için AI asistan'),
        ),
        migrations.AddField(
            model_name='maildomain',
            name='ai_provider',
            field=models.CharField(default='openrouter', max_length=32),
        ),
        migrations.AddField(
            model_name='maildomain',
            name='ai_default_model',
            field=models.CharField(blank=True, default='openai/gpt-4o-mini', max_length=128),
        ),
        migrations.AddField(
            model_name='maildomain',
            name='ai_system_prompt_default',
            field=models.TextField(
                blank=True,
                default='Sen profesyonel bir e-posta asistanısın. Türkçe, kısa ve net yaz.',
            ),
        ),
        migrations.AddField(
            model_name='mailaccount',
            name='ai_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='mailaccount',
            name='ai_provider',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='mailaccount',
            name='ai_model',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='mailaccount',
            name='ai_api_key',
            field=models.CharField(blank=True, default='', max_length=512),
        ),
        migrations.AddField(
            model_name='mailaccount',
            name='ai_system_prompt',
            field=models.TextField(blank=True, default=''),
        ),
    ]
