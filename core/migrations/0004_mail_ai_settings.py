from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_mailaccount_options_alter_maildomain_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='maildomain',
            name='ai_enabled',
            field=models.BooleanField(default=False, help_text='Domain için AI asistan (sunucu anahtarı)'),
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
            field=models.TextField(blank=True, default='Sen profesyonel bir e-posta asistanısın. Kısa ve net yaz.'),
        ),
        migrations.AddField(
            model_name='mailaccount',
            name='ai_enabled',
            field=models.BooleanField(default=False, help_text='Hesap AI kullanabilir (domain de açık olmalı)'),
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
            field=models.CharField(blank=True, default='', max_length=512, help_text='OpenRouter vb. — hesaba özel'),
        ),
        migrations.AddField(
            model_name='mailaccount',
            name='ai_system_prompt',
            field=models.TextField(blank=True, default=''),
        ),
    ]
