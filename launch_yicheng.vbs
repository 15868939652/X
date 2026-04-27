Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(fso.GetParentFolderName(WScript.FullName), "pythonw.exe")
guiPath = fso.BuildPath(base, "launcher_gui.pyw")
sh.CurrentDirectory = base
If fso.FileExists(pythonw) Then
    sh.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & guiPath & Chr(34), 0, False
Else
    sh.Run "pythonw " & Chr(34) & guiPath & Chr(34), 0, False
End If
