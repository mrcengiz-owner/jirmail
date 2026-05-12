from ninja import Router, Schema
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from core.models import MailAccount, MailDomain
from saas.models import SystemConfig
import bcrypt
import psutil
import os
import re
import subprocess
import dj_database_url
from datetime import datetime


router = Router()


class HealthStatusSchema(Schema):
    status: str
    database: bool
    postfix: bool
    dovecot: bool


class LoginSchema(Schema):
    email: str
    password: str


@router.post("/login", summary="Admin Girişi")
@csrf_exempt
def admin_login(request, data: LoginSchema):
    try:
        account = MailAccount.objects.filter(email=data.email.lower()).first()
        if not account:
            return {"status": "error", "message": "Invalid email or password"}

        if not bcrypt.checkpw(data.password.encode('utf-8'), account.password_hash.encode('utf-8')):
            return {"status": "error", "message": "Invalid email or password"}

        if not account.is_active:
            return {"status": "error", "message": "Account is inactive"}

        config = SystemConfig.objects.first()
        jir_key = config.jir_local_key if config else getattr(settings, 'JIR_LOCAL_KEY', 'JirCode_Alpha_2026_Secure_Key_v1')

        return {
            "status": "success",
            "message": "Login successful",
            "jir_key": jir_key,
            "email": account.email,
            "role": account.role
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Login error: {str(e)}"
        }


@router.get("/health", response={200: HealthStatusSchema}, summary="Sistem Sağlığı")
def health_check(request):
    checks = {
        'database': False,
        'postfix': False,
        'dovecot': False,
    }

    try:
        connection.ensure_connection()
        checks['database'] = True
    except Exception:
        pass

    vmail_path = getattr(settings, 'POSTFIX_VMAIL_PATH', '/etc/postfix/vmail_accounts')
    if os.path.exists(vmail_path):
        try:
            result = subprocess.run(['postmap', '-q', 'test', vmail_path], capture_output=True, timeout=5)
            checks['postfix'] = result.returncode == 0
        except Exception:
            pass

    dovecot_socket = '/var/run/dovecot/auth-login'
    if os.path.exists(dovecot_socket) or os.path.exists('/var/run/dovecot'):
        checks['dovecot'] = True

    all_healthy = all(checks.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "database": checks['database'],
        "postfix": checks['postfix'],
        "dovecot": checks['dovecot'],
    }


class TestDbSchema(Schema):
    db_type: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_pass: str


class SetupCompleteSchema(Schema):
    domain: str
    admin_email: str
    admin_password: str
    instance_id: str
    jir_local_key: str
    db_type: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_pass: str


@router.post("/test-db", summary="Veritabanı Bağlantı Testi")
def test_db(request, data: TestDbSchema):
    try:
        if data.db_type == 'sqlite':
            return {
                "status": "success",
                "message": "SQLite bağlantısı başarılı",
                "db_type": "sqlite"
            }

        import psycopg2
        conn = psycopg2.connect(
            host=data.db_host,
            port=data.db_port or 5432,
            user=data.db_user,
            password=data.db_pass,
            database=data.db_name,
            connect_timeout=10
        )
        conn.close()

        return {
            "status": "success",
            "message": "PostgreSQL bağlantısı başarılı",
            "db_type": "postgresql"
        }
    except ImportError as e:
        return {
            "status": "error",
            "message": f"PostgreSQL sürücüsü bulunamadı: {str(e)}",
            "syntax": "pip install psycopg2-binary"
        }
    except psycopg2.OperationalError as e:
        error_msg = str(e).strip()
        return {
            "status": "error",
            "message": f"Bağlantı hatası: {error_msg}",
            "syntax": f"psql -h {data.db_host} -p {data.db_port or 5432} -U {data.db_user} -d {data.db_name}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Beklenmeyen hata: {str(e)}",
            "syntax": "Hata detayı için sunucu loglarını kontrol edin."
        }


@router.post("/setup-complete", summary="Kurulum Tamamla")
def setup_complete(request, data: SetupCompleteSchema):
    from django.db import transaction
    try:
        existing_config = None
        try:
            existing_config = SystemConfig.objects.first()
            if existing_config and existing_config.is_installed:
                return {"status": "error", "message": "Sistem zaten kurulmuş!"}
        except:
            pass

        if data.db_type == 'postgresql':
            import psycopg2
            conn = psycopg2.connect(
                host=data.db_host,
                port=data.db_port or 5432,
                user=data.db_user,
                password=data.db_pass,
                database=data.db_name,
                connect_timeout=10
            )
            conn.close()

        db_engine = 'django.db.backends.postgresql' if data.db_type == 'postgresql' else 'django.db.backends.sqlite3'

        from django.core.management import call_command
        call_command('makemigrations', 'saas', 'core', '--noinput', verbosity=0)
        call_command('migrate', '--noinput', verbosity=0)

        salt = bcrypt.gensalt()
        hashed_pw = bcrypt.hashpw(data.admin_password.encode('utf-8'), salt).decode('utf-8')

        domain_obj, _ = MailDomain.objects.get_or_create(name=data.domain)

        admin_account = MailAccount.objects.create(
            domain=domain_obj,
            username=data.admin_email.split('@')[0],
            email=data.admin_email.lower(),
            password_hash=hashed_pw,
            role='FULL'
        )

        with transaction.atomic():
            config = existing_config if existing_config else SystemConfig()
            config.instance_id = data.instance_id
            config.is_installed = True
            config.jir_local_key = data.jir_local_key

            config.db_engine = db_engine
            if data.db_type == 'postgresql':
                config.db_host = data.db_host
                config.db_port = data.db_port or 5432
                config.db_name = data.db_name
                config.db_user = data.db_user
                config.db_password = data.db_pass

            config.save()
            config.refresh_from_db()

        # Flag file creation with portable path
        installed_flag_path = os.path.join(settings.BASE_DIR, 'config', '.installed')
        os.makedirs(os.path.dirname(installed_flag_path), exist_ok=True)
        with open(installed_flag_path, 'w') as f:
            f.write(str(config.instance_id))

        # .env update with portable path
        env_file = os.path.join(settings.BASE_DIR, '.env')
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                env_lines = f.readlines()
            with open(env_file, 'w') as f:
                for line in env_lines:
                    if line.startswith('INSTALLED='):
                        continue
                    f.write(line)
            with open(env_file, 'a') as f:
                f.write('INSTALLED=True\n')

        from django.db import connection
        connection.close()

        return {
            "status": "success",
            "message": "Kurulum tamamlandı!",
            "instance_id": str(config.instance_id)
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "message": f"Kurulum hatası: {str(e)}",
            "syntax": traceback.format_exc()
        }


class DockerContainerStatsSchema(Schema):
    container_id: str
    container_name: str
    cpu_percent: float
    ram_percent: float
    ram_usage_mb: float
    ram_limit_mb: float
    network_rx_mb: float
    network_tx_mb: float
    disk_usage_mb: float


class SystemSpecsSchema(Schema):
    cpu_percent: float
    ram_percent: float
    ram_total_gb: float
    ram_used_gb: float
    disk_percent: float
    disk_total_gb: float
    disk_used_gb: float
    docker_containers: list
    total_container_cpu: float
    total_container_ram_mb: float


class ServiceStatusSchema(Schema):
    name: str
    status: str
    port: int = None


class SystemRequirementsSchema(Schema):
    status: str
    ram_ok: bool
    ram_total_gb: float
    ram_required_gb: float
    disk_ok: bool
    disk_free_gb: float
    disk_required_gb: float
    ports_ok: list
    ports_blocked: list
    services: list


def check_port_available(port):
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('localhost', port))
            return result != 0
    except:
        return False


@router.get("/system-requirements", response={200: SystemRequirementsSchema}, summary="Sistem Gereksinimleri Kontrol")
def check_system_requirements(request):
    import socket

    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    required_ports = [25, 465, 587, 993, 143]
    ports_ok = []
    ports_blocked = []

    for port in required_ports:
        if check_port_available(port):
            ports_ok.append(port)
        else:
            ports_blocked.append(port)

    services = []
    service_checks = {
        'PostgreSQL': (5432, 'postgres'),
        'Postfix': (25, 'postfix'),
        'Dovecot': (993, 'dovecot'),
    }

    for name, (port, proc_name) in service_checks.items():
        try:
            for proc in psutil.process_iter(['name']):
                if proc_name in proc.info['name'].lower():
                    services.append({"name": name, "status": "running", "port": port})
                    break
            else:
                services.append({"name": name, "status": "stopped", "port": port})
        except:
            services.append({"name": name, "status": "unknown", "port": port})

    ram_required_gb = 2.0
    disk_required_gb = 10.0

    all_ok = (
        ram.total / (1024**3) >= ram_required_gb and
        disk.free / (1024**3) >= disk_required_gb and
        len(ports_blocked) == 0
    )

    return {
        "status": "ok" if all_ok else "warning",
        "ram_ok": ram.total / (1024**3) >= ram_required_gb,
        "ram_total_gb": round(ram.total / (1024**3), 2),
        "ram_required_gb": ram_required_gb,
        "disk_ok": disk.free / (1024**3) >= disk_required_gb,
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "disk_required_gb": disk_required_gb,
        "ports_ok": ports_ok,
        "ports_blocked": ports_blocked,
        "services": services
    }


@router.get("/system-specs", response={200: SystemSpecsSchema}, summary="Sistem Özelliklerini Getir")
def get_system_specs(request):
    cpu_percent = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    docker_containers = []
    total_container_cpu = 0.0
    total_container_ram_mb = 0.0

    try:
        import docker
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        jir_containers = ['jir_django', 'jir_postgres', 'jir_postfix', 'jir_dovecot', 'jir_redis', 'jir_celery', 'jir_celery_beat']

        for container in client.containers.list():
            if any(c in container.name for c in jir_containers):
                try:
                    container.reload()
                    state = container.status
                    is_running = state == 'running'

                    stats = container.stats(stream=False) if is_running else None
                    cpu_percent = 0
                    mem_usage = 0
                    mem_limit = 0
                    mem_percent = 0

                    if stats:
                        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
                        system_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
                        cpu_count = stats['cpu_stats'].get('online_cpus', 1)
                        cpu_percent = (cpu_delta / system_delta * cpu_count * 100.0) if system_delta > 0 else 0

                        mem_usage = stats['memory_stats'].get('usage', 0) / (1024 * 1024)
                        mem_limit = stats['memory_stats'].get('limit', 1) / (1024 * 1024)
                        mem_percent = (mem_usage / mem_limit * 100) if mem_limit > 0 else 0

                    docker_containers.append({
                        "container_id": container.short_id,
                        "container_name": container.name,
                        "status": state,
                        "cpu_percent": round(cpu_percent, 2),
                        "ram_percent": round(mem_percent, 2),
                        "ram_usage_mb": round(mem_usage, 2),
                        "ram_limit_mb": round(mem_limit, 2),
                    })

                    if is_running:
                        total_container_cpu += cpu_percent
                        total_container_ram_mb += mem_usage
                except Exception as e:
                    continue

        client.close()
    except Exception as e:
        pass

    return {
        "cpu_percent": cpu_percent,
        "ram_percent": ram.percent,
        "ram_total_gb": round(ram.total / (1024**3), 2),
        "ram_used_gb": round(ram.used / (1024**3), 2),
        "disk_percent": disk.percent,
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "disk_used_gb": round(disk.used / (1024**3), 2),
        "docker_containers": docker_containers,
        "total_container_cpu": round(total_container_cpu, 2),
        "total_container_ram_mb": round(total_container_ram_mb, 2),
    }


class ContainerStatusSchema(Schema):
    container_id: str
    container_name: str
    status: str
    cpu_percent: float
    ram_percent: float
    ram_usage_mb: float
    ram_limit_mb: float


@router.get("/container-status", response={200: list}, summary="Container Durumu")
def get_container_status(request):
    containers = []

    socket_paths = [
        '/var/run/docker.sock',
        '/run/docker.sock',
    ]

    client = None
    last_error = None

    for socket_path in socket_paths:
        if not os.path.exists(socket_path):
            continue
        try:
            import docker
            client = docker.DockerClient(base_url=f'unix://{socket_path}')
            client.ping()
            break
        except Exception as e:
            last_error = str(e)
            client = None
            continue

    if not client:
        return [{
            "container_id": "error",
            "container_name": "Docker Connection Error",
            "status": "offline",
            "cpu_percent": 0,
            "ram_percent": 0,
            "ram_usage_mb": 0,
            "ram_limit_mb": 0,
            "error": f"Could not connect to Docker socket. Error: {last_error or 'Unknown'}. Check if Docker is running and socket permissions."
        }]

    try:
        jir_containers = ['jir_django', 'jir_postgres', 'jir_postfix', 'jir_dovecot', 'jir_redis', 'jir_celery', 'jir_celery_beat']
        all_containers = client.containers.list(all=True)

        for container in all_containers:
            if any(c in container.name for c in jir_containers):
                try:
                    container.reload()
                    state = container.status
                    is_running = state == 'running'

                    stats = container.stats(stream=False) if is_running else None
                    cpu_percent = 0.0
                    mem_usage = 0.0
                    mem_limit = 0.0
                    mem_percent = 0.0

                    if stats:
                        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
                        system_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
                        cpu_count = stats['cpu_stats'].get('online_cpus', 1)
                        cpu_percent = (cpu_delta / system_delta * cpu_count * 100.0) if system_delta > 0 else 0

                        mem_usage = stats['memory_stats'].get('usage', 0) / (1024 * 1024)
                        mem_limit = stats['memory_stats'].get('limit', 1) / (1024 * 1024)
                        mem_percent = (mem_usage / mem_limit * 100) if mem_limit > 0 else 0

                    containers.append({
                        "container_id": container.short_id,
                        "container_name": container.name,
                        "status": state,
                        "cpu_percent": round(cpu_percent, 2),
                        "ram_percent": round(mem_percent, 2),
                        "ram_usage_mb": round(mem_usage, 2),
                        "ram_limit_mb": round(mem_limit, 2),
                    })
                except Exception as e:
                    continue

        client.close()
    except Exception as e:
        pass

    return containers


class LogEntrySchema(Schema):
    timestamp: str
    type: str
    message: str
    source: str


@router.get("/logs", summary="Mail Loglarını Getir")
def get_logs(request, key: str, lines: int = 50, filter_type: str = None):
    if key != getattr(settings, 'JIR_LOCAL_KEY', None):
        return [
            {'timestamp': datetime.now().isoformat(), 'type': 'error', 'message': 'Yetkisiz erişim! Geçersiz anahtar.', 'source': 'system'}
        ]

    log_files = [
        '/var/log/mail.log',
        '/var/log/syslog',
        '/var/log/dovecot.log',
    ]

    logs = []

    missing_files = []
    for log_file in log_files:
        if not os.path.exists(log_file):
            missing_files.append(log_file)

    if missing_files:
        return [
            {'timestamp': datetime.now().isoformat(), 'type': 'info', 'message': f'Log files not found: {", ".join(missing_files)}. Mail services may not be configured yet.', 'source': 'system'}
        ]

    for log_file in log_files:
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    all_lines = f.readlines()
                    recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
                    for line in recent:
                        if not line.strip():
                            continue
                        entry = parse_log_line(line, log_file)
                        if entry:
                            if filter_type and entry.get('type') != filter_type:
                                continue
                            logs.append(entry)
            except PermissionError:
                logs.append({
                    'timestamp': datetime.now().isoformat(),
                    'type': 'warning',
                    'message': f'Permission denied reading: {log_file}',
                    'source': 'system'
                })
            except Exception as e:
                logs.append({
                    'timestamp': datetime.now().isoformat(),
                    'type': 'error',
                    'message': f'Error reading {log_file}: {str(e)}',
                    'source': 'system'
                })

    logs.sort(key=lambda x: x['timestamp'], reverse=True)
    return logs[:lines]


def parse_log_line(line, source_file):
    """Parse a log line into structured data"""
    patterns = {
        'auth': r'(?P<timestamp>\w+\s+\d+\s+\d+:\d+:\d+).*?(auth|login|password).*?(success|fail|error)',
        'smtp': r'(?P<timestamp>\w+\s+\d+\s+\d+:\d+:\d+).*?(smtp|send|reject).*?(from|to|=)',
        'delivery': r'(?P<timestamp>\w+\s+\d+\s+\d+:\d+:\d+).*?(delivered|bounced|deferred)',
        'dovecot': r'(?P<timestamp>\w+\s+\d+\s+\d+:\d+:\d+).*?(imap|pop3|dovecot)',
    }

    line_lower = line.lower()
    log_type = 'info'

    if 'error' in line_lower or 'fail' in line_lower:
        log_type = 'error'
    elif 'warning' in line_lower or 'warn' in line_lower:
        log_type = 'warning'
    elif 'auth' in line_lower or 'login' in line_lower:
        log_type = 'auth'
    elif 'delivered' in line_lower:
        log_type = 'success'
    elif 'sent' in line_lower or 'smtp' in line_lower:
        log_type = 'smtp'

    source_map = {
        '/var/log/mail.log': 'postfix',
        '/var/log/syslog': 'system',
        '/var/log/dovecot.log': 'dovecot',
    }

    try:
        return {
            'timestamp': datetime.now().isoformat(),
            'type': log_type,
            'message': line.strip()[:500],
            'source': source_map.get(source_file, 'unknown')
        }
    except:
        return None


class MailAccountSchema(Schema):
    username: str
    domain: str
    password: str


@router.post("/restart-container/{container_name}", summary="Container Yeniden Başlat")
def restart_container(request, container_name: str):
    """Belirtilen Docker container'ını yeniden başlatır."""
    # Sadece izin verilen container'lar yeniden başlatılabilir
    allowed_containers = [
        'jir_django', 'jir_postgres', 'jir_postfix',
        'jir_dovecot', 'jir_redis', 'jir_celery', 'jir_celery_beat'
    ]

    if container_name not in allowed_containers:
        return {"status": "error", "message": f"Container '{container_name}' izin listesinde değil."}

    socket_paths = ['/var/run/docker.sock', '/run/docker.sock']
    client = None

    for socket_path in socket_paths:
        if not os.path.exists(socket_path):
            continue
        try:
            import docker
            client = docker.DockerClient(base_url=f'unix://{socket_path}')
            client.ping()
            break
        except Exception:
            client = None

    if not client:
        return {"status": "error", "message": "Docker socket'e bağlanılamadı."}

    try:
        container = client.containers.get(container_name)
        container.restart(timeout=10)
        client.close()
        return {
            "status": "success",
            "message": f"'{container_name}' container'ı yeniden başlatıldı.",
            "container": container_name
        }
    except Exception as e:
        return {"status": "error", "message": f"Yeniden başlatma hatası: {str(e)}"}



    username: str
    domain: str
    password: str


def update_postfix_vmail(email, action="add"):
    vmail_path = getattr(settings, 'POSTFIX_VMAIL_PATH', '/etc/postfix/vmail_accounts')
    try:
        import os
        os.makedirs(os.path.dirname(vmail_path), exist_ok=True)

        if action == "remove":
            if os.path.exists(vmail_path):
                with open(vmail_path, 'r') as f:
                    lines = f.readlines()
                with open(vmail_path, 'w') as f:
                    for line in lines:
                        if not line.startswith(email + ' '):
                            f.write(line)
        else:
            with open(vmail_path, 'a') as f:
                f.write(f"{email} OK\n")

        try:
            result = subprocess.run(['postmap', vmail_path], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                import logging
                logging.warning(f"Postfix map update warning: {result.stderr}")
                return True
        except FileNotFoundError:
            import logging
            logging.warning("postmap command not found, skipping postmap")
            return True
        except Exception as e:
            import logging
            logging.warning(f"Postfix map update warning: {e}")
            return True
        return True
    except Exception as e:
        import logging
        logging.error(f"Postfix update error: {e}")
        return False


@router.post("/create-account", summary="Yeni Mail Hesabı Oluştur")
@csrf_exempt
def create_mail_account(request, data: MailAccountSchema):
    config = SystemConfig.objects.first()

    if not config:
        return {"status": "error", "message": "Sistem konfigürasyonu bulunamadı!"}

    current_count = MailAccount.objects.count()
    if current_count >= config.max_accounts:
        return {
            "status": "error",
            "message": f"Limit aşıldı! Mevcut paketiniz en fazla {config.max_accounts} hesaba izin veriyor."
        }

    salt = bcrypt.gensalt()
    hashed_pw = bcrypt.hashpw(data.password.encode('utf-8'), salt).decode('utf-8')

    domain_obj, _ = MailDomain.objects.get_or_create(name=data.domain)
    full_email = f"{data.username}@{data.domain}".lower()

    try:
        new_account = MailAccount.objects.create(
            domain=domain_obj,
            username=data.username,
            email=full_email,
            password_hash=hashed_pw
        )

        try:
            update_postfix_vmail(full_email, action="add")
        except Exception as e:
            import logging
            logging.warning(f"Postfix vmail update skipped: {e}")

        return {
            "status": "success",
            "email": new_account.email,
            "remaining_slots": config.max_accounts - (current_count + 1)
        }
    except Exception as e:
        import logging
        logging.error(f"Create account error: {e}")
        return {"status": "error", "message": f"Hesap oluşturulamadı: {str(e)}"}