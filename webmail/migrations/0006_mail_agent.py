"""AI ajan modelleri ve mesaj triage alanı."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_mail_role_webmail_default'),
        ('webmail', '0005_mailaitask'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailmessagecache',
            name='ai_meta',
            field=models.JSONField(blank=True, default=dict, help_text='AI triage: category, priority, summary…'),
        ),
        migrations.CreateModel(
            name='MailAgentProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mode', models.CharField(
                    choices=[('off', 'Kapalı'), ('assist', 'Asistan (öneri)'), ('autopilot', 'Otopilot (güvenli aksiyonlar)')],
                    db_index=True,
                    default='assist',
                    max_length=16,
                )),
                ('auto_triage', models.BooleanField(default=True)),
                ('auto_organize', models.BooleanField(default=True)),
                ('auto_reply_suggest', models.BooleanField(default=True)),
                ('digest_enabled', models.BooleanField(default=True)),
                ('digest_frequency', models.CharField(
                    choices=[('daily', 'Günlük'), ('weekly', 'Haftalık')],
                    default='daily',
                    max_length=16,
                )),
                ('digest_hour', models.PositiveSmallIntegerField(default=8, help_text='UTC saat (0-23)')),
                ('triage_batch_size', models.PositiveSmallIntegerField(default=15)),
                ('organize_batch_size', models.PositiveSmallIntegerField(default=25)),
                ('last_triage_at', models.DateTimeField(blank=True, null=True)),
                ('last_organize_at', models.DateTimeField(blank=True, null=True)),
                ('last_digest_at', models.DateTimeField(blank=True, null=True)),
                ('last_digest_text', models.TextField(blank=True, default='')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='agent_profile',
                    to='core.mailaccount',
                )),
            ],
        ),
        migrations.CreateModel(
            name='MailAiRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('enabled', models.BooleanField(db_index=True, default=True)),
                ('priority', models.PositiveSmallIntegerField(db_index=True, default=100)),
                ('match_from', models.CharField(blank=True, default='', max_length=255)),
                ('match_subject', models.CharField(blank=True, default='', max_length=255)),
                ('match_category', models.CharField(blank=True, default='', max_length=32)),
                ('action_type', models.CharField(
                    choices=[
                        ('spam', 'Spam'),
                        ('archive', 'Arşivle'),
                        ('mark_read', 'Okundu işaretle'),
                        ('move_folder', 'Klasöre taşı'),
                        ('star', 'Yıldızla'),
                        ('delete', 'Sil'),
                    ],
                    default='archive',
                    max_length=32,
                )),
                ('action_target', models.CharField(blank=True, default='', help_text='move_folder için hedef', max_length=255)),
                ('created_by_ai', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ai_rules',
                    to='core.mailaccount',
                )),
            ],
            options={
                'ordering': ['priority', 'id'],
            },
        ),
    ]
