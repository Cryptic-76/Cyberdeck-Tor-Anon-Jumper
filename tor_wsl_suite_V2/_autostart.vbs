' Cyberdeck Tor Suite - autostart
' Launcher (versteckt, ohne Konsolenfenster) fuer den Windows Anmeldeordner.
' Startet die Suite in WSL; falls WSL noch nicht bereit war, eine kurze Wartezeit
' und ein Retry. Kein Fenster, kein Output.
Dim shell
Set shell = CreateObject("WScript.Shell")

' StartScript: wsl.exe -d kali-linux -- bash /mnt/c/tor-expert-bundle/tor_wsl_suite/tools/start_suite.sh
Dim cmdLine
cmdLine = "wsl.exe -d kali-linux -- bash /mnt/c/tor-expert-bundle/tor_wsl_suite/tools/start_suite.sh"

Dim attempt
For attempt = 1 To 3
    ' Warten, bis WSL/Docker verfuegbar ist (sonst schlaegt der Start fehl)
    Dim wslReady
    wslReady = shell.Run("wsl.exe -d kali-linux -- bash -c ""true""", 0, True)
    If wslReady = 0 Then
        Exit For
    End If
    WScript.Sleep 4000
Next

' Suite starten (0 = verstecktes Fenster, True = warten, bis beendet)
shell.Run cmdLine, 0, False

WScript.Quit