' Cyberdeck Tor Suite - Start (Ein-Klick, versteckt, ohne Konsolenfenster)
' Stoppt NICHT, startet nur idempotent (laeuft bereits -> kein Doppelstart).
Dim shell
Set shell = CreateObject("WScript.Shell")
Dim cmdLine
cmdLine = "wsl.exe -d kali-linux -- bash /mnt/c/tor-expert-bundle/tor_wsl_suite/tools/start_suite.sh"
shell.Run cmdLine, 0, True
WScript.Quit