import paramiko, time
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("43.136.175.219", username="root", password="2Vbrm5ah", timeout=30, look_for_keys=False, allow_agent=False)

sftp = c.open_sftp()
sftp.put(r"C:\Users\win\Documents\study\china-travel-map\frontend\index.html", "/root/china-travel-map/frontend/index.html")
sftp.put(r"C:\Users\win\Documents\study\china-travel-map\backend\server.py", "/root/china-travel-map/backend/server.py")
sftp.put(r"C:\Users\win\Documents\study\china-travel-map\backend\database.py", "/root/china-travel-map/backend/database.py")
sftp.close()
print("Files uploaded")

# Restart
transport = c.get_transport()
chan = transport.open_session(timeout=15)
chan.setblocking(0)
chan.get_pty()
chan.exec_command("cd /root/china-travel-map/backend && pkill -f python._server.py 2>/dev/null && sleep 1 && AMAP_KEY=fc5ea342775f94afaf8aec42694fdb4c nohup python3 server.py > /tmp/travel.log 2>&1 &")
time.sleep(4)
chan.close()
time.sleep(2)

# Verify food API
stdin, stdout, stderr = c.exec_command("curl -sk --compressed -o /tmp/food_test.json -w '%{http_code}' 'https://vps5865.top/travel/api/pois?type=food&page_size=2000'", timeout=30)
stdin.close()
print("Food API HTTP:", stdout.read().decode().strip())

stdin, stdout, stderr = c.exec_command("python3 -c 'import json; d=json.load(open(\"/tmp/food_test.json\")); provs={}; [provs.update({r.get(\"province\",\"?\"): provs.get(r.get(\"province\",\"?\"),0)+1}) for r in d[\"results\"] if r.get(\"type\")==\"food\"]; print(f\"Foods: {len(d[\"results\"])} total\"); [print(f\"  {k}: {v}\") for k,v in sorted(provs.items(), key=lambda x:-x[1])[:10]]', timeout=15)
stdin.close()
print(stdout.read().decode()[:500])

c.close()
