# /home/murat/Jir/jir-mail/core/api.py

from typing import Optional

from ninja import Query, Router, Schema
from django.conf import settings
from django.db import connection
from .models import MailAccount, MailDomain, MailRole
from saas.models import SystemConfig
import bcrypt
import os
import subprocess
import logging

logger = logging.getLogger(__name__)
router = Router()


class MailAccountSchema(Schema):
    username: str
    domain: str
    password: str


class QuotaUpdateSchema(Schema):
    quota_mb: int


class RoleUpdateSchema(Schema):
    role: str


class AccountUpdateSchema(Schema):
    username: str = None
    password: str = None


class EmailSettingsSchema(Schema):
    signature: str = ''
    auto_responder_enabled: bool = False
    auto_responder_subject: str = ''
    auto_responder_body: str = ''
    forward_to: str = ''
    forward_enabled: bool = False
    keep_copy: bool = True


class DomainVerificationSchema(Schema):
    domain: str


class DomainDNSRecordsSchema(Schema):
    domain: str
    spf_record: str
    dkim_record: str
    dmarc_record: str
    mx_record: str


def update_postfix_vmail(email, action="add"):
    vmail_path = getattr(settings, 'POSTFIX_VMAIL_PATH', '/etc/postfix/vmail_accounts')
    try:
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

        result = subprocess.run(
            ['postmap', vmail_path],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            logger.error(f"Postfix Mapping Hatası: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"Postfix güncelleme hatası: {e}")
        return False


def get_api_key():
    """API anahtarını SystemConfig / env'den al (hardcoded fallback yok)."""
    from jir_core.dashboard_auth import get_configured_local_key
    return get_configured_local_key()


def check_auth(request, key: str = None) -> bool:
    """Panel oturumu veya X-JIR-Local-Key. Query ?key= kabul edilmez."""
    from jir_core.dashboard_auth import require_panel_api
    return require_panel_api(request) is None


def check_panel_auth(request, key: str = None) -> bool:
    """Mail sunucusu paneli işlemleri — süper yönetici oturumu veya servis anahtarı."""
    from jir_core.dashboard_auth import require_panel_api
    return require_panel_api(request) is None


def check_self_or_panel(request, email: str, key: str = None) -> bool:
    from jir_core.dashboard_auth import require_self_or_panel
    return require_self_or_panel(request, email) is None


@router.get("/list-accounts", summary="Tüm Mail Hesaplarını Listele")
def list_mail_accounts(request, key: str = None):
    if not check_panel_auth(request, key):
        return {"status": "error", "message": "Yetkiniz yok. Süper yönetici yetkisi gerekir."}

    accounts = MailAccount.objects.select_related('domain').all()
    config = SystemConfig.objects.first()

    account_data = [
        {
            "email": acc.email,
            "username": acc.username,
            "domain": acc.domain.name,
            "created_at": acc.created_at,
            "is_active": acc.is_active,
            "quota_bytes": acc.quota_bytes,
            "quota_mb": acc.quota_mb,
            "role": acc.role,
            "role_display": acc.get_role_display(),
            "is_superuser": acc.is_bootstrap_admin(),
            "permissions": acc.permissions_summary(),
        } for acc in accounts
    ]

    return {
        "status": "success",
        "total": accounts.count(),
        "active_count": accounts.filter(is_active=True).count(),
        "limit": config.max_accounts,
        "tier": config.tier,
        "accounts": account_data
    }


@router.patch("/toggle-account/{email}", summary="Hesabı Aktif/Pasif Yap")
def toggle_account(request, email: str, key: str = None):
    if not check_panel_auth(request, key):
        return {"status": "error", "message": "Yetkiniz yok. Süper yönetici yetkisi gerekir."}

    try:
        account = MailAccount.objects.get(email=email)
        account.is_active = not account.is_active
        account.save()

        status_text = "Aktif" if account.is_active else "Pasif"
        return {"status": "success", "message": f"Hesap durumu {status_text} olarak güncellendi.", "is_active": account.is_active}
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.patch("/update-quota/{email}", summary="Hesap Kota Güncelle")
def update_quota(request, email: str, key: str = None, data: QuotaUpdateSchema = None):
    if not check_panel_auth(request, key):
        return {"status": "error", "message": "Yetkiniz yok. Süper yönetici yetkisi gerekir."}

    try:
        account = MailAccount.objects.get(email=email)
        quota_bytes = 0 if data.quota_mb == 0 else data.quota_mb * 1024 * 1024
        account.quota_bytes = quota_bytes
        account.save()

        quota_display = "Sınırsız" if quota_bytes == 0 else f"{data.quota_mb} MB"
        return {"status": "success", "message": f"Kota {quota_display} olarak güncellendi.", "quota_bytes": quota_bytes}
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


def _active_full_admin_count() -> int:
    return MailAccount.objects.filter(role=MailRole.FULL_ACCESS, is_active=True).count()


@router.patch("/update-role/{email}", summary="Hesap Rol Güncelle")
def update_role(request, email: str, data: RoleUpdateSchema, key: str = None):
    if not check_panel_auth(request, key):
        return {"status": "error", "message": "Yetkiniz yok. Süper yönetici yetkisi gerekir."}

    valid_roles = [choice[0] for choice in MailRole.choices]
    new_role = (data.role or '').strip().upper()
    if new_role not in valid_roles:
        return {"status": "error", "message": f"Geçersiz rol. Geçerli: {valid_roles}"}

    try:
        from urllib.parse import unquote

        email_key = unquote(email).strip().lower()
        account = MailAccount.objects.get(email__iexact=email_key)
        if account.role == MailRole.FULL_ACCESS and new_role != MailRole.FULL_ACCESS:
            if _active_full_admin_count() <= 1:
                return {
                    "status": "error",
                    "message": "Son süper yöneticinin yetkisi kaldırılamaz.",
                }
        if account.is_bootstrap_admin() and new_role != MailRole.FULL_ACCESS:
            return {
                "status": "error",
                "message": "Kurulum yöneticisinin süper yönetici yetkisi değiştirilemez.",
            }

        account.role = new_role
        account.save(update_fields=['role'])

        return {
            "status": "success",
            "message": f"Rol '{account.get_role_display()}' olarak güncellendi.",
            "role": account.role,
            "permissions": account.permissions_summary(),
        }
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.patch("/update-settings/{email}", summary="Hesap Email Ayarlarını Güncelle")
def update_email_settings(request, email: str, key: str = None, data: EmailSettingsSchema = None):
    if not check_self_or_panel(request, email, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        account = MailAccount.objects.get(email=email)

        account.signature = data.signature
        account.auto_responder_enabled = data.auto_responder_enabled
        account.auto_responder_subject = data.auto_responder_subject
        account.auto_responder_body = data.auto_responder_body
        account.forward_to = data.forward_to
        account.forward_enabled = data.forward_enabled
        account.keep_copy = data.keep_copy
        account.save()

        return {
            "status": "success",
            "message": "Email ayarları güncellendi.",
            "settings": {
                "signature": account.signature,
                "auto_responder_enabled": account.auto_responder_enabled,
                "auto_responder_subject": account.auto_responder_subject,
                "auto_responder_body": account.auto_responder_body,
                "forward_to": account.forward_to,
                "forward_enabled": account.forward_enabled,
                "keep_copy": account.keep_copy
            }
        }
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.get("/account-settings/{email}", summary="Hesap Email Ayarlarını Getir")
def get_email_settings(request, email: str, key: str = None):
    if not check_self_or_panel(request, email, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        account = MailAccount.objects.get(email=email)

        return {
            "status": "success",
            "email": account.email,
            "settings": {
                "signature": account.signature,
                "auto_responder_enabled": account.auto_responder_enabled,
                "auto_responder_subject": account.auto_responder_subject,
                "auto_responder_body": account.auto_responder_body,
                "forward_to": account.forward_to,
                "forward_enabled": account.forward_enabled,
                "keep_copy": account.keep_copy
            }
        }
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.patch("/update-account/{email}", summary="Hesap Güncelle")
def update_account(request, email: str, key: str = None, data: AccountUpdateSchema = None):
    if not check_self_or_panel(request, email, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        account = MailAccount.objects.get(email=email)

        if data.username is not None:
            account.username = data.username
            new_email = f"{data.username}@{account.domain.name}".lower()
            if new_email != email:
                existing = MailAccount.objects.filter(email=new_email).exclude(id=account.id).first()
                if existing:
                    return {"status": "error", "message": "Bu e-posta adresi zaten kullanımda."}
                update_postfix_vmail(email, action="remove")
                account.email = new_email
                update_postfix_vmail(new_email, action="add")

        if data.password is not None and data.password:
            salt = bcrypt.gensalt()
            account.password_hash = bcrypt.hashpw(data.password.encode('utf-8'), salt).decode('utf-8')

        account.save()

        return {
            "status": "success",
            "message": "Hesap güncellendi",
            "email": account.email,
            "username": account.username
        }
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.delete("/delete-account/{email}", summary="Hesap Sil")
def delete_account(request, email: str, key: str = None):
    if not check_panel_auth(request, key):
        return {"status": "error", "message": "Yetkiniz yok. Süper yönetici yetkisi gerekir."}

    try:
        account = MailAccount.objects.get(email=email)
        if account.is_bootstrap_admin():
            return {"status": "error", "message": "Kurulum yöneticisi silinemez."}
        if account.role == MailRole.FULL_ACCESS and _active_full_admin_count() <= 1:
            return {"status": "error", "message": "Son süper yönetici silinemez."}
        update_postfix_vmail(email, action="remove")
        account.delete()

        return {"status": "success", "message": "Hesap silindi"}
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.get("/account-details/{email}", summary="Hesap Detayları")
def get_account_details(request, email: str, key: str = None):
    if not check_self_or_panel(request, email, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        account = MailAccount.objects.select_related('domain').get(email=email)

        return {
            "status": "success",
            "account": {
                "email": account.email,
                "username": account.username,
                "domain": account.domain.name,
                "is_active": account.is_active,
                "role": account.role,
                "quota_bytes": account.quota_bytes,
                "quota_mb": account.quota_mb,
                "created_at": account.created_at.isoformat(),
                "signature": account.signature,
                "auto_responder_enabled": account.auto_responder_enabled,
                "auto_responder_subject": account.auto_responder_subject,
                "auto_responder_body": account.auto_responder_body,
                "forward_to": account.forward_to,
                "forward_enabled": account.forward_enabled,
                "keep_copy": account.keep_copy
            }
        }
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.post("/create-account", summary="Yeni Mail Hesabı Oluştur")
def create_mail_account(request, data: MailAccountSchema, key: str = None):
    if not check_panel_auth(request, key):
        return {"status": "error", "message": "Yetkiniz yok. Süper yönetici yetkisi gerekir."}

    config = SystemConfig.objects.first()
    if not config:
        return {"status": "error", "message": "Sistem yapılandırması bulunamadı."}
    current_count = MailAccount.objects.count()

    if current_count >= config.max_accounts:
        return {"status": "error", "message": f"Limit aşıldı! Maksimum {config.max_accounts} hesap açabilirsiniz."}

    salt = bcrypt.gensalt()
    hashed_pw = bcrypt.hashpw(data.password.encode('utf-8'), salt).decode('utf-8')

    domain_obj, _ = MailDomain.objects.get_or_create(name=data.domain)
    email = f"{data.username}@{data.domain}".lower()

    try:
        new_account = MailAccount.objects.create(
            domain=domain_obj,
            username=data.username,
            email=email,
            password_hash=hashed_pw
        )
        update_postfix_vmail(email, action="add")
        return {
            "status": "success",
            "email": new_account.email,
            "remaining_slots": config.max_accounts - (current_count + 1)
        }
    except Exception as e:
        return {"status": "error", "message": "E-posta adresi kullanımda veya bir hata oluştu."}


@router.post("/generate-dns-records/{domain}", summary="DNS Kayıtları Oluştur / Yenile")
def generate_dns_records(
    request,
    domain: str,
    key: str = None,
    regenerate: bool = Query(False),
):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        domain_obj = MailDomain.objects.get(name=domain)

        if regenerate or not domain_obj.dkim_private_key:
            domain_obj.generate_dkim_keys()

        mail_server_hostname = getattr(settings, 'MAIL_SERVER_HOSTNAME', None) or f'mail.{domain_obj.name}'

        return {
            "status": "success",
            "domain": domain,
            "spf_record": domain_obj.spf_record,
            "dkim_record": domain_obj.dkim_record,
            "dmarc_record": domain_obj.dmarc_record,
            "mx_record": f"@ {mail_server_hostname}",
            "verification_status": domain_obj.verification_status,
            "verified_at": domain_obj.verified_at.isoformat() if domain_obj.verified_at else None
        }
    except MailDomain.DoesNotExist:
        return {"status": "error", "message": "Domain bulunamadı."}
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}


class DnsApplyBody(Schema):
    server_ip: Optional[str] = None
    credentials: Optional[dict] = None
    provider: Optional[str] = None


@router.post("/apply-dns/{domain}", summary="DNS kayıtlarını provider’a uygula")
def apply_dns_records(request, domain: str, data: DnsApplyBody = None, key: str = None):
    """Kayıtlı veya istekteki Cloudflare/Route53/Namecheap bilgisiyle zone’a yazar."""
    if not check_panel_auth(request, key):
        return {"status": "error", "message": "Yetkiniz yok. Süper yönetici yetkisi gerekir."}

    data = data or DnsApplyBody()
    try:
        from dns_providers.records import apply_mail_dns, detect_public_ip
        from dns_providers.system_dns import (
            credentials_configured,
            get_system_dns_config,
            normalize_provider_credentials,
            resolve_mail_hostname,
        )

        domain_obj = MailDomain.objects.get(name=domain)
        provider = (data.provider or domain_obj.dns_provider or 'manual').lower()
        credentials = data.credentials if data.credentials is not None else (domain_obj.dns_credentials or {})
        credentials = normalize_provider_credentials(provider, credentials)
        if provider == 'manual' or not credentials_configured(provider, credentials):
            sys_provider, sys_creds = get_system_dns_config()
            if sys_provider != 'manual' and credentials_configured(sys_provider, sys_creds):
                provider = sys_provider
                credentials = sys_creds
        if provider == 'manual':
            return {
                "status": "error",
                "message": "Otomatik uygulama için Cloudflare / Route53 / Namecheap seçin. "
                "Ayarlar → DNS bölümünden API token kaydedin veya kurulumda Cloudflare seçin.",
            }
        if not credentials_configured(provider, credentials):
            return {
                "status": "error",
                "message": f"{provider} API bilgisi bulunamadı. Ayarlar sayfasından token girin.",
            }

        mail_host = getattr(settings, 'MAIL_SERVER_HOSTNAME', None) or resolve_mail_hostname(domain_obj.name)
        outcome = apply_mail_dns(
            domain_obj.name,
            provider_name=provider,
            credentials=credentials,
            server_ip=(data.server_ip or detect_public_ip() or ''),
            mail_hostname=mail_host,
            domain_obj=domain_obj,
        )
        ok = outcome.get("success") or outcome.get("partial")
        return {
            "status": "success" if ok else "error",
            "message": outcome.get("message") or ("DNS uygulandı" if ok else "DNS uygulanamadı"),
            **outcome,
        }
    except MailDomain.DoesNotExist:
        return {"status": "error", "message": "Domain bulunamadı."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/list-domains", summary="Domain Listesi")
def list_domains(request, key: str = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    domains = MailDomain.objects.all()

    return {
        "status": "success",
        "domains": [
            {
                "id": d.id,
                "name": d.name,
                "is_active": d.is_active,
                "dkim_enabled": d.dkim_enabled,
                "verification_status": d.verification_status,
                "verified_at": d.verified_at.isoformat() if d.verified_at else None,
                "spf_record": d.spf_record,
                "dkim_record": d.dkim_record,
                "dmarc_record": d.dmarc_record,
                "dns_provider": d.dns_provider,
                "created_at": d.created_at.isoformat()
            } for d in domains
        ]
    }


@router.post("/verify-domain/{domain}", summary="Domain Doğrulama")
def verify_domain(request, domain: str, key: str = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        from datetime import datetime
        domain_obj = MailDomain.objects.get(name=domain)

        domain_obj.verification_status = 'verified'
        domain_obj.verified_at = datetime.now()
        domain_obj.save()

        return {
            "status": "success",
            "message": "Domain başarıyla doğrulandı",
            "verification_status": domain_obj.verification_status,
            "verified_at": domain_obj.verified_at.isoformat()
        }
    except MailDomain.DoesNotExist:
        return {"status": "error", "message": "Domain bulunamadı."}
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}


class AddDomainSchema(Schema):
    name: str
    is_active: bool = True


class UpdateDomainSchema(Schema):
    """Domain güncelleme (durum askıya alma, DNS sağlayıcı)."""
    is_active: Optional[bool] = None
    dns_provider: Optional[str] = None


class DomainDetailsSchema(Schema):
    id: int
    name: str
    is_active: bool
    dkim_enabled: bool
    verification_status: str
    verified_at: str = None
    spf_record: str
    dkim_record: str
    dmarc_record: str
    created_at: str
    account_count: int
    total_storage_mb: float


@router.post("/add-domain", summary="Yeni Domain Ekle")
def add_domain(request, data: AddDomainSchema, key: str = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        domain_name = data.name.lower().strip()

        from core.mail_domains import domain_hosting_error

        host_err = domain_hosting_error(domain_name)
        if host_err:
            return {"status": "error", "message": host_err}

        existing = MailDomain.objects.filter(name=domain_name).first()
        if existing:
            return {"status": "error", "message": "Bu domain zaten mevcut"}

        domain = MailDomain.objects.create(
            name=domain_name,
            is_active=data.is_active
        )

        from dns_providers.system_dns import auto_apply_domain_dns

        dns_outcome = auto_apply_domain_dns(domain)
        domain.refresh_from_db()

        message = 'Domain eklendi'
        if dns_outcome.get('applied') and dns_outcome.get('success'):
            message = dns_outcome.get('message') or 'Domain eklendi — DNS kayıtları otomatik uygulandı'
        elif dns_outcome.get('applied') and dns_outcome.get('partial'):
            message = dns_outcome.get('message') or 'Domain eklendi — DNS kısmen uygulandı'
        elif dns_outcome.get('applied') and not dns_outcome.get('success'):
            message = f"Domain eklendi — DNS uygulanamadı: {dns_outcome.get('message', 'bilinmeyen hata')}"

        return {
            "status": "success",
            "message": message,
            "domain": {
                "id": domain.id,
                "name": domain.name,
                "is_active": domain.is_active,
                "dns_provider": domain.dns_provider,
                "verification_status": domain.verification_status,
            },
            "dns": dns_outcome,
        }
    except Exception as e:
        return {"status": "error", "message": f"Hata: {str(e)}"}


@router.patch("/update-domain/{domain}", summary="Domain Güncelle")
def update_domain_settings(request, domain: str, data: UpdateDomainSchema, key: str = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        domain_obj = MailDomain.objects.get(name=domain)
        allowed_dns = {c[0] for c in MailDomain.DNS_PROVIDER_CHOICES}

        if data.is_active is not None:
            domain_obj.is_active = data.is_active
        if data.dns_provider is not None:
            if data.dns_provider not in allowed_dns:
                return {"status": "error", "message": "Geçersiz DNS sağlayıcı"}
            domain_obj.dns_provider = data.dns_provider

        domain_obj.save()
        return {
            "status": "success",
            "message": "Domain güncellendi",
            "domain": {
                "id": domain_obj.id,
                "name": domain_obj.name,
                "is_active": domain_obj.is_active,
                "dns_provider": domain_obj.dns_provider,
                "verification_status": domain_obj.verification_status,
            },
        }
    except MailDomain.DoesNotExist:
        return {"status": "error", "message": "Domain bulunamadı."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/domain-details/{domain}", summary="Domain Detayları")
def get_domain_details(request, domain: str, key: str = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        domain_obj = MailDomain.objects.get(name=domain)
        accounts = MailAccount.objects.filter(domain=domain_obj)

        total_storage = 0
        for acc in accounts:
            total_storage += acc.current_storage_bytes

        return {
            "status": "success",
            "domain": {
                "id": domain_obj.id,
                "name": domain_obj.name,
                "is_active": domain_obj.is_active,
                "dkim_enabled": domain_obj.dkim_enabled,
                "verification_status": domain_obj.verification_status,
                "verified_at": domain_obj.verified_at.isoformat() if domain_obj.verified_at else None,
                "spf_record": domain_obj.spf_record,
                "dkim_record": domain_obj.dkim_record,
                "dmarc_record": domain_obj.dmarc_record,
                "created_at": domain_obj.created_at.isoformat(),
                "account_count": accounts.count(),
                "total_storage_mb": round(total_storage / (1024 * 1024), 2)
            }
        }
    except MailDomain.DoesNotExist:
        return {"status": "error", "message": "Domain bulunamadı."}


@router.get("/dns-diagnose/{domain}", summary="DNS sağlayıcı tanılama (FULL)")
def dns_diagnose(request, domain: str, key: str = None):
    if not check_panel_auth(request, key):
        return {"status": "error", "message": "Yetkiniz yok. Süper yönetici yetkisi gerekir."}

    try:
        from dns_providers.records import detect_public_ip
        from dns_providers.system_dns import credentials_configured, get_system_dns_config, resolve_mail_hostname

        domain_obj = MailDomain.objects.get(name=domain)
        sys_provider, sys_creds = get_system_dns_config(persist_fallback=True)
        provider = (domain_obj.dns_provider or sys_provider or 'manual').lower()
        credentials = domain_obj.dns_credentials or sys_creds or {}
        if provider == 'manual' and sys_provider != 'manual':
            provider = sys_provider
            credentials = sys_creds

        diag = {
            "domain": domain_obj.name,
            "provider": provider,
            "credentials_configured": credentials_configured(provider, credentials),
            "system_provider": sys_provider,
            "system_credentials_configured": credentials_configured(sys_provider, sys_creds),
            "mail_hostname": resolve_mail_hostname(domain_obj.name),
            "server_ip": detect_public_ip() or '',
        }

        if provider == 'cloudflare' and credentials_configured('cloudflare', credentials):
            from dns_providers import get_provider
            cf = get_provider('cloudflare', credentials)
            verify = getattr(cf, 'verify_mail_domain', None)
            if callable(verify):
                diag["cloudflare"] = verify(domain_obj.name)

        if diag["credentials_configured"]:
            diag["status"] = "ok" if diag.get("cloudflare", {}).get("success", True) else "warning"
        else:
            diag["status"] = "error"
            diag["message"] = (
                "Cloudflare API token kayıtlı değil. "
                "Kurulum sihirbazında Cloudflare seçip token girin veya Ayarlar → DNS alanından ekleyin."
            )

        return {"status": "success", "diagnostics": diag}
    except MailDomain.DoesNotExist:
        return {"status": "error", "message": "Domain bulunamadı."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/delete-domain/{domain}", summary="Domain Sil")
def delete_domain(request, domain: str, key: str = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        domain_obj = MailDomain.objects.get(name=domain)
        account_count = MailAccount.objects.filter(domain=domain_obj).count()

        if account_count > 0:
            return {
                "status": "error",
                "message": f"Domain silinemez. {account_count} aktif hesap var. Önce hesapları silin."
            }

        domain_obj.delete()
        return {"status": "success", "message": "Domain silindi"}

    except MailDomain.DoesNotExist:
        return {"status": "error", "message": "Domain bulunamadı."}


@router.patch("/toggle-domain/{domain}", summary="Domain Aktif/Pasif")
def toggle_domain(request, domain: str, key: str = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        domain_obj = MailDomain.objects.get(name=domain)
        domain_obj.is_active = not domain_obj.is_active
        domain_obj.save()

        status_text = "Aktif" if domain_obj.is_active else "Pasif"
        return {
            "status": "success",
            "message": f"Domain {status_text} olarak güncellendi",
            "is_active": domain_obj.is_active
        }
    except MailDomain.DoesNotExist:
        return {"status": "error", "message": "Domain bulunamadı."}


class DomainAISettingsSchema(Schema):
    ai_enabled: Optional[bool] = None
    ai_provider: Optional[str] = None
    ai_default_model: Optional[str] = None
    ai_system_prompt_default: Optional[str] = None


@router.patch("/domain-ai/{domain}", summary="Domain AI ayarları (sunucu)")
def update_domain_ai(request, domain: str, data: DomainAISettingsSchema, key: str = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}
    try:
        domain_obj = MailDomain.objects.get(name=domain)
    except MailDomain.DoesNotExist:
        return {"status": "error", "message": "Domain bulunamadı."}
    fields = []
    for attr, val in data.dict(exclude_unset=True).items():
        if val is not None:
            setattr(domain_obj, attr, val)
            fields.append(attr)
    if fields:
        domain_obj.save(update_fields=fields)
    return {
        "status": "success",
        "domain": domain_obj.name,
        "ai_enabled": domain_obj.ai_enabled,
        "ai_default_model": domain_obj.ai_default_model,
    }