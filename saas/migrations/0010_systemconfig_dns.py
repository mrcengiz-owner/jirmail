from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('saas', '0009_systemconfig_bootstrap_admin_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemconfig',
            name='dns_provider',
            field=models.CharField(
                default='manual',
                help_text='Kurulumda seçilen DNS sağlayıcı (cloudflare, route53, …)',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='systemconfig',
            name='dns_credentials',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Kurulumda girilen provider API token/anahtarları',
            ),
        ),
    ]
