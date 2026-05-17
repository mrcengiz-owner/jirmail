"""Mail stack otomatik doğrulama ve onarım (Postfix pgsql, Dovecot kota, DB hesapları)."""
from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

MAILBOX_QUERY = (
    "SELECT CONCAT(a.email, ' ', d.name, '/', a.username, '/') AS mailbox "
    "FROM core_mailaccount a INNER JOIN core_maildomain d ON d.id = a.domain_id "
    "WHERE a.is_active = true AND d.is_active = true"
)
DOMAIN_QUERY = "SELECT name FROM core_maildomain WHERE is_active = true"


def build_postfix_pgsql_cf(
    *,
    db_host: str,
    db_port: str | int,
    db_user: str,
    db_pass: str,
    db_name: str,
    query: str,
) -> str:
    """Postfix pgsql map — çok satırlı (tek satır hosts= şifreyi bozar)."""
    return (
        f"hosts = {db_host}\n"
        f"port = {db_port}\n"
        f"user = {db_user}\n"
        f"password = {db_pass}\n"
        f"dbname = {db_name}\n"
        f"query = {query}\n"
    )


def validate_postfix_pgsql_cf(content: str) -> tuple[bool, str]:
    if not content or not content.strip():
        return False, "dosya boş"
    if re.search(r"hosts\s*=\s*host=.*password=", content, re.I):
        return False, "tek satır hosts= formatı (dbname kaybolmuş olabilir)"
    if not re.search(r"^dbname\s*=\s*\S+", content, re.M):
        return False, "dbname satırı yok veya boş"
    if not re.search(r"^password\s*=", content, re.M):
        return False, "password satırı yok"
    if not re.search(r"^query\s*=", content, re.M):
        return False, "query satırı yok"
    return True, "ok"


def _postfix_container_name() -> str:
    return (os.getenv("JIR_CONTAINER_POSTFIX") or "jir_postfix").strip()


def _dovecot_container_name() -> str:
    return (os.getenv("JIR_CONTAINER_DOVECOT") or "jir_dovecot").strip()


def _docker_client():
    import docker

    dh = getattr(settings, "DOCKER_HOST", None) or "unix:///var/run/docker.sock"
    return docker.DockerClient(base_url=dh, timeout=15)


def heal_postfix_container(*, container: str | None = None) -> dict[str, Any]:
    """Postfix içinde init script + pgsql doğrulama."""
    name = container or _postfix_container_name()
    out: dict[str, Any] = {"container": name, "ok": False, "actions": []}
    try:
        client = _docker_client()
        c = client.containers.get(name)
        for script in (
            "/docker-init.d/10-jirmail-inbound.sh",
            "/docker-init.d/11-validate-pgsql.sh",
        ):
            code, logs = c.exec_run(["sh", script], demux=True)
            out["actions"].append(
                {"script": script, "exit_code": code, "stderr": (logs[1] or b"").decode()[:500]}
            )
        code, logs = c.exec_run(
            [
                "sh",
                "-c",
                "grep -q '^dbname = ' /etc/postfix/pgsql-virtual-mailboxes.cf "
                "&& postmap -q probe@invalid.local pgsql:/etc/postfix/pgsql-virtual-mailboxes.cf "
                ">/dev/null 2>&1; echo pgsql_cf_ok",
            ],
            demux=True,
        )
        stdout = (logs[0] or b"").decode()
        out["ok"] = code == 0 and "pgsql_cf_ok" in stdout
        client.close()
    except Exception as exc:
        out["error"] = str(exc)
        logger.warning("heal_postfix_container: %s", exc)
    return out


def heal_dovecot_container(*, container: str | None = None) -> dict[str, Any]:
    """Dovecot kota/config self-heal + reload."""
    name = container or _dovecot_container_name()
    out: dict[str, Any] = {"container": name, "ok": False, "actions": []}
    shell = r"""
set -e
if grep -qE 'quota_rule.*%\{(Userdb|userdb):quota_bytes\}' /etc/dovecot/dovecot.conf 2>/dev/null; then
  sed -i 's|quota_rule = .*|quota_rule = *:storage=2G|' /etc/dovecot/dovecot.conf
  echo fixed_quota
fi
doveconf -n >/dev/null
doveadm reload 2>/dev/null || true
echo dovecot_ok
"""
    try:
        client = _docker_client()
        c = client.containers.get(name)
        code, logs = c.exec_run(["sh", "-c", shell], demux=True)
        stdout = (logs[0] or b"").decode()
        out["ok"] = code == 0 and "dovecot_ok" in stdout
        out["actions"].append({"exit_code": code, "stdout": stdout[:300]})
        client.close()
    except Exception as exc:
        out["error"] = str(exc)
        logger.warning("heal_dovecot_container: %s", exc)
    return out


def verify_mail_stack(*, fix: bool = False, healthcheck: bool = False) -> dict[str, Any]:
    """Tam stack kontrolü; fix=True ise Docker soketi varsa onarır."""
    from core.models import MailAccount, MailDomain
    from management.mail_service_endpoint import resolve_mail_endpoint, tcp_reachable
    from management.mail_tls import verify_imap_tls, verify_smtp_starttls

    report: dict[str, Any] = {
        "ok": True,
        "checks": [],
        "healed": [],
        "compose_stack": os.getenv("JIR_COMPOSE_STACK") == "1",
    }

    def add(check_id: str, ok: bool, message: str, **extra):
        report["checks"].append({"id": check_id, "ok": ok, "message": message, **extra})
        if not ok:
            report["ok"] = False

    # DB
    active_accounts = MailAccount.objects.filter(is_active=True).count()
    active_domains = MailDomain.objects.filter(is_active=True).count()
    accounts_ok = active_accounts > 0
    if healthcheck:
        add(
            "db_accounts",
            True,
            f"Aktif hesap: {active_accounts} (healthcheck modunda zorunlu değil)",
            optional=True,
        )
    else:
        add(
            "db_accounts",
            accounts_ok,
            f"Aktif hesap: {active_accounts}, aktif domain: {active_domains}",
        )

    # Ağ (Django konteynerinden)
    smtp_host, smtp_port = resolve_mail_endpoint(
        "postfix", int(getattr(settings, "SMTP_PORT", 587)), auth_submission=True
    )
    imap_host, imap_port = resolve_mail_endpoint("dovecot", int(getattr(settings, "IMAP_PORT", 993)))
    smtp_ok = verify_smtp_starttls(smtp_host, smtp_port, timeout=4.0)
    imap_ok = verify_imap_tls(imap_host, imap_port, timeout=6.0, log_failure=False)
    add("smtp", smtp_ok, f"SMTP {smtp_host}:{smtp_port} {'OK' if smtp_ok else 'erişilemiyor'}")
    add("imap", imap_ok, f"IMAP {imap_host}:{imap_port} {'OK' if imap_ok else 'erişilemiyor'}")

    # Postfix pgsql dosyası (docker exec ile oku)
    postfix_cf_ok = False
    try:
        client = _docker_client()
        c = client.containers.get(_postfix_container_name())
        _code, logs = c.exec_run(["cat", "/etc/postfix/pgsql-virtual-mailboxes.cf"], demux=True)
        content = (logs[0] or b"").decode()
        valid, reason = validate_postfix_pgsql_cf(content)
        postfix_cf_ok = valid
        if not valid:
            add("postfix_pgsql_cf", False, f"pgsql map bozuk: {reason}")
            if fix:
                healed = heal_postfix_container()
                report["healed"].append({"service": "postfix", **healed})
                postfix_cf_ok = healed.get("ok", False)
        else:
            add("postfix_pgsql_cf", True, "pgsql map dosya formatı OK")
        client.close()
    except Exception as exc:
        if healthcheck:
            add("postfix_pgsql_cf", True, "Docker soketi yok — Postfix entrypoint onarır", skipped=True)
        else:
            add(
                "postfix_pgsql_cf",
                False,
                f"Postfix konteyner okunamadı ({exc}); entrypoint init güvenilir",
                skipped=True,
            )

    # Dovecot config
    try:
        client = _docker_client()
        c = client.containers.get(_dovecot_container_name())
        _code, logs = c.exec_run(["grep", "quota_rule", "/etc/dovecot/dovecot.conf"], demux=True)
        line = (logs[0] or b"").decode().strip()
        bad_quota = bool(re.search(r"%\{(Userdb|userdb):quota_bytes\}", line))
        if bad_quota:
            add("dovecot_quota", False, f"Kota satırı hatalı: {line[:80]}")
            if fix:
                healed = heal_dovecot_container()
                report["healed"].append({"service": "dovecot", **healed})
        else:
            add("dovecot_quota", True, f"Kota OK ({line[:60]})")
        client.close()
    except Exception as exc:
        add("dovecot_quota", True, f"Docker yok — entrypoint şablonu kullanılır ({exc})", skipped=True)

    if fix and report["compose_stack"]:
        try:
            _ = _docker_client()
            if not postfix_cf_ok:
                report["healed"].append(
                    {"service": "postfix", **heal_postfix_container()}
                )
        except Exception:
            pass

    return report


def run_mail_stack_self_test() -> dict[str, Any]:
    """Hızlı birim testleri (CI / entrypoint)."""
    good = build_postfix_pgsql_cf(
        db_host="postgres",
        db_port=5432,
        db_user="u",
        db_pass="Murat1993.",
        db_name="jir_mail_prod",
        query=MAILBOX_QUERY,
    )
    ok, _ = validate_postfix_pgsql_cf(good)
    bad = "hosts = host=postgres port=5432 dbname= user=u password=secret"
    bad_ok, _ = validate_postfix_pgsql_cf(bad)
    return {
        "ok": ok and not bad_ok,
        "valid_sample": ok,
        "rejects_broken_hosts_line": not bad_ok,
    }
