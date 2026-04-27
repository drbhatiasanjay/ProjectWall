' ProjectWall silent launcher — double-click this file.
' Runs pythonw (no console), browser opens automatically once the server is ready.
Option Explicit

Dim sh, fso, scriptDir, logPath, cmd, rc
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FolderExists(scriptDir & "\logs") Then fso.CreateFolder(scriptDir & "\logs")

logPath = scriptDir & "\logs\wall-launcher.log"
Dim ts
Set ts = fso.OpenTextFile(logPath, 8, True)
ts.WriteLine "[" & Now & "] launcher starting, scriptDir=" & scriptDir

sh.CurrentDirectory = scriptDir
cmd = "cmd.exe /c """"" & scriptDir & "\.venv\Scripts\pythonw.exe"" -m cli.wall serve --quiet >> """ & logPath & """ 2>&1"""
ts.WriteLine "[" & Now & "] cmd=" & cmd

On Error Resume Next
rc = sh.Run(cmd, 0, False)
If Err.Number <> 0 Then
  ts.WriteLine "[" & Now & "] Run failed: " & Err.Description
Else
  ts.WriteLine "[" & Now & "] Run returned " & rc
End If
On Error Goto 0

ts.Close
