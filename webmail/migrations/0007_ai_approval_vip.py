"""Onay kuyruğu ve VIP gönderenler."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_mail_role_webmail_default'),
        ('webmail', '0006_mail_agent'),
    ]

    operations = [
        migrations.CreateModel(
            name='MailVipSender',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pattern', models.CharField(help_text='E-posta veya @domain.com', max_length=255)),
                ('label', models.CharField(blank=True, default='', max_length=120)),
                ('enabled', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='vip_senders',
                    to='core.mailaccount',
                )),
            ],
            options={
                'ordering': ['pattern'],
            },
        ),
        migrations.CreateModel(
            name='MailAiPendingAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uid', models.PositiveIntegerField()),
                ('folder', models.CharField(default='INBOX', max_length=255)),
                ('action_type', models.CharField(max_length=32)),
                ('action_target', models.CharField(blank=True, default='', max_length=255)),
                ('subject', models.CharField(blank=True, default='', max_length=998)),
                ('from_addr', models.CharField(blank=True, default='', max_length=500)),
                ('reason', models.TextField(blank=True, default='')),
                ('source', models.CharField(default='ai', max_length=16)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Beklemede'),
                        ('approved', 'Onaylandı'),
                        ('rejected', 'Reddedildi'),
                        ('applied', 'Uygulandı'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=16,
                ),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('account', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ai_pending_actions',
                    to='core.mailaccount',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
