from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('saas', '0008_systemconfig_docker_container_map'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemconfig',
            name='bootstrap_admin_email',
            field=models.EmailField(
                blank=True,
                default='',
                help_text='Kurulumda oluşturulan süper yönetici e-postası (değiştirilemez işaret)',
            ),
        ),
    ]
