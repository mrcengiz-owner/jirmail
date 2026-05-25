from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='MailRepairRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(db_index=True, max_length=64)),
                ('actor_email', models.CharField(blank=True, default='', max_length=254)),
                ('ok', models.BooleanField(default=False)),
                ('summary', models.CharField(blank=True, default='', max_length=500)),
                ('report', models.JSONField(blank=True, default=dict)),
                ('ip_address', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'verbose_name': 'Mail onarım kaydı',
                'verbose_name_plural': 'Mail onarım kayıtları',
                'ordering': ['-created_at'],
            },
        ),
    ]
