from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_mail_ai_settings'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mailaccount',
            name='role',
            field=models.CharField(
                choices=[
                    ('FULL', 'Süper Yönetici'),
                    ('USER', 'Webmail Kullanıcısı'),
                    ('SEND', 'Sadece Gönderme'),
                    ('RECV', 'Sadece Alma'),
                    ('BLOCK', 'Şirket İçi'),
                ],
                default='USER',
                max_length=10,
            ),
        ),
    ]
