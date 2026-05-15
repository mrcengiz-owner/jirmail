# Generated manually for docker_container_map

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('saas', '0007_systemconfig_installation_log'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemconfig',
            name='docker_container_map',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Örn. {"postfix":"stack-postfix-abc","dovecot":"stack-dovecot-xyz"}',
            ),
        ),
    ]
