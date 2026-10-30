using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
namespace DeepSteamInstaller {
 internal static class InstallerShortcutTests {
  static void Check(bool value, string message) { if (!value) throw new Exception(message); }
  static void Link(string file, string target, string arguments) {
   object shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
   object link = null;
   try {
    link = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[]{file});
    link.GetType().InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[]{target});
    link.GetType().InvokeMember("Arguments", BindingFlags.SetProperty, null, link, new object[]{arguments});
    link.GetType().InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
   } finally { if (link != null) Marshal.FinalReleaseComObject(link); Marshal.FinalReleaseComObject(shell); }
  }
  [STAThread] static int Main(string[] args) {
   try {
    AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
    AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
    string root = Path.GetFullPath(args[0]);
    string desktop = Path.Combine(root, "isolated desktop"); Directory.CreateDirectory(desktop);
    string programs = Path.Combine(root, "isolated programs"); Directory.CreateDirectory(programs);
    var context = new UninstallContext { Root=Path.Combine(root, "owned app"), Id=Guid.NewGuid().ToString("N") };
    string launcher=Path.Combine(context.Root, "DeepSteam.exe");
    string[] owned={"DeepSteam.lnk", "Stop DeepSteam.lnk", "关闭 DeepSteam.lnk"};
    foreach(string name in owned) Link(Path.Combine(desktop,name),launcher,name=="DeepSteam.lnk"?"--launch":"--stop");
    string other=Path.Combine(desktop,"关闭 DeepSteam other.lnk");
    Link(other,Path.Combine(root,"another app","DeepSteam.exe"),"--stop");
    string wrong=Path.Combine(desktop,"DeepSteam user action.lnk"); Link(wrong,launcher,"--unrelated");
    string menu=Path.Combine(programs,"DeepSteam-"+context.Id.Substring(0,8)); Directory.CreateDirectory(menu);
    string uninstall=Path.Combine(menu,"Uninstall DeepSteam.lnk");
    Link(uninstall,Path.Combine(context.Root,"Uninstall-DeepSteam.exe"),"");
    UninstallCore.RemoveShortcuts(context,desktop,programs);
    foreach(string name in owned) Check(!File.Exists(Path.Combine(desktop,name)),"Owned shortcut retained: "+name);
    Check(!File.Exists(uninstall),"Uninstall shortcut retained");
    Check(!Directory.Exists(menu),"Empty owned menu retained");
    Check(File.Exists(other),"Another installation shortcut removed");
    Check(File.Exists(wrong),"Unrelated user action removed");
    Console.WriteLine("PASS 7 assertions; actual COM shortcuts in isolated folders; no desktop operations"); return 0;
   } catch(Exception error) { Console.Error.WriteLine(error); return 1; }
  }
 }
}
