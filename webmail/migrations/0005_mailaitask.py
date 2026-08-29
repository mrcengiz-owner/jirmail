"""Webmail AI görev modeli."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_mail_role_webmail_default'),
        ('webmail', '0004_mailmessagecache_sender_meta'),
    ]

    operations = [
        migrations.CreateModel(
            name='MailAiTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('instruction', models.TextField()),
                ('task_type', models.CharField(
                    choices=[
                        ('chat', 'Sohbet'),
                        ('analyze', 'Analiz'),
                        ('send', 'Gönder'),
                        ('reply', 'Yanıt'),
                        ('custom', 'Özel'),
                    ],
                    db_index=True,
                    default='custom',
                    max_length=16,
                )),
                ('context', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Beklemede'),
                        ('running', 'Çalışıyor'),
                        ('done', 'Tamamlandı'),
                        ('failed', 'Başarısız'),
                        ('cancelled', 'İptal'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=16,
                )),
                ('result', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('account', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ai_tasks',
                    to='core.mailaccount',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
