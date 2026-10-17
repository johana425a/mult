using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;
namespace DeepSteamInstaller {
    internal static class ReviewFaults {
        internal static void AfterWrite(string phase) {
            if(Environment.GetEnvironmentVariable("DEEPSTEAM_REVIEW_CRASH")==phase) Environment.Exit(77);
        }
    }
    internal static class InstallerReviewTests {
        static void Check(bool value,string message){if(!value)throw new Exception(message);}
        static string Write(string root,string name,string value){string path=Path.Combine(root,name);Directory.CreateDirectory(Path.GetDirectoryName(path));File.WriteAllText(path,value,new UTF8Encoding(false));return path;}
        static void Own(UninstallContext ctx,string name){string path=Path.Combine(ctx.Root,name);ctx.Files.Add(new UninstallFile{Path=name,Hash=UninstallRegistration.Sha(path),Bytes=new FileInfo(path).Length});}
        [STAThread] static int Main(string[] args) {
            try{return Run(args);}catch(Exception error){Console.WriteLine(error.GetType().FullName+": "+error.Message);Console.WriteLine(error.StackTrace);return 1;}
        }
        static int Run(string[] args) {
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
            if(args.Length==4 && args[0]=="crash") {
                Environment.SetEnvironmentVariable("DEEPSTEAM_REVIEW_CRASH",args[3]);
                UninstallUpgrade.Refresh(args[1],args[2],UninstallRegistration.Sha(args[2]),args[2]+".report.json",false);
                return 1;
            }
            Check(UninstallUpgrade.PublicProgramPath("runtime/pglite/server.cjs"),"pglite program ownership missing");
            Check(!UninstallUpgrade.PublicProgramPath("extensions/mcp/fixture/memory.jsonl"),"extension data must remain protected");
            Check(UninstallRegistration.Protected("extensions/mcp/fixture/memory.jsonl"),"extension retention missing");
            int passed=0;
            foreach(string phase in new string[]{"DeepSteam.exe","Uninstall-DeepSteam.exe",Program.InstalledMarker,"manifest","identity","registry"}) {
                string baseDir=Path.Combine(Path.GetTempPath(),"DeepSteam-ownership-review-"+Guid.NewGuid().ToString("N"));
                string root=Path.Combine(baseDir,"DeepSteam");Directory.CreateDirectory(root);
                var ctx=new UninstallContext{Root=root,Id=Guid.NewGuid().ToString("N"),Version="fixture-before",Manifest=Path.Combine(root,UninstallRegistration.ManifestName),WorkspaceSnapshotReady=true};
                ctx.DataRoots.Add(root);
                try {
                    File.Copy(Application.ExecutablePath,Path.Combine(root,"DeepSteam.exe"));
                    File.Copy(Application.ExecutablePath,Path.Combine(root,"Uninstall-DeepSteam.exe"));
                    Write(root,Program.InstalledMarker,"DeepSteam "+ctx.Version+"\r\nfixture");
                    string payload=Write(root,"runtime/pglite/review-fixture.cjs","old-program");
                    foreach(string name in new string[]{"DeepSteam.exe","Uninstall-DeepSteam.exe",Program.InstalledMarker,"runtime/pglite/review-fixture.cjs"})Own(ctx,name);
                    UninstallRegistration.Write(ctx);UninstallRegistration.CreateUninstallShortcut(root);
                    string preserved=Write(root,"extensions/mcp/fixture/memory.jsonl","{\"value\":\"keep\"}\n");
                    string preservedHash=UninstallRegistration.Sha(preserved);
                    File.WriteAllText(payload,"new-program");
                    string receipt=Path.Combine(baseDir,"receipt.json");
                    File.WriteAllText(receipt,UninstallUpgrade.Serialize(new {kind="deepsteam-uninstall-update-v1",root=root,installation_id=ctx.Id,
                        previous_manifest_sha256=UninstallRegistration.Sha(ctx.Manifest),target_version=Program.Version,updater_sha256=UninstallRegistration.Sha(Application.ExecutablePath),
                        files=new object[]{new {path="runtime/pglite/review-fixture.cjs",sha256=UninstallRegistration.Sha(payload),bytes=new FileInfo(payload).Length}}}),new UTF8Encoding(false));
                    var psi=new ProcessStartInfo(Application.ExecutablePath,"crash "+InstallerForm.Quote(root)+" "+InstallerForm.Quote(receipt)+" "+InstallerForm.Quote(phase)){UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden};
                    using(var process=Process.Start(psi)){process.WaitForExit();Check(process.ExitCode==77,"fault did not terminate process at "+phase);}
                    UninstallUpgrade.Refresh(root,receipt,UninstallRegistration.Sha(receipt),receipt+".report.json",false);
                    var updated=UninstallRegistration.Verify(root);
                    Check(updated.Version==Program.Version,"ownership version not repaired");
                    Check(updated.Files.Find(row=>row.Path=="runtime/pglite/review-fixture.cjs").Hash==UninstallRegistration.Sha(payload),"new hash not owned");
                    Check(UninstallRegistration.Sha(preserved)==preservedHash,"extension data changed");
                    UninstallCore.Remove(updated,false,delegate(UninstallContext item){},delegate(string text){},false);
                    Check(!File.Exists(payload),"verified updated program was not removed");
                    Check(File.Exists(preserved)&&UninstallRegistration.Sha(preserved)==preservedHash,"uninstall deleted extension data");
                    passed++;
                } finally {
                    Registry.CurrentUser.DeleteSubKeyTree(UninstallRegistration.RegistryName(ctx.Id),false);
                    string shortcut=UninstallUpgrade.Shortcut(ctx);if(File.Exists(shortcut))File.Delete(shortcut);
                    string folder=Path.GetDirectoryName(shortcut);if(Directory.Exists(folder)&&Directory.GetFileSystemEntries(folder).Length==0)Directory.Delete(folder);
                }
            }
            Console.WriteLine("{\"passed\":true,\"hard_process_death_phases\":"+passed+",\"isolated_uninstall_cases\":"+passed+",\"live_installation_touched\":false}");
            return 0;
        }
    }
}
