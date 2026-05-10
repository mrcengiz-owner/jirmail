from ninja import Router, Schema
from django.conf import settings
from core.models import Backup, MailAccount, MailDomain
from datetime import datetime, timedelta
import os
import subprocess
import tarfile
import json
import shutil

router = Router()


class BackupConfigSchema(Schema):
    backup_type: str
    include_emails: bool = False
    include_configs: bool = False
    include_database: bool = True


class RestoreConfigSchema(Schema):
    backup_id: int
    restore_emails: bool = True
    restore_configs: bool = True
    restore_database: bool = True


class BackupListSchema(Schema):
    id: int
    name: str
    backup_type: str
    status: str
    file_path: str
    file_size_mb: float
    created_at: str
    includes_emails: bool
    includes_configs: bool
    includes_database: bool


def get_backup_directory():
    backup_dir = getattr(settings, 'BACKUP_DIR', None)
    if not backup_dir:
        try:
            from saas.models import SystemConfig
            config = SystemConfig.objects.first()
            if config:
                backup_dir = config.backup_dir
        except Exception:
            pass
    if not backup_dir:
        backup_dir = '/var/backups/jirmail'
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def create_database_dump(backup_dir):
    db_config_path = settings.BASE_DIR / 'config' / 'db_config.json'
    if not os.path.exists(db_config_path):
        return False, "Veritabanı konfigürasyonu bulunamadı"

    with open(db_config_path, 'r') as f:
        db_config = json.load(f)

    db_engine = db_config.get('ENGINE', '')
    dump_file = os.path.join(backup_dir, 'database.sql')

    try:
        if 'sqlite' in db_engine:
            shutil.copy2(str(settings.BASE_DIR / 'db.sqlite3'), dump_file)
            return True, dump_file
        elif 'postgres' in db_engine:
            host = db_config.get('HOST', 'localhost')
            port = db_config.get('PORT', 5432)
            name = db_config.get('NAME', 'jirmail')
            user = db_config.get('USER', 'postgres')
            password = db_config.get('PASSWORD', '')

            env = os.environ.copy()
            env['PGPASSWORD'] = password

            result = subprocess.run(
                ['pg_dump', '-h', host, '-p', str(port), '-U', user, '-f', dump_file, name],
                capture_output=True, text=True, env=env
            )
            if result.returncode != 0:
                return False, f"pg_dump hatası: {result.stderr}"
            return True, dump_file
    except Exception as e:
        return False, str(e)

    return False, "Desteklenmeyen veritabanı türü"


def create_email_backup(backup_dir):
    mail_root = getattr(settings, 'POSTFIX_MAIL_ROOT', '/var/mail/vhosts')
    if not os.path.exists(mail_root):
        return False, "Mail dizini bulunamadı"

    email_backup = os.path.join(backup_dir, 'emails.tar.gz')
    try:
        with tarfile.open(email_backup, 'w:gz') as tar:
            for domain in MailDomain.objects.filter(is_active=True):
                domain_path = os.path.join(mail_root, domain.name)
                if os.path.exists(domain_path):
                    tar.add(domain_path, arcname=f"vhosts/{domain.name}")

        file_size = os.path.getsize(email_backup) / (1024 * 1024)
        return True, {'path': email_backup, 'size_mb': file_size}
    except Exception as e:
        return False, str(e)


def create_config_backup(backup_dir):
    config_files = [
        settings.BASE_DIR / 'config' / 'db_config.json',
        settings.BASE_DIR / '.env',
    ]

    config_backup = os.path.join(backup_dir, 'configs.tar.gz')
    try:
        with tarfile.open(config_backup, 'w:gz') as tar:
            for config_file in config_files:
                if os.path.exists(config_file):
                    tar.add(config_file, arcname=os.path.basename(config_file))

        file_size = os.path.getsize(config_backup) / (1024 * 1024)
        return True, {'path': config_backup, 'size_mb': file_size}
    except Exception as e:
        return False, str(e)


@router.post("/create-backup", summary="Yedekleme Oluştur")
def create_backup(request, data: BackupConfigSchema):
    try:
        backup_dir = get_backup_directory()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        backup = Backup.objects.create(
            name=f"Backup_{timestamp}",
            backup_type=data.backup_type,
            status='running',
            includes_emails=data.include_emails,
            includes_configs=data.include_configs,
            includes_database=data.include_database,
        )

        session_backup_dir = os.path.join(backup_dir, f"backup_{backup.id}")
        os.makedirs(session_backup_dir, exist_ok=True)

        results = {'database': False, 'emails': False, 'configs': False}
        total_size = 0

        if data.include_database:
            success, result = create_database_dump(session_backup_dir)
            results['database'] = success
            if success and isinstance(result, str):
                total_size += os.path.getsize(result) / (1024 * 1024)

        if data.include_emails:
            success, result = create_email_backup(session_backup_dir)
            results['emails'] = success
            if success and isinstance(result, dict):
                total_size += result['size_mb']

        if data.include_configs:
            success, result = create_config_backup(session_backup_dir)
            results['configs'] = success
            if success and isinstance(result, dict):
                total_size += result['size_mb']

        archive_path = os.path.join(backup_dir, f"jirmail_backup_{backup.id}.tar.gz")
        with tarfile.open(archive_path, 'w:gz') as tar:
            tar.add(session_backup_dir, arcname='backup')

        shutil.rmtree(session_backup_dir)

        backup.file_path = archive_path
        backup.file_size_mb = round(total_size, 2)
        backup.status = 'completed'
        backup.completed_at = datetime.now()
        backup.save()

        return {
            "status": "success",
            "backup_id": backup.id,
            "file_path": archive_path,
            "file_size_mb": round(total_size, 2),
            "results": results
        }

    except Exception as e:
        if 'backup' in locals():
            backup.status = 'failed'
            backup.error_message = str(e)
            backup.save()
        return {
            "status": "error",
            "message": f"Yedekleme hatası: {str(e)}"
        }


def create_backup_logic(backup_type='full', include_emails=False, include_configs=True, include_database=True):
    """
    Celery task'tan çağrılabilen backup oluşturma fonksiyonu.
    """
    try:
        backup_dir = get_backup_directory()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        backup = Backup.objects.create(
            name=f"Auto_Backup_{timestamp}",
            backup_type=backup_type,
            status='running',
            includes_emails=include_emails,
            includes_configs=include_configs,
            includes_database=include_database,
            is_auto_backup=True,
        )

        session_backup_dir = os.path.join(backup_dir, f"backup_{backup.id}")
        os.makedirs(session_backup_dir, exist_ok=True)

        results = {'database': False, 'emails': False, 'configs': False}
        total_size = 0

        if include_database:
            success, result = create_database_dump(session_backup_dir)
            results['database'] = success
            if success and isinstance(result, str):
                total_size += os.path.getsize(result) / (1024 * 1024)

        if include_emails:
            success, result = create_email_backup(session_backup_dir)
            results['emails'] = success
            if success and isinstance(result, dict):
                total_size += result['size_mb']

        if include_configs:
            success, result = create_config_backup(session_backup_dir)
            results['configs'] = success
            if success and isinstance(result, dict):
                total_size += result['size_mb']

        archive_path = os.path.join(backup_dir, f"jirmail_backup_{backup.id}.tar.gz")
        with tarfile.open(archive_path, 'w:gz') as tar:
            tar.add(session_backup_dir, arcname='backup')

        shutil.rmtree(session_backup_dir)

        backup.file_path = archive_path
        backup.file_size_mb = round(total_size, 2)
        backup.status = 'completed'
        backup.completed_at = datetime.now()
        backup.save()

        return {
            "status": "success",
            "backup_id": backup.id,
            "file_path": archive_path,
            "file_size_mb": round(total_size, 2)
        }

    except Exception as e:
        if 'backup' in locals():
            backup.status = 'failed'
            backup.error_message = str(e)
            backup.save()
        return {
            "status": "error",
            "message": f"Yedekleme hatası: {str(e)}"
        }


@router.get("/list-backups", response={200: list[BackupListSchema]}, summary="Yedekleri Listele")
def list_backups(request):
    backups = Backup.objects.all()[:50]
    return [
        {
            "id": b.id,
            "name": b.name,
            "backup_type": b.backup_type,
            "status": b.status,
            "file_path": b.file_path,
            "file_size_mb": b.file_size_mb,
            "created_at": b.created_at.isoformat(),
            "includes_emails": b.includes_emails,
            "includes_configs": b.includes_configs,
            "includes_database": b.includes_database,
        }
        for b in backups
    ]


@router.post("/restore-backup", summary="Yedekten Geri Yükle")
def restore_backup(request, data: RestoreConfigSchema):
    try:
        backup = Backup.objects.get(id=data.backup_id)
        if backup.status != 'completed':
            return {"status": "error", "message": "Tamamlanmış yedek seçin"}

        backup_dir = get_backup_directory()
        archive_path = backup.file_path

        if not os.path.exists(archive_path):
            return {"status": "error", "message": "Yedek dosyası bulunamadı"}

        restore_dir = os.path.join(backup_dir, f"restore_{backup.id}")
        os.makedirs(restore_dir, exist_ok=True)

        try:
            with tarfile.open(archive_path, 'r:gz') as tar:
                tar.extractall(restore_dir)
        except Exception as e:
            return {"status": "error", "message": f"Arşiv açma hatası: {str(e)}"}

        results = {}

        if data.restore_database:
            db_dump = os.path.join(restore_dir, 'backup', 'database.sql')
            if os.path.exists(db_dump):
                db_config_path = settings.BASE_DIR / 'config' / 'db_config.json'
                with open(db_config_path, 'r') as f:
                    db_config = json.load(f)

                if 'sqlite' in db_config.get('ENGINE', ''):
                    shutil.copy2(db_dump, str(settings.BASE_DIR / 'db.sqlite3'))
                    results['database'] = 'restored'
                elif 'postgres' in db_config.get('ENGINE', ''):
                    results['database'] = 'requires_manual_postgres'
                else:
                    results['database'] = 'unknown_engine'
            else:
                results['database'] = 'not_found_in_backup'

        if data.restore_configs:
            config_files = ['db_config.json']
            for cf in config_files:
                src = os.path.join(restore_dir, 'backup', cf)
                if os.path.exists(src):
                    shutil.copy2(src, settings.BASE_DIR / 'config' / cf)
                    results['configs'] = 'restored'

        if data.restore_emails:
            emails_tar = os.path.join(restore_dir, 'backup', 'emails.tar.gz')
            mail_root = getattr(settings, 'POSTFIX_MAIL_ROOT', '/var/mail/vhosts')
            if os.path.exists(emails_tar):
                with tarfile.open(emails_tar, 'r:gz') as tar:
                    tar.extractall(mail_root)
                results['emails'] = 'restored'

        shutil.rmtree(restore_dir)

        return {
            "status": "success",
            "message": "Geri yükleme tamamlandı",
            "results": results
        }

    except Backup.DoesNotExist:
        return {"status": "error", "message": "Yedek bulunamadı"}
    except Exception as e:
        return {"status": "error", "message": f"Geri yükleme hatası: {str(e)}"}


@router.delete("/delete-backup/{backup_id}", summary="Yedek Sil")
def delete_backup(request, backup_id: int):
    try:
        backup = Backup.objects.get(id=backup_id)
        if backup.file_path and os.path.exists(backup.file_path):
            os.remove(backup.file_path)
        backup.delete()
        return {"status": "success", "message": "Yedek silindi"}
    except Backup.DoesNotExist:
        return {"status": "error", "message": "Yedek bulunamadı"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/schedule-backup", summary="Otomatik Yedekleme Planla")
def schedule_backup(request, data: BackupConfigSchema):
    try:
        backup = Backup.objects.create(
            name=f"Auto_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            backup_type=data.backup_type,
            status='pending',
            includes_emails=data.include_emails,
            includes_configs=data.include_configs,
            includes_database=data.include_database,
            is_auto_backup=True,
            scheduled_for=datetime.now() + timedelta(hours=1)
        )
        return {
            "status": "success",
            "message": "Otomatik yedekleme planlandı",
            "backup_id": backup.id
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}