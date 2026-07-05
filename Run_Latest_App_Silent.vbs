Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(baseDir, ".venv\Scripts\pythonw.exe")
If Not fso.FileExists(pythonw) Then
    pythonw = fso.GetAbsolutePathName(fso.BuildPath(baseDir, "..\..\.venv\Scripts\pythonw.exe"))
End If

If Not fso.FileExists(pythonw) Then
    MsgBox "Python virtual environment was not found." & vbCrLf & pythonw, vbCritical, "Exam Generator"
    WScript.Quit 1
End If

shell.CurrentDirectory = baseDir
shell.Run """" & pythonw & """ -m src.gui.main", 1, False
