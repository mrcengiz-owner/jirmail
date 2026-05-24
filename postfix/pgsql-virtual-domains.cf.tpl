# Şablon — ÇALIŞAN dosya 10-jirmail-inbound.sh tarafından yazılır. Elle kopyalamayın.
# Eski: SELECT name FROM core_maildomain WHERE is_active = true  → gmail.com yerel sayılır (HATALI)
hosts = postgres
user = postgres
password = CHANGE_ME
dbname = jir_mail_prod
query = SELECT 1 FROM core_maildomain d INNER JOIN core_mailaccount a ON a.domain_id = d.id AND a.is_active = true WHERE d.is_active = true AND d.name NOT IN ('gmail.com') AND d.name='%s' LIMIT 1
