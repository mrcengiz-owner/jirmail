hosts = postgres
port = 5432
user = postgres
password = CHANGE_ME
dbname = jir_mail_prod
query = SELECT name FROM core_maildomain WHERE is_active = true
