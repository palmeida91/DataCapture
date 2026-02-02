Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw data_collector_oee.py", 0, False
Set WshShell = Nothing