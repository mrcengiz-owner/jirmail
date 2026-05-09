# /home/murat/Jir/jir-mail/core/api.py

from ninja import Router, Schema
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


@router.get("/list-accounts", summary="Tüm Mail Hesaplarını Listele")
def list_mail_accounts(request, key: str):
    if key != getattr(settings, 'JIR_LOCAL_KEY', None):
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
def toggle_account(request, email: str, key: str):
    if key != getattr(settings, 'JIR_LOCAL_KEY', None):
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
def update_quota(request, email: str, key: str, data: QuotaUpdateSchema):
    if key != getattr(settings, 'JIR_LOCAL_KEY', None):
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
def update_role(request, email: str, key: str, data: RoleUpdateSchema):
    if key != getattr(settings, 'JIR_LOCAL_KEY', None):
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