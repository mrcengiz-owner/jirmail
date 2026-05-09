import requests
resp = requests.post("http://127.0.0.1:8000/api/management/test-db", json={
    "db_type": "sqlite",
    "db_host": "localhost",
    "db_port": 5432,
    "db_name": "test",
    "db_user": "test",
    "db_pass": "test"
})
print("Status:", resp.status_code)
print("Content-Type:", resp.headers.get("Content-Type"))
print("Response:", resp.text[:500])