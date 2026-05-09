# Generated manually for Jîr-Mail Quota & Role Management

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailaccount',
            name='quota_bytes',
            field=models.BigIntegerField(default=52428800, help_text='Kota bayt cinsinden (50MB = 52428800, 0 = sınırsız)'),
        ),
        migrations.AddField(
            model_name='mailaccount',
            name='role',
            field=models.CharField(
                choices=[('FULL', 'Tam Erişim'), ('SEND', 'Sadece Gönderme'), ('RECV', 'Sadece Alma'), ('BLOCK', 'Şirket İçi')],
                default='FULL',
                max_length=10
            ),
        ),
    ]