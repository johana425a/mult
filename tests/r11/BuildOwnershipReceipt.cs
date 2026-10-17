using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
namespace DeepSteamInstaller {
    internal static class BuildOwnershipReceipt {
        static int Main(string[] args) {
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
            try {
                var context=UninstallRegistration.Verify(args[0]);
                var additions=new Dictionary<string,object>(StringComparer.OrdinalIgnoreCase);
                int checkedFiles=0,changedOwned=0,skippedLinks=0;
                foreach(var item in context.Files) {
                    if(!UninstallUpgrade.PublicProgramPath(item.Path))continue;
                    string path=UninstallRegistration.Child(context.Root,item.Path);
                    if(!File.Exists(Package.Extended(path)))continue;
                    try{UninstallRegistration.PlainPath(path);}catch(IOException){skippedLinks++;continue;}
                    string hash=UninstallRegistration.Sha(path);long size=new FileInfo(Package.Extended(path)).Length;checkedFiles++;
                    if(hash!=item.Hash||size!=item.Bytes){additions[item.Path]=new {path=item.Path,sha256=hash,bytes=size};changedOwned++;}
                }
                foreach(object value in (object[])UninstallRegistration.Json(args[2])) {
                    string name=(string)value;
                    if(!UninstallUpgrade.PublicProgramPath(name))throw new IOException("Non-program extra entry: "+name);
                    string path=UninstallRegistration.Child(context.Root,name);UninstallRegistration.PlainPath(path);
                    additions[name]=new {path=name,sha256=UninstallRegistration.Sha(path),bytes=new FileInfo(Package.Extended(path)).Length};
                }
                var receipt=new {kind="deepsteam-uninstall-update-v1",root=context.Root,installation_id=context.Id,
                    previous_manifest_sha256=UninstallRegistration.Sha(context.Manifest),target_version=Program.Version,
                    updater_sha256=UninstallRegistration.Sha(args[1]),files=new List<object>(additions.Values).ToArray()};
                UninstallRegistration.AtomicBytes(args[3],new UTF8Encoding(false).GetBytes(UninstallUpgrade.Serialize(receipt)));
                Console.WriteLine("{\"checked_existing_program_files\":"+checkedFiles+",\"changed_owned_files\":"+changedOwned+",\"receipt_files\":"+additions.Count+",\"skipped_link_paths\":"+skippedLinks+"}");
                return 0;
            }catch(Exception error){Console.WriteLine(error.GetType().Name+": "+error.Message);return 1;}
        }
    }
}
