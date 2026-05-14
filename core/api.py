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
    try:
        config = SystemConfig.objects.first()
        if config and config.jir_local_key:
            return config.jir_local_key
    except Exception:
        pass
    return getattr(settings, 'JIR_LOCAL_KEY', None)


def check_auth(request, key: str = None) -> bool:
    """Key veya session ile yetki kontrolü."""
    # Session'dan giriş yapmış kullanıcı her zaman yetkili
    if hasattr(request, 'session') and request.session.get('is_logged_in'):
        return True
    # Key kontrolü
    expected = get_api_key()
    if expected and key == expected:
        return True
    return False


@router.get("/list-accounts", summary="Tüm Mail Hesaplarını Listele")
def list_mail_accounts(request, key: str = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

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
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

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
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        account = MailAccount.objects.get(email=email)
        quota_bytes = 0 if data.quota_mb == 0 else data.quota_mb * 1024 * 1024
        account.quota_bytes = quota_bytes
        account.save()

        quota_display = "Sınırsız" if quota_bytes == 0 else f"{data.quota_mb} MB"
        return {"status": "success", "message": f"Kota {quota_display} olarak güncellendi.", "quota_bytes": quota_bytes}
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.patch("/update-role/{email}", summary="Hesap Rol Güncelle")
def update_role(request, email: str, key: str = None, data: RoleUpdateSchema = None):
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    valid_roles = [choice[0] for choice in MailRole.choices]
    if data.role not in valid_roles:
        return {"status": "error", "message": f"Geçersiz rol. Geçerli: {valid_roles}"}

    try:
        account = MailAccount.objects.get(email=email)
        account.role = data.role
        account.save()

        return {"status": "success", "message": f"Rol '{account.get_role_display()}' olarak güncellendi.", "role": account.role}
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.patch("/update-settings/{email}", summary="Hesap Email Ayarlarını Güncelle")
def update_email_settings(request, email: str, key: str = None, data: EmailSettingsSchema = None):
    if not check_auth(request, key):
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
    if not check_auth(request, key):
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
    if not check_auth(request, key):
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
    if not check_auth(request, key):
        return {"status": "error", "message": "Yetkisiz erişim!"}

    try:
        account = MailAccount.objects.get(email=email)
        update_postfix_vmail(email, action="remove")
        account.delete()

        return {"status": "success", "message": "Hesap silindi"}
    except MailAccount.DoesNotExist:
        return {"status": "error", "message": "Hesap bulunamadı."}


@router.get("/account-details/{email}", summary="Hesap Detayları")
def get_account_details(request, email: str, key: str = None):
    if not check_auth(request, key):
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
def create_mail_account(request, data: MailAccountSchema):
    config = SystemConfig.objects.first()
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

        existing = MailDomain.objects.filter(name=domain_name).first()
        if existing:
            return {"status": "error", "message": "Bu domain zaten mevcut"}

        domain = MailDomain.objects.create(
            name=domain_name,
            is_active=data.is_active
        )

        return {
            "status": "success",
            "message": "Domain eklendi",
            "domain": {
                "id": domain.id,
                "name": domain.name,
                "is_active": domain.is_active
            }
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