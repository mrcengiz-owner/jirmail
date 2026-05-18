from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('webmail', '0003_scheduled_mail'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailmessagecache',
            name='sender_meta',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
