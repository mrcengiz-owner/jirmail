from django.apps import AppConfig


class ManagementConfig(AppConfig):
    name = 'management'

    def ready(self) -> None:
        try:
            from management.mail_tls import bootstrap_mail_tls_ca_from_db

            bootstrap_mail_tls_ca_from_db()
        except Exception:
            pass
