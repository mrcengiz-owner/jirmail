# Dovecot PostgreSQL — şablon (sırlar repoda yok).
# Çalışma anında entrypoint: envsubst ile /etc/dovecot/dovecot-sql.conf.ext üretilir.
# Gerekli ortam: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

driver = pgsql
connect = host=$DB_HOST port=$DB_PORT dbname=$DB_NAME user=$DB_USER password=$DB_PASS

default_pass_scheme = bcrypt

password_query = SELECT email as user, password_hash AS password, \
  '/var/mail/vhosts/%d/%n' AS userdb_home, \
  '/var/mail/vhosts/%d/%n' AS mail, \
  5000 AS uid, 5000 AS gid, \
  COALESCE(quota_bytes, 52428800) AS quota_bytes \
  FROM core_mailaccount WHERE email = '%u' AND is_active = true

user_query = SELECT '/var/mail/vhosts/%d/%n' AS home, \
  '/var/mail/vhosts/%d/%n' AS mail, \
  5000 AS uid, 5000 AS gid, \
  COALESCE(quota_bytes, 52428800) AS quota_bytes \
  FROM core_mailaccount WHERE email = '%u' AND is_active = true
