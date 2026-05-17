# Generated manually for outbound delivery tracking
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('webmail', '0001_initial'),
        ('core', '0009_maildomain_dns_credentials_maildomain_dns_provider_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='MailOutboundLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('to_addr', models.TextField()),
                ('subject', models.CharField(blank=True, default='', max_length=998)),
                ('snippet', models.CharField(blank=True, default='', max_length=500)),
                ('message_id', models.CharField(blank=True, db_index=True, default='', max_length=512)),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('pending', 'Beklemede'),
                            ('sent', 'Gönderildi'),
                            ('failed', 'Başarısız'),
                            ('deferred', 'Ertelendi'),
                        ],
                        db_index=True,
                        default='pending',
                        max_length=16,
                    ),
                ),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    'account',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='outbound_logs',
                        to='core.mailaccount',
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
