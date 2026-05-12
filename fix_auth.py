with open('/home/murat/Jir/jir-mail/core/api.py', 'r') as f:
    content = f.read()

old = '    expected_key = get_api_key()\n    if key != expected_key:'
new = '    if not check_auth(request, key):'
count = content.count(old)
content = content.replace(old, new)

with open('/home/murat/Jir/jir-mail/core/api.py', 'w') as f:
    f.write(content)

print(f'Replaced {count} occurrences')
