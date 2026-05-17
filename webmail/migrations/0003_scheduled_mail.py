from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_mail_ai_settings'),
        ('webmail', '0002_mailoutboundlog'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScheduledMail',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('to_addr', models.TextField()),
                ('cc_addr', models.TextField(blank=True, default='')),
                ('bcc_addr', models.TextField(blank=True, default='')),
                ('subject', models.CharField(blank=True, default='', max_length=998)),
                ('body_text', models.TextField(blank=True, default='')),
                ('body_html', models.TextField(blank=True, default='')),
                ('attachments_meta', models.JSONField(blank=True, default=list)),
                ('send_at', models.DateTimeField(db_index=True)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Beklemede'),
                        ('sent', 'Gönderildi'),
                        ('failed', 'Başarısız'),
                        ('cancelled', 'İptal'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=16,
                )),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('account', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='scheduled_mails',
                    to='core.mailaccount',
                )),
            ],
            options={
                'ordering': ['send_at'],
            },
        ),
    ]
