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

from .docker_containers import (
    SERVICE_KEYS,
    all_resolved_container_names,
    merged_container_name,
    persist_container_alias,
    read_stored_container_map,
    service_key_for_display_name,
    service_key_from_container_url_segment,
)

router = Router()


class HealthStatusSchema(Schema):
    status: str
    database: bool
    postfix: bool
    dovecot: bool


class SystemSettingsUpdateSchema(Schema):
    """Kurulum sonrası panel ayarları (veritabanı alanları bu endpoint ile değişmez)."""

    docker_container_map: dict | None = None
    mail_data_path: str | None = None
    postfix_vmail_path: str | None = None
    dovecot_passdb_path: str | None = None
    backup_dir: str | None = None


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
    # postmap yoksa process kontrolüne düş
    if not checks['postfix']:
        try:
            for proc in psutil.process_iter(['name']):
                if 'postfix' in proc.info['name'].lower() or 'master' in proc.info['name'].lower():
                    checks['postfix'] = True
                    break
        except Exception:
            pass

    dovecot_socket = '/var/run/dovecot/auth-login'
    if os.path.exists(dovecot_socket) or os.path.exists('/var/run/dovecot'):
        checks['dovecot'] = True
    # socket yoksa process kontrolüne düş
    if not checks['dovecot']:
        try:
            for proc in psutil.process_iter(['name']):
                if 'dovecot' in proc.info['name'].lower():
                    checks['dovecot'] = True
                    break
        except Exception:
            pass

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


def check_port_listening(port, host='localhost'):
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            result = s.connect_ex((host, port))
            return result == 0
    except:
        return False


def _normalize_docker_container_name(name):
    if not name:
        return ''
    return str(name).strip().strip('/')


def _management_docker_client(timeout=10):
    import docker
    dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    return docker.DockerClient(base_url=dh, timeout=timeout)


def _static_jir_container_names():
    """İzin verilen konteyner adları (env + SystemConfig.docker_container_map)."""
    return all_resolved_container_names()


def _jir_stack_name_substrings(include_proxy=False):
    """Konteyner listelerinde eşleştirme (Coolify uzun adları için substring)."""
    names = list(_static_jir_container_names())
    if include_proxy:
        names.append('jir_docker_proxy')
    names.append('jir_')
    out = []
    seen = set()
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


_DOCKER_STACK_DISCOVERY = {
    'PostgreSQL': {
        'hints': ('postgres', 'postgresql'),
        'compose': ('postgres', 'db', 'database'),
    },
    'Postfix': {
        'hints': ('postfix', 'smtp', 'mta', 'exim', 'boky/postfix'),
        'compose': ('postfix', 'smtp', 'mta', 'mail', 'mailer', 'msmtp'),
    },
    'Dovecot': {
        'hints': ('dovecot', 'imap', 'pop3', 'lmtp'),
        'compose': ('dovecot', 'imap', 'pop3', 'mail'),
    },
    'Redis': {
        'hints': ('redis', 'valkey', 'keydb'),
        'compose': ('redis', 'valkey', 'keydb', 'cache'),
    },
}

# İsim/Compose etiketi bulunamadığında imaj satırında arama (Coolify uzun adları)
_SERVICE_IMAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    'postgres': ('postgres', 'postgis', 'timescale'),
    'postfix': (
        'postfix',
        'docker-mailserver',
        'mailu',
        'exim',
        'sendmail',
        'boky/postfix',
        'catatnight/postfix',
    ),
    'dovecot': ('dovecot', 'mailu/dovecot', 'mailu/imap', 'dovecot-imap'),
    'redis': ('redis', 'valkey', 'keydb'),
    'django': ('jir-mail', 'jir_mail', 'gunicorn'),
    'celery': ('celery', 'jir-mail', 'jir_mail'),
    'celery_beat': ('celery', 'beat', 'jir-mail', 'jir_mail'),
}


def _discover_container_by_image_keywords(client, service_key: str | None) -> str | None:
    """İmaj adında servis ipucu — isim keşfi başarısızsa (ör. Coolify rastgele ad)."""
    if not service_key:
        return None
    sk = service_key.strip().lower()
    kws = _SERVICE_IMAGE_KEYWORDS.get(sk)
    if not kws:
        return None
    junk = ('webpack', 'vite', 'nginx:')
    best = None
    best_sc = 0
    for c in client.containers.list(all=True):
        try:
            img = (((c.attrs or {}).get('Config') or {}).get('Image') or '').lower()
            nm = _normalize_docker_container_name(c.name).lower()
        except Exception:
            continue
        if any(j in img for j in junk) and not any(k in img for k in kws):
            continue
        sc = 0
        for kw in kws:
            if kw in img:
                sc += 24
            if kw in nm:
                sc += 12
        if getattr(c, 'status', None) == 'running':
            sc += 4
        if sc > best_sc:
            best_sc = sc
            best = c
    if best is None or best_sc < 15:
        return None
    return _normalize_docker_container_name(best.name)


def _compose_service_name(c) -> str:
    try:
        labs = (c.attrs or {}).get('Config', {}).get('Labels') or {}
        if not isinstance(labs, dict):
            return ''
        return (labs.get('com.docker.compose.service') or '').strip().lower()
    except Exception:
        return ''


def _discovery_cfg_for_url_key(url_key_lower: str) -> dict:
    """URL segmenti → hints + compose (Coolify uzun adları için)."""
    key = (url_key_lower or '').strip().lower()
    disp_map = {
        'postgresql': 'PostgreSQL',
        'postgres': 'PostgreSQL',
        'jir_postgres': 'PostgreSQL',
        'postfix': 'Postfix',
        'jir_postfix': 'Postfix',
        'dovecot': 'Dovecot',
        'jir_dovecot': 'Dovecot',
        'redis': 'Redis',
        'jir_redis': 'Redis',
    }
    disp = disp_map.get(key)
    if disp:
        return dict(_DOCKER_STACK_DISCOVERY[disp])
    if 'postfix' in key or '-smtp-' in key or key.endswith('smtp'):
        return dict(_DOCKER_STACK_DISCOVERY['Postfix'])
    if 'dovecot' in key or 'imap' in key:
        return dict(_DOCKER_STACK_DISCOVERY['Dovecot'])
    if 'postgres' in key or 'postgresql' in key:
        return dict(_DOCKER_STACK_DISCOVERY['PostgreSQL'])
    if 'redis' in key or 'valkey' in key:
        return dict(_DOCKER_STACK_DISCOVERY['Redis'])
    return {'hints': (), 'compose': ()}


def _hints_for_url_container_key(url_key_lower: str) -> tuple[str, ...] | None:
    cfg = _discovery_cfg_for_url_key(url_key_lower)
    h = tuple(cfg.get('hints') or ())
    return h if h else None


def _discover_container_by_hints(client, hints, compose_names=()):
    hints = tuple(h.lower() for h in hints if h)
    compose_names = tuple(n.lower() for n in (compose_names or ()) if n)
    if not hints and not compose_names:
        return None
    best = None
    best_score = -1
    for c in client.containers.list(all=True):
        nm = _normalize_docker_container_name(c.name).lower()
        if nm and all(x not in nm for x in ('postfix', 'dovecot', 'smtp', 'imap', 'pop3', 'lmtp', 'mta', 'mail')):
            if any(x in nm for x in ('django', 'gunicorn', 'celery', 'uvicorn', 'webpack', 'vite')):
                continue
        img = ''
        try:
            img = (((c.attrs or {}).get('Config') or {}).get('Image') or '').lower()
        except Exception:
            pass
        svc = _compose_service_name(c)
        sc = 0
        for h in hints:
            if h and h in nm:
                sc += 12
            if h and h in img:
                sc += 8
        for cn in compose_names:
            if cn and cn == svc:
                sc += 30
            elif cn and cn in nm:
                sc += 5
        if sc > best_score:
            best_score = sc
            best = c
        elif sc == best_score and sc > 0 and best is not None:
            try:
                if c.status == 'running' and getattr(best, 'status', None) != 'running':
                    best = c
            except Exception:
                pass
    if best is None or best_score < 6:
        return None
    return _normalize_docker_container_name(best.name)


def _port_probe_host_for_service(display_name: str) -> str:
    """Docker ağında servis adı ile port dinleme; 'PostgreSQL'.lower() → postgresql hatası önlenir."""
    if display_name == 'PostgreSQL':
        return getattr(settings, 'POSTGRES_HOST', None) or 'postgres'
    if display_name == 'Redis':
        return getattr(settings, 'REDIS_HOST', None) or 'redis'
    if display_name == 'Postfix':
        return os.getenv('POSTFIX_SMTP_HOST', 'postfix')
    if display_name == 'Dovecot':
        return os.getenv('DOVECOT_IMAP_HOST', 'dovecot')
    return display_name.lower()


def _get_container_resolving_aliases(client, primary_name: str, url_key_lower: str):
    """Önce tam ad; yoksa ipuçlarıyla keşfedilen gerçek konteyner adı (Coolify vb.)."""
    import docker

    primary_name = _normalize_docker_container_name(primary_name)
    cfg = _discovery_cfg_for_url_key(url_key_lower)
    hints = tuple(cfg.get('hints') or ())
    compose = tuple(cfg.get('compose') or ())

    try:
        return client.containers.get(primary_name), primary_name
    except docker.errors.NotFound:
        if not hints and not compose:
            sk_fb = service_key_from_container_url_segment(url_key_lower)
            alt_kw = _discover_container_by_image_keywords(client, sk_fb)
            if alt_kw:
                return client.containers.get(alt_kw), alt_kw
            raise docker.errors.NotFound(
                f'Container {primary_name} not found'
            ) from None
        alt = _discover_container_by_hints(client, hints, compose)
        if not alt:
            sk_fb = service_key_from_container_url_segment(url_key_lower)
            alt = _discover_container_by_image_keywords(client, sk_fb)
        if not alt:
            raise docker.errors.NotFound(
                f'Container {primary_name} not found'
            ) from None
        return client.containers.get(alt), alt


def _resolve_service_container_name(default_name, display_name):
    """Önce ayarlı ad; yoksa imaj/isim/Compose etiketi ile keşif (Coolify vb.)."""
    resolved = _normalize_docker_container_name(default_name)
    cfg = _DOCKER_STACK_DISCOVERY.get(display_name) or {'hints': (), 'compose': ()}
    hints = tuple(cfg.get('hints') or ())
    compose = tuple(cfg.get('compose') or ())
    client = None
    try:
        client = _management_docker_client(3)
        client.ping()
    except Exception:
        return resolved
    try:
        if check_service_in_docker(resolved):
            return resolved
        alt = _discover_container_by_hints(client, hints, compose)
        if alt:
            return alt
        sk = service_key_for_display_name(display_name)
        if sk:
            alt2 = _discover_container_by_image_keywords(client, sk)
            if alt2:
                return alt2
    except Exception:
        pass
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
    return resolved


def _management_container_pass_through_allowed(client, name):
    try:
        c = client.containers.get(_normalize_docker_container_name(name))
    except Exception:
        return False
    nm = _normalize_docker_container_name(c.name).lower()
    img = ''
    try:
        img = (((c.attrs or {}).get('Config') or {}).get('Image') or '').lower()
    except Exception:
        pass
    needles = ('postgres', 'postgresql', 'postfix', 'dovecot', 'redis', 'celery', 'jir')
    return any(n in nm or n in img for n in needles)


def check_service_in_docker(container_name, docker_host=None):
    """Docker içinde container çalışıyor mu kontrol et"""
    try:
        import docker
        dh = docker_host or getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
        client = docker.DockerClient(base_url=dh, timeout=3)
        want = _normalize_docker_container_name(container_name)
        for container in client.containers.list(all=True):
            if _normalize_docker_container_name(container.name) == want:
                ok = container.status == 'running'
                client.close()
                return ok
        client.close()
        return False
    except Exception:
        return False


@router.get("/system-requirements", response={200: dict}, summary="Sistem Gereksinimleri Kontrol")
def check_system_requirements(request):
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    required_ports = [25, 465, 587, 993, 143]
    ports_ok = []
    ports_blocked = []

    for port in required_ports:
        if check_port_listening(port):
            ports_ok.append(port)
        else:
            ports_blocked.append(port)

    services = []
    docker_services = {
        'PostgreSQL': {'port': 5432},
        'Postfix': {'port': 25},
        'Dovecot': {'port': 993},
        'Redis': {'port': 6379},
    }

    docker_host = getattr(settings, 'DOCKER_HOST', None)

    for name, info in docker_services.items():
        sk = service_key_for_display_name(name)
        merged_before = merged_container_name(sk) if sk else ''
        container_name = _resolve_service_container_name(merged_before, name)
        if sk and container_name and container_name != merged_before:
            persist_container_alias(sk, container_name)
        port = info['port']

        # 1. Önce Docker container kontrolü (en güvenilir)
        if check_service_in_docker(container_name, docker_host):
            services.append({
                "name": name,
                "status": "running",
                "port": port,
                "container": container_name,
            })
            continue

        # 2. Docker başarısız veya container yoksa, port kontrolü
        # Django Docker ağında ise servis hostname'i (postgres, redis, …) ile dene
        probe_host = _port_probe_host_for_service(name)
        is_listening = check_port_listening(port, host=probe_host)

        if not is_listening:
            # Fallback: localhost üzerinden de dene
            is_listening = check_port_listening(port, host='localhost')

        services.append({
            "name": name,
            "status": "running" if is_listening else "stopped",
            "port": port,
            "container": container_name,
        })

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


@router.get("/docker-diagnostics", summary="Docker keşif tanısı (FULL oturum)")
def docker_diagnostics(request):
    """Panel hangi konteyner adlarını çözüyor; Docker listesinde postfix/dovecot vb. görünüyor mu."""
    from management.coolify_discovery import (
        mail_tcp_endpoints,
        network_ips_from_attrs,
        network_overlap_hint,
        relevant_platform_env,
        suggested_coolify_env_block,
    )
    from management.deploy_readiness import detect_deployment_platform

    if not request.session.get('is_logged_in'):
        return {"status": "error", "message": "Oturum gerekli."}
    if request.session.get('role') != 'FULL':
        return {"status": "error", "message": "Bu işlem için FULL yetkisi gerekir."}

    out: dict = {
        "status": "ok",
        "docker_host": getattr(settings, 'DOCKER_HOST', ''),
        "docker_ping": False,
        "docker_error": None,
        "merged_container_names": {},
        "stored_docker_container_map": {},
        "mail_related_containers": [],
    }
    for sk in ('postgres', 'postfix', 'dovecot', 'redis', 'django', 'celery', 'celery_beat'):
        out['merged_container_names'][sk] = merged_container_name(sk)
    out['stored_docker_container_map'] = read_stored_container_map()

    client = None
    try:
        import docker
        client = _management_docker_client(8)
        client.ping()
        out['docker_ping'] = True
        for c in client.containers.list(all=True):
            nm = (c.name or '').lower()
            img = ''
            try:
                img = (((c.attrs or {}).get('Config') or {}).get('Image') or '').lower()
            except Exception:
                pass
            if any(x in nm or x in img for x in (
                'postfix', 'dovecot', 'smtp', 'imap', 'redis', 'postgres', 'jir_', 'mail',
            )):
                try:
                    c.reload()
                    attrs = c.attrs or {}
                except Exception:
                    attrs = (c.attrs or {})
                nets = network_ips_from_attrs(attrs)
                img_full = ''
                try:
                    img_full = (((attrs.get('Config') or {}).get('Image') or img or '') or '').lower()
                except Exception:
                    img_full = img or ''
                out['mail_related_containers'].append({
                    'name': c.name,
                    'status': getattr(c, 'status', ''),
                    'image': img_full[:160],
                    'compose_service': _compose_service_name(c),
                    'network_ips': nets,
                })
        out['mail_related_containers'] = sorted(
            out['mail_related_containers'],
            key=lambda x: (x.get('name') or '').lower(),
        )[:60]
    except Exception as exc:
        out['docker_error'] = str(exc)
        out['status'] = 'warning'
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass

    if out.get('docker_ping') and not out.get('mail_related_containers'):
        out['hint'] = (
            'Bu Docker API listesinde postfix/dovecot/postgres/redis adında konteyner yok. '
            'Harici Postgres kullanıyorsanız: `python manage.py provision_mail_stack --print-compose` ile YAML üretin '
            've Coolify’da ayrı stack olarak deploy edin. '
            'Mail servisleri başka sunucudaysa SMTP_HOST/IMAP_HOST kullanın.'
        )
    elif out.get('docker_error'):
        out['hint'] = (
            'Docker API erişilemiyor. DOCKER_HOST veya /var/run/docker.sock mount kontrol edin. '
            'Erişim yoksa yalnızca ortam değişkeni ile sabit ad verilebilir.'
        )

    out['deployment_platform'] = detect_deployment_platform()
    out['platform_env_summary'] = relevant_platform_env()
    out['mail_tcp'] = mail_tcp_endpoints()
    out['suggested_env_snippet'] = suggested_coolify_env_block({'containers': out['mail_related_containers']})
    oh = network_overlap_hint(out['mail_related_containers'])
    if oh:
        out['network_overlap_hint'] = oh

    return out


@router.get("/deploy-readiness", summary="Deploy / Coolify uyumluluk raporu (FULL)")
def deploy_readiness_api(request):
    """Deploy sonrası ortam kontrolü: profil uyumu, Docker, mail, env."""
    if not request.session.get('is_logged_in'):
        return {"status": "error", "message": "Oturum gerekli."}
    if request.session.get('role') != 'FULL':
        return {"status": "error", "message": "Bu işlem için yönetici (FULL) yetkisi gerekir."}

    from .deploy_readiness import collect_deploy_readiness

    report = collect_deploy_readiness()
    return {"status": "ok", **report}


@router.get("/mail-stack-compose", summary="Postfix+Dovecot için compose YAML (FULL)")
def mail_stack_compose_api(request):
    """DATABASE_URL + MAIL_DOMAIN ile Coolify’a yapıştırılabilir docker-compose üretir."""
    if not request.session.get('is_logged_in'):
        return {"status": "error", "message": "Oturum gerekli."}
    if request.session.get('role') != 'FULL':
        return {"status": "error", "message": "Bu işlem için yönetici (FULL) yetkisi gerekir."}

    from installer.mail_stack import (
        mail_stack_instructions_markdown,
        mail_stack_params_from_env,
        mail_stack_params_summary,
        render_mail_stack_compose_yaml,
    )

    try:
        p = mail_stack_params_from_env()
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    return {
        "status": "ok",
        "compose_yaml": render_mail_stack_compose_yaml(p),
        "params": mail_stack_params_summary(p),
        "instructions_md": mail_stack_instructions_markdown(),
    }


@router.get("/system-settings", summary="Kurulum sonrası sistem ayarları (FULL)")
def get_system_settings(request):
    if not request.session.get('is_logged_in'):
        return {"status": "error", "message": "Oturum gerekli."}
    if request.session.get('role') != 'FULL':
        return {"status": "error", "message": "Bu sayfa için yönetici (FULL) yetkisi gerekir."}

    config = SystemConfig.objects.first()
    if not config:
        return {"status": "error", "message": "SystemConfig bulunamadı."}

    ilog = config.installation_log or {}
    if not isinstance(ilog, dict):
        ilog = {}

    resolved = {sk: merged_container_name(sk) for sk in SERVICE_KEYS}
    stored = read_stored_container_map()

    return {
        "status": "ok",
        "is_installed": bool(config.is_installed),
        "instance_id": str(config.instance_id),
        "installation_log": ilog,
        "docker_container_map": dict(stored),
        "docker_resolved": resolved,
        "mail_data_path": config.mail_data_path or "",
        "postfix_vmail_path": config.postfix_vmail_path or "",
        "dovecot_passdb_path": config.dovecot_passdb_path or "",
        "backup_dir": config.backup_dir or "",
        "database_visible": {
            "engine": config.db_engine or "",
            "host": config.db_host or "",
            "port": int(config.db_port) if config.db_port else None,
            "name": config.db_name or "",
            "user": config.db_user or "",
            "password_configured": bool((config.db_password or "").strip()),
        },
    }


@router.post("/system-settings", summary="Sistem ayarlarını güncelle (FULL, DB hariç)")
@csrf_exempt
def update_system_settings(request, data: SystemSettingsUpdateSchema):
    if not request.session.get('is_logged_in'):
        return {"status": "error", "message": "Oturum gerekli."}
    if request.session.get('role') != 'FULL':
        return {"status": "error", "message": "Bu sayfa için yönetici (FULL) yetkisi gerekir."}

    config = SystemConfig.objects.first()
    if not config:
        return {"status": "error", "message": "SystemConfig bulunamadı."}

    fields: list[str] = []

    if data.docker_container_map is not None:
        m = dict(config.docker_container_map or {})
        if not isinstance(m, dict):
            m = {}
        for k, v in data.docker_container_map.items():
            kk = str(k).strip().lower()
            if kk not in SERVICE_KEYS:
                continue
            vv = _normalize_docker_container_name(str(v))
            if vv:
                m[kk] = vv
            else:
                m.pop(kk, None)
        config.docker_container_map = m
        fields.append('docker_container_map')

    if data.mail_data_path is not None:
        config.mail_data_path = (data.mail_data_path or '').strip()[:500]
        fields.append('mail_data_path')
    if data.postfix_vmail_path is not None:
        config.postfix_vmail_path = (data.postfix_vmail_path or '').strip()[:500]
        fields.append('postfix_vmail_path')
    if data.dovecot_passdb_path is not None:
        config.dovecot_passdb_path = (data.dovecot_passdb_path or '').strip()[:500]
        fields.append('dovecot_passdb_path')
    if data.backup_dir is not None:
        config.backup_dir = (data.backup_dir or '').strip()[:500]
        fields.append('backup_dir')

    if not fields:
        return {"status": "error", "message": "Güncellenecek alan yok."}

    fields.append('updated_at')
    config.save(update_fields=fields)
    return {"status": "ok", "message": "Ayarlar kaydedildi."}


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
        client = _management_docker_client(5)
        client.ping()
        jir_subs = _jir_stack_name_substrings(include_proxy=False)

        for container in client.containers.list(all=True):
            if any(c in container.name for c in jir_subs):
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


class SystemStatsSchema(Schema):
    active_domains: int
    active_accounts: int
    inactive_accounts: int


@router.get("/system-stats", response={200: SystemStatsSchema}, summary="Navbar İstatistikleri")
def get_system_stats(request):
    from core.models import MailAccount, MailDomain

    active_domains = MailDomain.objects.filter(is_active=True).count()
    active_accounts = MailAccount.objects.filter(is_active=True).count()
    inactive_accounts = MailAccount.objects.filter(is_active=False).count()

    return {
        "active_domains": active_domains,
        "active_accounts": active_accounts,
        "inactive_accounts": inactive_accounts
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
    from management.compose_status import compose_stack_containers

    compose_list = compose_stack_containers()
    if compose_list is not None:
        return compose_list

    containers = []
    import docker

    substrings = _jir_stack_name_substrings(include_proxy=True)
    base_urls = []
    dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    base_urls.append(dh)
    if dh.startswith('unix://'):
        for sp in ('/var/run/docker.sock', '/run/docker.sock'):
            u = f'unix://{sp}'
            if u not in base_urls:
                base_urls.append(u)

    for base_url in base_urls:
        client = None
        try:
            client = docker.DockerClient(base_url=base_url, timeout=5)
            client.ping()
        except Exception:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
            continue

        try:
            all_containers = client.containers.list(all=True)
            for container in all_containers:
                if any(s in container.name for s in substrings):
                    try:
                        container.reload()
                        state = container.status
                        is_running = state == 'running'

                        cpu_percent = 0.0
                        mem_usage = 0.0
                        mem_limit = 0.0
                        mem_percent = 0.0

                        if is_running:
                            try:
                                stats = container.stats(stream=False)
                                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                                            stats['precpu_stats']['cpu_usage']['total_usage']
                                system_delta = stats['cpu_stats'].get('system_cpu_usage', 0) - \
                                               stats['precpu_stats'].get('system_cpu_usage', 0)
                                cpu_count = stats['cpu_stats'].get('online_cpus', 1)
                                if system_delta > 0:
                                    cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0

                                mem_usage = stats['memory_stats'].get('usage', 0) / (1024 * 1024)
                                mem_limit = stats['memory_stats'].get('limit', 1) / (1024 * 1024)
                                mem_percent = (mem_usage / mem_limit * 100) if mem_limit > 0 else 0
                            except Exception:
                                pass

                        containers.append({
                            "container_id": container.short_id,
                            "container_name": container.name,
                            "status": state,
                            "cpu_percent": round(cpu_percent, 2),
                            "ram_percent": round(mem_percent, 2),
                            "ram_usage_mb": round(mem_usage, 2),
                            "ram_limit_mb": round(mem_limit, 2),
                        })
                    except Exception:
                        continue

            client.close()
            return containers
        except Exception as e:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
            if dh.startswith('tcp://') and base_url == dh:
                return [{
                    "container_id": "error",
                    "container_name": "Docker Proxy Error",
                    "status": "offline",
                    "cpu_percent": 0,
                    "ram_percent": 0,
                    "ram_usage_mb": 0,
                    "ram_limit_mb": 0,
                    "error": str(e)
                }]
            continue

    return [{
        "container_id": "unavailable",
        "container_name": "Docker Unavailable",
        "status": "offline",
        "cpu_percent": 0,
        "ram_percent": 0,
        "ram_usage_mb": 0,
        "ram_limit_mb": 0,
        "error": "Docker API erişilemiyor. DOCKER_HOST ortam değişkenini ayarlayın veya /var/run/docker.sock mount edin (yerel compose için docker-proxy kullanılabilir)."
    }]


@router.post("/container/{container_name}/{action}", summary="Container Start/Stop/Restart")
@csrf_exempt
def container_action(request, container_name, action):
    """Start, stop, or restart a Docker container (dashboard — FULL oturum gerekir)."""
    if not request.session.get('is_logged_in'):
        return {"status": "error", "message": "Oturum gerekli. Lütfen yeniden giriş yapın."}
    if request.session.get('role') != 'FULL':
        return {"status": "error", "message": "Bu işlem için yönetici (FULL) yetkisi gerekir."}

    if action not in ['start', 'stop', 'restart']:
        return {"status": "error", "message": "Invalid action. Use start, stop, or restart."}

    _blocked_names = {
        'docker unavailable',
        'docker proxy error',
        'unavailable',
        'error',
    }
    raw_early = (container_name or '').strip().lower()
    if raw_early in _blocked_names or 'unavailable' in raw_early:
        return {
            "status": "error",
            "message": (
                "Docker API bu panelde kullanılamıyor (Compose/Dokploy modu). "
                "Konteynerleri platform arayüzünden veya sunucuda `docker compose` ile yönetin."
            ),
        }

    try:
        from installer.compose_mode import is_compose_stack

        if is_compose_stack():
            return {
                "status": "error",
                "message": (
                    "JIR_COMPOSE_STACK=1: servisler docker-compose.yml ile yönetilir. "
                    "Dokploy’da stack’i yeniden başlatın; panelden start/stop desteklenmez."
                ),
            }
    except Exception:
        pass

    container_map = {
        'postgresql': merged_container_name('postgres'),
        'postgres': merged_container_name('postgres'),
        'postfix': merged_container_name('postfix'),
        'dovecot': merged_container_name('dovecot'),
        'redis': merged_container_name('redis'),
        'django': merged_container_name('django'),
        'celery': merged_container_name('celery'),
        'celery_beat': merged_container_name('celery_beat'),
    }
    for legacy_key, sk in (
        ('jir_postgres', 'postgres'),
        ('jir_postfix', 'postfix'),
        ('jir_dovecot', 'dovecot'),
        ('jir_redis', 'redis'),
        ('jir_django', 'django'),
        ('jir_celery', 'celery'),
        ('jir_celery_beat', 'celery_beat'),
    ):
        container_map[legacy_key] = merged_container_name(sk)

    raw = _normalize_docker_container_name(container_name)
    lk = raw.lower()
    if lk in container_map:
        actual_name = _normalize_docker_container_name(container_map[lk])
    else:
        actual_name = raw

    allowed_static = _static_jir_container_names()

    client = None

    try:
        import docker
        client = _management_docker_client(10)

        if actual_name not in allowed_static and not _management_container_pass_through_allowed(client, actual_name):
            return {"status": "error", "message": f"Bu konteyner için işlem tanımlı değil: {actual_name}"}

        try:
            container, physical_name = _get_container_resolving_aliases(client, actual_name, lk)
        except docker.errors.NotFound:
            return {"status": "error", "message": f"Container {actual_name} not found"}

        if physical_name != actual_name and physical_name not in allowed_static:
            if not _management_container_pass_through_allowed(client, physical_name):
                return {"status": "error", "message": f"Keşfedilen konteyner için işlem tanımlı değil: {physical_name}"}

        sk_disc = service_key_from_container_url_segment(lk)

        if action == 'start':
            try:
                container.start()
            except docker.errors.APIError as e:
                err = str(e).lower()
                if 'already started' in err or 'already running' in err or '304' in str(e):
                    return {"status": "success", "message": f"{physical_name} zaten çalışıyor", "action": "noop"}
                raise
            if sk_disc and physical_name != actual_name:
                persist_container_alias(sk_disc, physical_name)
            return {"status": "success", "message": f"{physical_name} başlatıldı", "action": "start"}
        elif action == 'stop':
            try:
                container.stop(timeout=10)
            except docker.errors.APIError as e:
                err = str(e).lower()
                if 'not running' in err or 'is not running' in err:
                    return {"status": "success", "message": f"{physical_name} zaten durmuş", "action": "noop"}
                raise
            if sk_disc and physical_name != actual_name:
                persist_container_alias(sk_disc, physical_name)
            return {"status": "success", "message": f"{physical_name} durduruldu", "action": "stop"}
        elif action == 'restart':
            container.restart(timeout=10)
            if sk_disc and physical_name != actual_name:
                persist_container_alias(sk_disc, physical_name)
            return {"status": "success", "message": f"{physical_name} yeniden başlatıldı", "action": "restart"}

    except ImportError:
        return {"status": "error", "message": "Docker module not installed. Install with: pip install docker"}
    except Exception as e:
        docker_error = str(e)
        if 'NotFound' in docker_error or '404' in docker_error:
            return {"status": "error", "message": f"Container {actual_name} not found"}
        elif 'Permission' in docker_error or 'denied' in docker_error.lower():
            return {"status": "error", "message": "Docker permission denied. Check socket access."}
        else:
            return {"status": "error", "message": docker_error}
    finally:
        if client:
            client.close()


class LogEntrySchema(Schema):
    timestamp: str
    type: str
    message: str
    source: str


@router.get("/logs", summary="Mail Loglarını Getir")
def get_logs(request, key: str = None, lines: int = 100, filter_type: str = None):
    # Key doğrulama: settings, DB veya session'dan kontrol et
    valid_key = getattr(settings, 'JIR_LOCAL_KEY', None)
    try:
        config = SystemConfig.objects.first()
        if config and config.jir_local_key:
            valid_key = config.jir_local_key
    except Exception:
        pass

    # Session'dan giriş yapmış kullanıcı da erişebilir
    session_logged_in = getattr(request, 'session', {}).get('is_logged_in', False)

    if not session_logged_in and key != valid_key:
        return [
            {'timestamp': datetime.now().isoformat(), 'type': 'error', 'message': 'Yetkisiz erişim! Geçersiz anahtar.', 'source': 'system'}
        ]

    log_files = [
        '/var/log/mail.log',
        '/var/log/syslog',
        '/var/log/dovecot.log',
    ]

    logs = []

    missing_files = [f for f in log_files if not os.path.exists(f)]

    if len(missing_files) == len(log_files):
        # Hiçbir log dosyası yok — Django uygulama loglarını göster
        django_logs = []
        try:
            import logging
            # Son Django log kayıtlarını simüle et
            django_logs.append({
                'timestamp': datetime.now().isoformat(),
                'type': 'info',
                'message': 'Mail log dosyaları bulunamadı (/var/log/mail.log, /var/log/syslog, /var/log/dovecot.log). '
                           'Bu dosyalar Postfix ve Dovecot servisleri çalıştığında oluşur.',
                'source': 'system'
            })
            django_logs.append({
                'timestamp': datetime.now().isoformat(),
                'type': 'info',
                'message': f'Django sunucusu çalışıyor. DEBUG={settings.DEBUG}. '
                           f'Veritabanı: {settings.DATABASES["default"]["ENGINE"].split(".")[-1]}',
                'source': 'django'
            })
        except Exception:
            pass
        return django_logs

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
    raw = _normalize_docker_container_name(container_name)
    lk = raw.lower()
    quick_map = {
        'postgresql': merged_container_name('postgres'),
        'postgres': merged_container_name('postgres'),
        'postfix': merged_container_name('postfix'),
        'dovecot': merged_container_name('dovecot'),
        'redis': merged_container_name('redis'),
        'django': merged_container_name('django'),
        'celery': merged_container_name('celery'),
        'celery_beat': merged_container_name('celery_beat'),
        'jir_postgres': merged_container_name('postgres'),
        'jir_postfix': merged_container_name('postfix'),
        'jir_dovecot': merged_container_name('dovecot'),
        'jir_redis': merged_container_name('redis'),
        'jir_django': merged_container_name('django'),
        'jir_celery': merged_container_name('celery'),
        'jir_celery_beat': merged_container_name('celery_beat'),
    }
    target = quick_map.get(lk, raw)
    allowed_static = _static_jir_container_names()

    client = None
    try:
        import docker
        client = _management_docker_client(10)
        client.ping()
    except Exception as e:
        if client:
            try:
                client.close()
            except Exception:
                pass
        return {"status": "error", "message": f"Docker'a bağlanılamadı: {str(e)}"}

    if target not in allowed_static and not _management_container_pass_through_allowed(client, target):
        try:
            client.close()
        except Exception:
            pass
        return {"status": "error", "message": f"Container '{container_name}' izin listesinde değil."}

    try:
        import docker
        container, physical = _get_container_resolving_aliases(client, target, lk)
        if physical != target and physical not in allowed_static:
            if not _management_container_pass_through_allowed(client, physical):
                try:
                    client.close()
                except Exception:
                    pass
                return {"status": "error", "message": f"Keşfedilen konteyner izin listesinde değil: {physical}"}
        container.restart(timeout=10)
        sk_disc = service_key_from_container_url_segment(lk)
        if sk_disc and physical != target:
            persist_container_alias(sk_disc, physical)
        client.close()
        return {
            "status": "success",
            "message": f"'{physical}' container'ı yeniden başlatıldı.",
            "container": physical
        }
    except docker.errors.NotFound:
        try:
            client.close()
        except Exception:
            pass
        return {"status": "error", "message": f"Container {target} not found"}
    except Exception as e:
        try:
            client.close()
        except Exception:
            pass
        return {"status": "error", "message": f"Yeniden başlatma hatası: {str(e)}"}


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
        try:
            from management.postfix_maps import reload_virtual_mailboxes

            reload_virtual_mailboxes()
        except Exception as e:
            import logging
            logging.warning(f"Postfix virtual_mailbox reload skipped: {e}")

        return {
            "status": "success",
            "email": new_account.email,
            "remaining_slots": config.max_accounts - (current_count + 1)
        }
    except Exception as e:
        import logging
        logging.error(f"Create account error: {e}")
        return {"status": "error", "message": f"Hesap oluşturulamadı: {str(e)}"}