using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Security.Cryptography;
using System.Windows.Forms;
using Microsoft.Win32;
namespace DeepSteamInstaller {
 internal static class InstallerPresentationTests {
  static int checks;
  static void Check(bool ok,string message) { checks++; if(!ok) throw new Exception(message); }
  static void Own(UninstallContext context,string name,string value) {
   string file=Path.Combine(context.Root,name); File.WriteAllText(file,value);
   context.Files.Add(new UninstallFile{Path=name,Bytes=new FileInfo(file).Length,Hash=UninstallRegistration.Sha(file)});
  }
  [STAThread] static int Main(string[] args) {
   try {
    AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
    AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
    string root=Path.GetFullPath(args[0]); Directory.CreateDirectory(root);
    Check(SetupTheme.Paper.ToArgb()==ColorTranslator.FromHtml("#1c1814").ToArgb(),"Background must match app dark palette");
    Check(SetupTheme.Accent.ToArgb()==ColorTranslator.FromHtml("#d97a48").ToArgb(),"Accent must match app dark palette");
    string reason="The installation directory does not match the Windows registration. No files were deleted.";
    string text=Uninstaller.FailureMessage(reason);
    Check(text.Contains("登记不一致") && text.Contains("没有删除任何文件"),"Localized explanation lost");
    foreach(float scale in new[]{1F,1.5F,2F}) {
     using(var dialog=new SetupDialog(text,"DeepSteam 卸载尚未完成",false)) {
      dialog.Scale(new SizeF(scale,scale)); dialog.PerformLayout();
      foreach(Control control in dialog.Controls) control.PerformLayout();
      dialog.BodyViewport.PerformLayout();
      Check(!dialog.Visible,"Tests must never show a native window");
      Check(dialog.Body.Width<=dialog.BodyViewport.ClientSize.Width,"Message exceeds available width at "+scale);
      Check(dialog.Body.Height<=dialog.BodyViewport.ClientSize.Height,"Short error clipped at "+scale);
      Check(dialog.Heading.MaximumSize.Width>0,"Heading must wrap");
      Check(dialog.MaximizeBox,"Long diagnostics must allow maximize");
     }
    }
    string journalFixture=Path.Combine(root,"journal-size-fixture.json");
    byte[] snapshot=new byte[]{1,2,3}; string snapshotName=UninstallRegistration.ManifestName;
    string savedName=UninstallUpgrade.WriteJournalSnapshot(journalFixture,snapshotName,snapshot);
    string snapshotFile=Path.Combine(journalFixture+".snapshots",snapshotName);
    var snapshotRow=new Dictionary<string,object>{{"path",snapshotName},{"before_file",savedName},{"before_sha",UninstallRegistration.Sha(snapshotFile)}};
    Check(Convert.ToBase64String(UninstallUpgrade.ReadJournalSnapshot(journalFixture,snapshotRow))=="AQID","External snapshot roundtrip failed");
    bool snapshotRejected=false;
    try { UninstallUpgrade.WriteJournalSnapshot(journalFixture,"../outside",snapshot); } catch(IOException) { snapshotRejected=true; }
    Check(snapshotRejected,"Snapshot escaped its transaction directory");
    File.WriteAllBytes(snapshotFile,new byte[]{4,5,6}); snapshotRejected=false;
    try { UninstallUpgrade.ReadJournalSnapshot(journalFixture,snapshotRow); } catch(IOException) { snapshotRejected=true; }
    Check(snapshotRejected,"Tampered rollback bytes were accepted");
    snapshotRow.Remove("before_file"); snapshotRow["before"]="AQID";
    Check(Convert.ToBase64String(UninstallUpgrade.ReadJournalSnapshot(journalFixture,snapshotRow))=="AQID","Legacy ownership journal cannot be recovered");
    string phase; int percent;
    Check(InstallProgress.TryParse("Integrity: 50/200",out phase,out percent)&&percent==25&&phase=="正在校验文件","Measured verification progress");
    Check(InstallProgress.TryParse("Runtime: 6/12",out phase,out percent)&&percent==50,"Measured runtime progress");
    foreach(string invalid in new[]{"Integrity: 0/0","Runtime: 13/12","Runtime: -1/12","arbitrary 3/10"})
     Check(!InstallProgress.TryParse(invalid,out phase,out percent),"Invalid progress accepted");
    byte[] payload=new byte[3500000]; for(int i=0;i<payload.Length;i++) payload[i]=(byte)(i%251);
    var observed=new List<int>(); byte[] expected;
    using(var sha=SHA256.Create()) expected=sha.ComputeHash(payload);
    using(var input=new MemoryStream(payload)) {
     byte[] actual=Package.HashWithProgress(input,delegate(int p){observed.Add(p);});
     Check(Convert.ToBase64String(actual)==Convert.ToBase64String(expected),"Progress must preserve payload SHA256");
    }
    Check(observed.Count>1 && observed[observed.Count-1]==100,"Hashing must report real completion");
    for(int i=1;i<observed.Count;i++) Check(observed[i]>=observed[i-1],"Hash progress moved backwards");
    string exe=Path.Combine(root,"Uninstall-DeepSteam.exe");
    Check(Uninstaller.ResolveRoot(new string[0],exe)==root,"Installed entry resolves incorrectly");
    Check(Uninstaller.ResolveRoot(new[]{"--uninstall-from-desktop",root},exe)==root,"Desktop entry root lost");
    Check(Uninstaller.ResolveRoot(new[]{"--uninstall-worker",root,"fixture-id"},Path.Combine(root,"temp","Uninstall-DeepSteam.exe"))==root,"Worker forgot original root");
    bool rejected=false;
    try { Uninstaller.ResolveRoot(new[]{"--uninstall-from-desktop",Path.Combine(root,"wrong")},exe); } catch(IOException) { rejected=true; }
    Check(rejected,"Wrong desktop root must never be authorized");
    var context=new UninstallContext{Root=root,Id=Guid.NewGuid().ToString("N"),Version="fixture",Manifest=Path.Combine(root,UninstallRegistration.ManifestName)};
    context.DataRoots.Add(root);
    try {
     Own(context,Program.InstalledMarker,"DeepSteam fixture\r\nfixture timestamp");
     Own(context,"Uninstall-DeepSteam.exe","fixture file");
     UninstallRegistration.Write(context);
     Check(UninstallRegistration.Verify(root).Id==context.Id,"Correctly registered desktop root rejected");
     using(var key=Registry.CurrentUser.OpenSubKey(UninstallRegistration.RegistryName(context.Id),true)) key.SetValue("InstallLocation",Path.Combine(root,"wrong"));
     rejected=false;
     try { UninstallRegistration.Verify(root); } catch(IOException e) { rejected=e.Message==reason; }
     Check(rejected,"Moved/unregistered root must still block removal");
     Check(File.Exists(exe)&&File.Exists(context.Manifest),"Read-only failure deleted files");
    } finally { Registry.CurrentUser.DeleteSubKeyTree(UninstallRegistration.RegistryName(context.Id),false); }
    Console.WriteLine("PASS "+checks+" assertions; hidden layout at 100/150/200 percent; actual registry fixtures; no native interaction or production removal");
    return 0;
   } catch(Exception error) { Console.Error.WriteLine(error); return 1; }
  }
 }
}
