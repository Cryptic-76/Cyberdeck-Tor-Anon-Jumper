' Cyberdeck Tor Suite - Stop (Ein-Klick, graceful, versteckt)
' SIGTERM an main.py -> sauberer Shutdown (Firewall/nft/DNS/RAM-Disk zurueckgesetzt).
Dim shell
Set shell = CreateObject("WScript.Shell")
Dim cmdLine
cmdLine = "wsl.exe -d kali-linux -- bash /mnt/c/tor-expert-bundle/tor_wsl_suite/tools/stop_suite.sh"
shell.Run cmdLine, 0, True
WScript.Quit