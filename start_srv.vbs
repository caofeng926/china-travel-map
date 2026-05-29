Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\win\Documents\study\china-travel-map\backend"
WshShell.Run "cmd /c C:\Python314\python.exe -u server.py > C:\Users\win\Documents\study\china-travel-map\backend\srv_stdout.log 2>&1", 0, False
