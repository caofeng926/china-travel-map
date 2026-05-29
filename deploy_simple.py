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

# Simple food API test
stdin, stdout, stderr = c.exec_command("curl -sk --compressed 'https://vps5865.top/travel/api/pois?type=food&page_size=5'", timeout=30)
stdin.close()
import sys
data = stdout.read()
sys.stdout.buffer.write(data[:500])
sys.stdout.buffer.flush()

c.close()
