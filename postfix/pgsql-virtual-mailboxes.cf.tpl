# Şablon — çalışan dosya 10-jirmail-inbound.sh ile çok satırlı yazılır (envsubst hosts satırı şifreyi bozar).
hosts = postgres
port = 5432
user = postgres
password = CHANGE_ME
dbname = jir_mail_prod
query = SELECT CONCAT(a.email, ' ', d.name, '/', a.username, '/') AS mailbox FROM core_mailaccount a INNER JOIN core_maildomain d ON d.id = a.domain_id WHERE a.is_active = true AND d.is_active = true
