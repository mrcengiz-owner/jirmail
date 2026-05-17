hosts = host=$DB_HOST port=$DB_PORT dbname=$DB_NAME user=$DB_USER password=$DB_PASS
query = SELECT CONCAT(a.email, ' ', d.name, '/', a.username, '/') AS mailbox FROM core_mailaccount a INNER JOIN core_maildomain d ON d.id = a.domain_id WHERE a.is_active = true AND d.is_active = true
