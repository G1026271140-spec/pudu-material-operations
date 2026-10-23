Option Explicit

Dim shell, args, command, index
Set shell = CreateObject("WScript.Shell")
Set args = WScript.Arguments
If args.Count = 0 Then WScript.Quit 2

command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File " & QuoteArg(args(0))
For index = 1 To args.Count - 1
    command = command & " " & QuoteArg(args(index))
Next
shell.Run command, 0, False

Function QuoteArg(value)
    QuoteArg = Chr(34) & Replace(CStr(value), Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
