using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using Microsoft.Win32;
namespace DeepSteamInstaller {
 internal static class InstallerFinalizationTests {
  static int checks;
  static void Check(bool value, string message) { checks++; if (!value) throw new Exception(message); }
  static void Own(UninstallContext context, string name) {
   string path=Path.Combine(context.Root,name);
   context.Files.Add(new UninstallFile{Path=name,Hash=UninstallRegistration.Sha(path),Bytes=new FileInfo(path).Length});
  }
  static string Write(string root,string name,string value) {
   string path=Path.Combine(root,name); Directory.CreateDirectory(Path.GetDirectoryName(path)); File.WriteAllText(path,value); return path;
  }
  [STAThread] static int Main(string[] args) {
   try {
    AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
    AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
    string root=Path.GetFullPath(args[0]); Directory.CreateDirectory(root);
    var context=new UninstallContext{Root=root,Id=Guid.NewGuid().ToString("N"),Version="fixture",Manifest=Path.Combine(root,UninstallRegistration.ManifestName),WorkspaceSnapshotReady=true};
    context.DataRoots.Add(root);
    try {
     string[] factory={"runtime/python/Lib/site-packages/pageindex/config.yaml","reports/demo-lesson-video.mp4","reports/usability-repair-manifest.json"};
     var legacyRows=new List<object>();
     foreach(string name in factory) {
      Check(!UninstallRegistration.Protected(name),"Factory file must be eligible: "+name);
      string file=Write(root,name,"packaged fixture");
      legacyRows.Add(new {path=name,sha256=UninstallRegistration.Sha(file),bytes=new FileInfo(file).Length});
     }
     // Match the real r11.4 omission: the trusted payload contains the defaults,
     // but their individual paths are absent from the old uninstall inventory.
     Write(root,"installer/payload-manifest.json",UninstallUpgrade.Serialize(new {files=legacyRows.ToArray()}));
     Own(context,"installer/payload-manifest.json");
     Check(UninstallRegistration.Protected("data/config.yaml"),"Private configuration protection lost");
     Check(UninstallRegistration.Protected("reports/user-report.json"),"User report protection lost");
     string keep=Write(root,"data/config.yaml","keep private fixture");
     string edited="runtime/python/Lib/site-packages/rapidocr/config.yaml";
     Write(root,edited,"factory value"); Own(context,edited); Write(root,edited,"user changed value");
     string launcher=Path.Combine(root,"DeepSteam.exe");
     using(var file=new FileStream(launcher,FileMode.CreateNew,FileAccess.Write,FileShare.None)) file.SetLength((long)Int32.MaxValue+257);
     // This is a real >2 GiB file, not a mocked size; old finalBytes code fails.
     Own(context,"DeepSteam.exe"); Write(root,"Uninstall-DeepSteam.exe","fixture uninstaller"); Own(context,"Uninstall-DeepSteam.exe");
     Write(root,Program.InstalledMarker,"DeepSteam fixture"); Own(context,Program.InstalledMarker);
     UninstallRegistration.Write(context);
     var watch=Stopwatch.StartNew();
     UninstallCore.Remove(context,false,delegate(UninstallContext ignored){},delegate(string text){},false);
     Check(!File.Exists(launcher),"Large embedded launcher retained");
     Check(!File.Exists(Path.Combine(root,"Uninstall-DeepSteam.exe")),"Uninstaller retained");
     foreach(string name in factory) Check(!File.Exists(Path.Combine(root,name)),"Factory file retained: "+name);
     Check(File.ReadAllText(keep)=="keep private fixture","Private state changed");
     Check(File.ReadAllText(Path.Combine(root,edited))=="user changed value","Changed program configuration removed");
     Check(!File.Exists(context.Manifest),"Uninstall manifest retained");
     string recovery=Write(root,"rollback-fixture.exe","restore exact bytes");
     var pending=new Dictionary<string,string>();
     using(var backup=new UninstallFinalizationBackup()) { backup.Capture(recovery); File.Delete(recovery); backup.RestoreMissing(pending); }
     Check(pending.Count==0&&File.ReadAllText(recovery)=="restore exact bytes","Rollback failed");
     long peak=Process.GetCurrentProcess().PeakWorkingSet64;
     Check(peak<768L*1024*1024,"Rollback unexpectedly allocates file-sized memory");
     Console.WriteLine("PASS "+checks+" assertions; real large-file uninstall and rollback; seconds="+watch.Elapsed.TotalSeconds+"; peak_bytes="+peak);
     return 0;
    } finally { Registry.CurrentUser.DeleteSubKeyTree(UninstallRegistration.RegistryName(context.Id),false); }
   } catch(Exception error) { Console.Error.WriteLine(error); return 1; }
  }
 }
}
