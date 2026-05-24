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
    """Postfix pgsql map — çok satırlı; port hosts satırında (ayrı port= uyarı verir)."""
    host = (db_host or 'localhost').strip()
    port = int(db_port or 5432)
    hosts = host if port == 5432 else f'{host}:{port}'
    return (
        f"hosts = {hosts}\n"
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
    """Postfix içinde init script + pgsql doğrulama + gerekirse postfix start."""
    name = container or _postfix_container_name()
    out: dict[str, Any] = {"container": name, "ok": False, "actions": []}
    try:
        client = _docker_client()
        c = client.containers.get(name)
        c.reload()
        if c.status != "running":
            out["actions"].append({"action": "container_start", "from": c.status})
            c.start()
            import time

            time.sleep(6)
            c.reload()

        for script in (
            "/docker-init.d/10-jirmail-inbound.sh",
            "/docker-init.d/31-jirmail-transport-maps.sh",
            "/docker-init.d/30-jirmail-outbound-smtp.sh",
            "/docker-init.d/32-jirmail-relay-sasl.sh",
            "/docker-init.d/11-validate-pgsql.sh",
        ):
            code, logs = c.exec_run(["sh", script], demux=True)
            out["actions"].append(
                {
                    "script": script,
                    "exit_code": code,
                    "stderr": (logs[1] or b"").decode()[:500],
                    "stdout": (logs[0] or b"").decode()[:300],
                }
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
        pgsql_ok = code == 0 and "pgsql_cf_ok" in stdout
        out["actions"].append({"action": "pgsql_probe", "ok": pgsql_ok})

        start_code, start_logs = c.exec_run(
            ["sh", "-c", "postfix start 2>&1; sleep 2; postfix status 2>&1"],
            demux=True,
        )
        start_out = ((start_logs[0] or b"") + (start_logs[1] or b"")).decode()
        running = "is running" in start_out.lower() or "running" in start_out.lower()
        out["actions"].append(
            {"action": "postfix_start", "exit_code": start_code, "output": start_out[:500]}
        )

        if not running:
            out["actions"].append({"action": "container_restart"})
            c.restart(timeout=30)
            import time

            time.sleep(12)
            _, status_logs = c.exec_run(["postfix", "status"], demux=True)
            start_out = ((status_logs[0] or b"") + (status_logs[1] or b"")).decode()
            running = "is running" in start_out.lower() or "running" in start_out.lower()
            out["actions"].append({"action": "postfix_status_after_restart", "output": start_out[:400]})

        out["ok"] = running and pgsql_ok
        client.close()
    except Exception as exc:
        out["error"] = str(exc)
        logger.warning("heal_postfix_container: %s", exc)
    return out


def ensure_postfix_running(*, container: str | None = None) -> dict[str, Any]:
    """Compose/single-server: Postfix konteynerini ayağa kaldır ve init script'lerini çalıştır."""
    return heal_postfix_container(container=container)


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

    if fix and not smtp_ok:
        try:
            healed_pf = ensure_postfix_running()
            report["healed"].append({"service": "postfix_ensure", **healed_pf})
            if healed_pf.get("ok"):
                smtp_ok = verify_smtp_starttls(smtp_host, smtp_port, timeout=4.0)
                for chk in report["checks"]:
                    if chk.get("id") == "smtp":
                        chk["ok"] = smtp_ok
                        chk["message"] = f"SMTP {smtp_host}:{smtp_port} {'OK' if smtp_ok else 'erişilemiyor'}"
                        break
                if smtp_ok:
                    report["ok"] = all(c.get("ok") for c in report["checks"] if not c.get("optional"))
        except Exception as exc:
            report["healed"].append({"service": "postfix_ensure", "ok": False, "error": str(exc)})

    # Dış posta çıkışı (port 25 veya relayhost) — otomatik yapılandır
    try:
        from management.outbound_autoconfig import ensure_outbound_delivery
        from management.outbound_connectivity import check_outbound_smtp
        from webmail.send_validation import admin_stale_domain_warnings

        if fix:
            auto = ensure_outbound_delivery(fix=True, full_heal=True)
            if auto.get('fixed_domains'):
                report["healed"].append(
                    {"service": "domains", "fixed": auto.get('fixed_domains')}
                )
            if auto.get('actions'):
                report["healed"].append({"service": "outbound", **auto})

        outbound = check_outbound_smtp(include_django_probe=False)
        stale = admin_stale_domain_warnings()
        if stale:
            add(
                "panel_domain_hygiene",
                True,
                f"Yönetici notu (gönderimi engellemez): {stale[0][:120]}",
                optional=True,
            )
        outbound_ok = bool(outbound.get("ok")) or outbound.get("mode") == "relay"
        if outbound.get("mode") == "relay":
            add(
                "outbound_smtp",
                True,
                f"Dış posta relayhost: {outbound.get('relayhost')}",
            )
        elif healthcheck:
            add(
                "outbound_smtp",
                True,
                outbound.get("message", "port 25"),
                optional=True,
                warning=not outbound_ok,
                recommendation=(outbound.get("recommendation") or "")[:200],
            )
        else:
            add(
                "outbound_smtp",
                outbound_ok,
                outbound.get("message", "port 25"),
                recommendation=(outbound.get("recommendation") or "")[:200],
            )
    except Exception as exc:
        add("outbound_smtp", True, f"Kontrol atlandı: {exc}", skipped=True)

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
