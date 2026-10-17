// DeepSteam Windows installer and launcher. Modified integration code, 2026-10-10.
// Build a small PE with .NET Framework 4.x csc; append the reviewed Zip64 payload.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32.SafeHandles;
using Microsoft.Win32;

namespace DeepSteamInstaller
{
    internal static class Program
    {
        internal const string Version = "2026.10.17-r11.3-review-local";
        internal const string InstallingMarker = ".deepsteam-installing";
        internal const string InstalledMarker = ".deepsteam-installed";

        // The installed runtime can be updated independently of this launcher.
        // This is display-only; installer/uninstaller ownership stays pinned.
        internal static string DisplayVersion(string root)
        {
            try
            {
                if (!File.Exists(Path.Combine(root, InstalledMarker))) return Version;
                using (FileStream file = File.OpenRead(Path.Combine(root, "RELEASE-IDENTITY.json")))
                {
                    ReleaseDisplay identity = new DataContractJsonSerializer(typeof(ReleaseDisplay)).ReadObject(file) as ReleaseDisplay;
                    if (identity != null && identity.Product == "DeepSteam" && identity.Version != null &&
                        Regex.IsMatch(identity.Version, @"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"))
                        return identity.Version;
                }
            }
            catch { }
            return Version;
        }

        [DataContract]
        private sealed class ReleaseDisplay
        {
            [DataMember(Name = "product")] public string Product { get; set; }
            [DataMember(Name = "version")] public string Version { get; set; }
        }

        [STAThread]
        private static int Main(string[] args)
        {
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
            if (args.Length == 5 && (args[0] == "--refresh-uninstall" || args[0] == "--check-uninstall-update"))
            {
                try
                {
                    UninstallUpgrade.Refresh(args[1], args[2], args[3], args[4], args[0] == "--check-uninstall-update");
                    return 0;
                }
                catch (Exception error) { Console.Error.WriteLine("FAIL " + error.Message); return 1; }
            }
            if (args.Length == 3 && args[0] == "--check-uninstall")
            {
                try { UninstallUpgrade.Check(args[1], args[2]); return 0; }
                catch (Exception error) { Console.Error.WriteLine("FAIL " + error.Message); return 1; }
            }
            if (args.Length == 3 && args[0] == "--bind-uninstall-data")
            {
                try { UninstallRegistration.BindData(args[1], args[2]); Console.WriteLine("PASS bound dedicated DeepSteam data for optional uninstall cleanup"); return 0; }
                catch { Console.Error.WriteLine("FAIL data ownership could not be verified; existing files were retained"); return 1; }
            }
            if (args.Length == 2 && args[0] == "--register-uninstall")
            {
                try
                {
                    string root = UninstallRegistration.Root(args[1]);
                    Package.ValidateInstalledManifest(root);
                    UninstallRegistration.Register(root);
                    Console.WriteLine("PASS registered per-user DeepSteam uninstaller"); return 0;
                }
                catch { Console.Error.WriteLine("FAIL installation inventory could not be verified; no uninstall permission was granted"); return 1; }
            }
            if (Uninstaller.IsUninstaller(Application.ExecutablePath) ||
                (args.Length > 0 && args[0] == "--uninstall"))
                return Uninstaller.Open(args);
            if (args.Length > 0 && (args[0] == "--install-to" || args[0] == "--resume-install-to"))
            {
                try
                {
                    if (args.Length < 2) throw new ArgumentException("缺少安装位置。");
                    string root = Path.GetFullPath(args[1]).TrimEnd('\\');
                    if (!Path.IsPathRooted(args[1]) || root.StartsWith("\\\\") || root.Length <= 3)
                        throw new IOException("必须指定本机磁盘中的专用绝对路径。");
                    if (root.Length > 100) throw new IOException("安装位置过长，请选择较短路径，例如 D:\\DeepSteam。");
                    Package.EnsureNoReparsePoint(root);
                    bool resume = args[0] == "--resume-install-to";
                    if (resume)
                    {
                        string marker = Path.Combine(root, InstallingMarker);
                        if (!Directory.Exists(root) || !File.Exists(marker) ||
                            File.Exists(Path.Combine(root, InstalledMarker)) ||
                            File.ReadAllText(marker, Encoding.UTF8).Trim() != "DeepSteam " + Version)
                            throw new IOException("续装只接受本版本未完成安装的专用目录，不能覆盖其他目录。");
                    }
                    else if (Directory.Exists(root) && Directory.GetFileSystemEntries(root).Length > 0)
                        throw new IOException("自动安装只接受空目录，不会覆盖已有内容。");
                    PayloadSummary summary = Package.Validate();
                    Package.EnsureDiskSpace(root, summary.Bytes);
                    Directory.CreateDirectory(root);
                    File.WriteAllText(Path.Combine(root, InstallingMarker), "DeepSteam " + Version, new UTF8Encoding(false));
                    Package.Extract(root, Console.WriteLine, delegate(int value) { }, delegate { return false; });
                    string installedExe = Path.Combine(root, "DeepSteam.exe");
                    if (!File.Exists(installedExe) && !String.Equals(installedExe, Application.ExecutablePath, StringComparison.OrdinalIgnoreCase))
                        File.Copy(Application.ExecutablePath, installedExe, false);
                    RunHeadlessScript(root, "Install-DeepSteam.ps1", true);
                    File.WriteAllText(Path.Combine(root, InstalledMarker), "DeepSteam " + Version + "\r\n" + DateTime.UtcNow.ToString("o"), new UTF8Encoding(false));
                    File.Delete(Path.Combine(root, InstallingMarker));
                    UninstallRegistration.Register(root);
                    if (Array.IndexOf(args, "--shortcuts") >= 0) InstallerForm.CreateShortcuts(root);
                    Console.WriteLine("PASS DeepSteam installation: " + root);
                    bool noLaunch = Array.IndexOf(args, "--no-launch") >= 0;
                    if (!noLaunch) RunHeadlessScript(root, "Start-DeepSteam.ps1", false);
                    return 0;
                }
                catch (Exception ex) { Console.Error.WriteLine("FAIL " + ex.Message); return 1; }
            }
            if (args.Length > 0 && args[0] == "--self-test")
            {
                try
                {
                    PayloadSummary result = Package.Validate();
                    string report = "PASS DeepSteam " + Version + "; files=" + result.Files +
                        "; uncompressedBytes=" + result.Bytes + "; install/start/stop scripts present; safe paths verified.";
                    Console.WriteLine(report);
                    if (args.Length > 1) File.WriteAllText(args[1], report + Environment.NewLine, new UTF8Encoding(false));
                    return 0;
                }
                catch (Exception ex)
                {
                    string report = "FAIL " + ex.Message;
                    Console.Error.WriteLine(report);
                    if (args.Length > 1) File.WriteAllText(args[1], report + Environment.NewLine, new UTF8Encoding(false));
                    return 1;
                }
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string action = InstallLocation.InitialAction(Application.ExecutablePath,
                args.Length > 0 ? args[0] : "", args.Length == 0,
                File.Exists(Path.Combine(Path.GetDirectoryName(Application.ExecutablePath), InstalledMarker)));
            Application.Run(new InstallerForm(action));
            return 0;
        }

        private static void RunHeadlessScript(string root, string name, bool containChildren)
        {
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
            info.Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + InstallerForm.Quote(Path.Combine(root, "installer", name)) + " -InstallRoot " + InstallerForm.Quote(root);
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = info.RedirectStandardError = true;
            info.StandardOutputEncoding = info.StandardErrorEncoding = Encoding.UTF8;
            using (Process process = new Process())
            using (KillJob job = containChildren ? new KillJob() : null)
            {
                process.StartInfo = info;
                process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Console.WriteLine(e.Data); };
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Console.Error.WriteLine(e.Data); };
                process.Start();
                try { if (job != null) job.Add(process); }
                catch { try { process.Kill(); } catch { } throw; }
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                process.WaitForExit();
                if (process.ExitCode != 0) throw new IOException(name + " 退出码 " + process.ExitCode);
            }
        }
    }

    internal sealed class PayloadSummary
    {
        internal int Files;
        internal long Bytes;
    }

    internal static class Package
    {
        // Exactly 64 bytes: magic[16], offset[8], length[8], SHA256[32].
        // Zip offsets are relative to the payload segment, never to the PE file.
        private static readonly byte[] TrailerMagic = Encoding.ASCII.GetBytes("DeepSteamZip64v1");
        private static bool payloadHashVerified;
        private static readonly string[] Required = {
            "installer/Install-DeepSteam.ps1", "installer/Start-DeepSteam.ps1", "installer/Stop-DeepSteam.ps1"
        };

        internal static Stream Open()
        {
            FileStream file = new FileStream(Application.ExecutablePath, FileMode.Open, FileAccess.Read,
                FileShare.Read, 128 * 1024, FileOptions.SequentialScan);
            try
            {
                if (file.Length < 64) throw new InvalidDataException("安装包不完整，请重新获取完整安装文件。");
                file.Seek(-64, SeekOrigin.End);
                byte[] trailer = new byte[64];
                ReadExactly(file, trailer, 0, trailer.Length);
                bool embedded = HasTrailerMagic(trailer);
                if (!embedded)
                {
                    // Windows refuses PE files larger than 4 GiB. Such releases
                    // keep the exact same verified payload next to a small EXE.
                    string companion = Path.ChangeExtension(Application.ExecutablePath, ".payload.dat");
                    if (!File.Exists(companion)) throw new InvalidDataException("安装包缺少内置资料，请将 EXE 与配套 payload.dat 放在同一文件夹。");
                    file.Dispose();
                    file = new FileStream(companion, FileMode.Open, FileAccess.Read,
                        FileShare.Read, 128 * 1024, FileOptions.SequentialScan);
                    if (file.Length < 64) throw new InvalidDataException("配套载荷文件不完整。");
                    file.Seek(-64, SeekOrigin.End);
                    ReadExactly(file, trailer, 0, trailer.Length);
                }
                for (int i = 0; i < TrailerMagic.Length; i++)
                    if (trailer[i] != TrailerMagic[i]) throw new InvalidDataException("安装包缺少内置资料，请重新获取完整安装文件。");
                long offset = BitConverter.ToInt64(trailer, 16);
                long length = BitConverter.ToInt64(trailer, 24);
                if (offset < (embedded ? 1 : 0) || length < 22 || offset > file.Length - 64 || length != file.Length - 64 - offset)
                    throw new InvalidDataException("安装包载荷位置或长度不正确，请重新获取完整安装文件。");
                PayloadSegmentStream stream = new PayloadSegmentStream(file, offset, length);
                if (!payloadHashVerified)
                {
                    byte[] actual;
                    using (SHA256 sha = SHA256.Create()) actual = sha.ComputeHash(stream);
                    int difference = 0;
                    for (int i = 0; i < actual.Length; i++) difference |= actual[i] ^ trailer[32 + i];
                    if (difference != 0) throw new InvalidDataException("安装包完整性校验失败，请重新获取完整安装文件。");
                    payloadHashVerified = true;
                }
                stream.Position = 0;
                return stream;
            }
            catch { file.Dispose(); throw; }
        }

        internal static void WriteBootstrap(string source, string destination)
        {
            // The uninstaller needs only the small PE prefix. Copying an entire
            // appended distribution makes the installed entry fail its size gate.
            using (FileStream file = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                long length = file.Length;
                if (length > 4 * 1024 * 1024)
                {
                    file.Seek(-64, SeekOrigin.End);
                    byte[] trailer = new byte[64]; ReadExactly(file, trailer, 0, 64);
                    long offset = BitConverter.ToInt64(trailer, 16), payloadLength = BitConverter.ToInt64(trailer, 24);
                    if (!HasTrailerMagic(trailer) || offset < 64 || offset > 4 * 1024 * 1024 ||
                        payloadLength < 22 || payloadLength != file.Length - offset - 64)
                        throw new InvalidDataException("无法确定卸载组件的有效程序边界。");
                    length = offset;
                }
                if (length < 64) throw new InvalidDataException("卸载组件不完整。");
                file.Position = 0;
                byte[] bootstrap = new byte[(int)length]; ReadExactly(file, bootstrap, 0, bootstrap.Length);
                if (bootstrap[0] != 'M' || bootstrap[1] != 'Z') throw new InvalidDataException("卸载组件不是有效程序。");
                File.WriteAllBytes(destination, bootstrap);
            }
        }

        private static bool HasTrailerMagic(byte[] trailer)
        {
            for (int i = 0; i < TrailerMagic.Length; i++) if (trailer[i] != TrailerMagic[i]) return false;
            return true;
        }

        private static void ReadExactly(Stream stream, byte[] buffer, int offset, int count)
        {
            while (count > 0)
            {
                int read = stream.Read(buffer, offset, count);
                if (read == 0) throw new EndOfStreamException("安装包被截断。");
                offset += read; count -= read;
            }
        }

        internal static string EntryPath(string name)
        {
            string normalized = name.Replace('\\', '/');
            if (String.IsNullOrEmpty(normalized) || normalized.StartsWith("/") || normalized.IndexOf(':') >= 0 || normalized.IndexOf('\0') >= 0)
                throw new InvalidDataException("安装包含有不安全的文件路径。");
            string[] parts = normalized.Split('/');
            for (int i = 0; i < parts.Length; i++)
            {
                string part = parts[i];
                if (part == ".." || part == "." || (part.Length == 0 && i != parts.Length - 1) ||
                    part.EndsWith(".") || part.EndsWith(" ") || part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                    throw new InvalidDataException("安装包含有不安全的文件路径。");
                string stem = part.Split('.')[0].ToUpperInvariant();
                if (Regex.IsMatch(stem, "^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$"))
                    throw new InvalidDataException("安装包含有 Windows 保留文件名。");
            }
            return normalized;
        }

        internal static PayloadSummary Validate()
        {
            PayloadSummary summary = new PayloadSummary();
            HashSet<string> names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            using (Stream stream = Open())
            using (ZipArchive zip = new ZipArchive(stream, ZipArchiveMode.Read, false))
            {
                foreach (ZipArchiveEntry entry in zip.Entries)
                {
                    string normalized = EntryPath(entry.FullName);
                    if (!names.Add(normalized.TrimEnd('/'))) throw new InvalidDataException("安装包中有重复的文件路径。");
                    if ((entry.ExternalAttributes >> 16 & 0xF000) == 0xA000)
                        throw new InvalidDataException("安装包不可包含符号链接。");
                    if (!normalized.EndsWith("/")) { summary.Files++; checked { summary.Bytes += entry.Length; } }
                }
            }
            foreach (string required in Required)
                if (!names.Contains(required)) throw new InvalidDataException("安装包缺少 " + required);
            if (summary.Files == 0) throw new InvalidDataException("安装包为空。");
            return summary;
        }
        internal static void ValidateInstalledManifest(string root)
        {
            // Overlay registration must be invoked from the reviewed installer
            // EXE + payload pair. A local marker alone is never sufficient.
            Validate();
            using (Stream stream = Open())
            using (ZipArchive zip = new ZipArchive(stream, ZipArchiveMode.Read, false))
            {
                ZipArchiveEntry manifest = zip.GetEntry("installer/payload-manifest.json");
                if (manifest == null || manifest.Length > 64 * 1024 * 1024) throw new IOException("安装包缺少公开文件清单。");
                string expected;
                using (Stream input = manifest.Open())
                using (SHA256 sha = SHA256.Create()) expected = BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
                if (UninstallRegistration.Sha(Path.Combine(root, "installer", "payload-manifest.json")) != expected)
                    throw new IOException("安装目录清单与当前安装包不一致。");
            }
        }

        internal static void EnsureNoReparsePoint(string path)
        {
            DirectoryInfo current = new DirectoryInfo(Extended(path));
            while (current != null)
            {
                if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("安装目录不可经过符号链接或目录联接，请选择普通文件夹。");
                current = current.Parent;
            }
        }

        internal static void EnsureDiskSpace(string root, long bytes)
        {
            DriveInfo drive = new DriveInfo(Path.GetPathRoot(root));
            if (!drive.IsReady) throw new IOException("安装磁盘尚未就绪。");
            if (!String.Equals(drive.DriveFormat, "NTFS", StringComparison.OrdinalIgnoreCase))
                throw new IOException("请选择 NTFS 格式磁盘；应用依赖使用目录联接，模型安装包也可能超过 4 GB。");
            long required = checked(bytes + 512L * 1024L * 1024L);
            if (drive.AvailableFreeSpace < required)
                throw new IOException("安装磁盘空间不足，至少需要 " + ((required + 1073741823L) / 1073741824L) + " GB 可用空间。");
        }

        internal static string Extended(string path)
        {
            if (path.StartsWith(@"\\?\", StringComparison.Ordinal)) return path;
            string absolute = Path.GetFullPath(path);
            if (absolute.StartsWith(@"\\", StringComparison.Ordinal)) return @"\\?\UNC\" + absolute.Substring(2);
            return @"\\?\" + absolute;
        }

        internal static void Extract(string root, Action<string> log, Action<int> progress, Func<bool> cancelled)
        {
            PayloadSummary summary = Validate();
            EnsureNoReparsePoint(root);
            string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            int completed = 0;
            int skipped = 0;
            byte[] buffer = new byte[128 * 1024];
            using (Stream stream = Open())
            using (ZipArchive zip = new ZipArchive(stream, ZipArchiveMode.Read, false))
            {
                foreach (ZipArchiveEntry entry in zip.Entries)
                {
                    if (cancelled()) throw new OperationCanceledException();
                    string relative = EntryPath(entry.FullName).Replace('/', Path.DirectorySeparatorChar);
                    string target = Path.GetFullPath(Path.Combine(root, relative));
                    if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("安装文件路径超出了所选文件夹。");
                    string folder = relative.EndsWith(Path.DirectorySeparatorChar.ToString()) ? target : Path.GetDirectoryName(target);
                    EnsureNoReparsePoint(folder);
                    Directory.CreateDirectory(Extended(folder));
                    if (relative.EndsWith(Path.DirectorySeparatorChar.ToString())) continue;
                    string extendedTarget = Extended(target);
                    if (File.Exists(extendedTarget))
                    {
                        if ((File.GetAttributes(extendedTarget) & FileAttributes.ReparsePoint) != 0)
                            throw new IOException("安装位置含文件链接，请选择新的普通文件夹。");
                        // Never overwrite a prior installation's local edits or user data.
                        skipped++;
                    }
                    else
                    {
                        string temporary = Extended(target + ".deepsteam-" + Guid.NewGuid().ToString("N") + ".tmp");
                        try
                        {
                            using (Stream input = entry.Open())
                            using (FileStream output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                            {
                                int read;
                                while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
                                {
                                    if (cancelled()) throw new OperationCanceledException();
                                    output.Write(buffer, 0, read);
                                }
                                if (output.Length != entry.Length) throw new InvalidDataException("解压文件长度与清单不一致，请重新获取安装包。");
                            }
                            File.Move(temporary, extendedTarget);
                        }
                        finally { if (File.Exists(temporary)) File.Delete(temporary); }
                    }
                    completed++;
                    if (completed % 50 == 0 || completed == summary.Files) progress(completed * 35 / summary.Files);
                }
            }
            log("Application files are ready: " + completed + " files" + (skipped > 0 ? "; existing files preserved: " + skipped + "." : "."));
        }
    }

    // A seekable 64-bit window into the appended archive. Disposing it closes the
    // file; neither the executable prefix nor the trailer is exposed to ZipArchive.
    internal sealed class PayloadSegmentStream : Stream
    {
        private readonly FileStream file;
        private readonly long start;
        private readonly long length;
        private long position;

        internal PayloadSegmentStream(FileStream source, long offset, long count)
        {
            file = source; start = offset; length = count;
            file.Position = start;
        }

        public override bool CanRead { get { return true; } }
        public override bool CanSeek { get { return true; } }
        public override bool CanWrite { get { return false; } }
        public override long Length { get { return length; } }
        public override long Position
        {
            get { return position; }
            set { Seek(value, SeekOrigin.Begin); }
        }

        public override int Read(byte[] buffer, int offset, int count)
        {
            if (buffer == null) throw new ArgumentNullException("buffer");
            if (offset < 0 || count < 0 || offset > buffer.Length - count) throw new ArgumentOutOfRangeException();
            int bounded = (int)Math.Min((long)count, length - position);
            if (bounded == 0) return 0;
            long absolute = checked(start + position);
            // Assigning FileStream.Position even to its current position drops
            // its read buffer. Keep sequential checksum/Deflate reads buffered.
            if (file.Position != absolute) file.Position = absolute;
            int read = file.Read(buffer, offset, bounded);
            position += read;
            return read;
        }

        public override long Seek(long offset, SeekOrigin origin)
        {
            long target;
            if (origin == SeekOrigin.Begin) target = offset;
            else if (origin == SeekOrigin.Current) target = checked(position + offset);
            else if (origin == SeekOrigin.End) target = checked(length + offset);
            else throw new ArgumentException("Unknown seek origin.");
            if (target < 0 || target > length) throw new IOException("Read exceeds the installer payload boundary.");
            long absolute = checked(start + target);
            if (file.Position != absolute) file.Position = absolute;
            position = target;
            return position;
        }

        public override void Flush() { }
        public override void SetLength(long value) { throw new NotSupportedException(); }
        public override void Write(byte[] buffer, int offset, int count) { throw new NotSupportedException(); }
        protected override void Dispose(bool disposing)
        {
            if (disposing) file.Dispose();
            base.Dispose(disposing);
        }
    }

    internal static class InstallLocation
    {
        // Never choose a USB/removable destination just because its drive letter
        // exists. A caller's existing explicit installation remains unchanged.
        internal static string SelectDefault(string ownDirectory, bool ownSelectedExplicitly,
            string localApplicationData, bool preferredDUsable)
        {
            if (ownSelectedExplicitly) return ownDirectory;
            if (preferredDUsable) return @"D:\DeepSteam";
            return Path.Combine(localApplicationData, "Programs", "DeepSteam");
        }

        internal static bool IsInstalledLauncher(string executablePath)
        {
            return String.Equals(Path.GetFileName(executablePath), "DeepSteam.exe", StringComparison.OrdinalIgnoreCase);
        }

        internal static string InitialAction(string executablePath, string requestedAction,
            bool noArguments, bool completedMarker)
        {
            return noArguments && completedMarker && IsInstalledLauncher(executablePath)
                ? "--launch" : requestedAction;
        }

        internal static bool UseOwnSelection(string action, bool ownHasMarker)
        {
            return ownHasMarker && (action == "--launch" || action == "--stop");
        }

        internal static bool IsLocalFixedStorage(DriveType type, bool ready, string format, bool removableMedia, int busType)
        {
            if (type != DriveType.Fixed || !ready || removableMedia ||
                !String.Equals(format, "NTFS", StringComparison.OrdinalIgnoreCase)) return false;
            // STORAGE_BUS_TYPE: local disk, virtual machine and Storage Spaces.
            // Unknown, USB, FireWire, SD/MMC and iSCSI are not default targets.
            return busType == 1 || busType == 2 || busType == 3 || busType == 8 ||
                busType == 10 || busType == 11 || busType == 14 || busType == 15 ||
                busType == 16 || busType == 17 || busType == 19;
        }

        internal static bool PreferredDUsable()
        {
            try
            {
                DriveInfo drive = new DriveInfo(@"D:\");
                if (drive.DriveType != DriveType.Fixed || !drive.IsReady ||
                    !String.Equals(drive.DriveFormat, "NTFS", StringComparison.OrdinalIgnoreCase)) return false;
                using (SafeFileHandle handle = OpenDevice(@"\\.\D:", 0, 3, IntPtr.Zero, 3, 0, IntPtr.Zero))
                {
                    if (handle.IsInvalid) return false;
                    // StorageDeviceProperty / PropertyStandardQuery. Only the
                    // media flag and bus type are inspected; no disk ID logged.
                    byte[] query = new byte[12];
                    byte[] descriptor = new byte[4096];
                    uint returned;
                    if (!QueryDevice(handle, 0x002D1400, query, (uint)query.Length,
                        descriptor, (uint)descriptor.Length, out returned, IntPtr.Zero) || returned < 36)
                        return false;
                    return IsLocalFixedStorage(drive.DriveType, drive.IsReady, drive.DriveFormat,
                        descriptor[10] != 0, BitConverter.ToInt32(descriptor, 28));
                }
            }
            catch (IOException) { return false; }
            catch (UnauthorizedAccessException) { return false; }
            catch (ArgumentException) { return false; }
            catch (NotSupportedException) { return false; }
            catch (System.Security.SecurityException) { return false; }
        }

        [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle OpenDevice(string name, uint access, uint share,
            IntPtr attributes, uint disposition, uint flags, IntPtr template);
        [DllImport("kernel32.dll", EntryPoint = "DeviceIoControl", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool QueryDevice(SafeFileHandle device, uint code, byte[] input,
            uint inputSize, [Out] byte[] output, uint outputSize, out uint returned, IntPtr overlapped);
    }

    // Presentation only. Installation, process ownership and data-preserving
    // uninstall paths remain independent of these lightweight native controls.
    internal static class SetupTheme
    {
        // Same dark tokens as upstream/DeepTutor/web/app/globals.css.
        // Brand artwork retains its gold/terracotta gradient independently.
        internal static readonly Color Paper = Color.FromArgb(26, 25, 24);
        internal static readonly Color Panel = Color.FromArgb(36, 34, 32);
        internal static readonly Color Ink = Color.FromArgb(232, 228, 222);
        internal static readonly Color Muted = Color.FromArgb(155, 149, 144);
        internal static readonly Color Accent = Color.FromArgb(212, 115, 75);
        internal static readonly Color AccentInk = Paper;
        internal static readonly Color Secondary = Color.FromArgb(42, 39, 37);
        internal static readonly Color Active = Color.FromArgb(48, 45, 42);
        internal static readonly Color Destructive = Color.FromArgb(212, 74, 60);
        internal static readonly Color DestructiveInk = Color.White;
        internal static readonly Color Line = Color.FromArgb(58, 54, 52);
        private static readonly bool motionEnabled = ReadMotion();
        internal static bool Motion { get { return motionEnabled && !SystemInformation.HighContrast; } }
        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SystemParametersInfo(uint action, uint parameter, out int value, uint flags);
        private static bool ReadMotion()
        {
            int enabled;
            return SystemParametersInfo(0x1042, 0, out enabled, 0) && enabled != 0;
        }

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);
        internal static void ApplyTitleBar(Form form)
        {
            try
            {
                int enabled = 1;
                if (DwmSetWindowAttribute(form.Handle, 20, ref enabled, sizeof(int)) != 0)
                    DwmSetWindowAttribute(form.Handle, 19, ref enabled, sizeof(int));
                int caption = ColorTranslator.ToWin32(Paper), ink = ColorTranslator.ToWin32(Ink);
                DwmSetWindowAttribute(form.Handle, 35, ref caption, sizeof(int));
                DwmSetWindowAttribute(form.Handle, 36, ref ink, sizeof(int));
            }
            catch (DllNotFoundException) { }
            catch (EntryPointNotFoundException) { }
        }

        // iOS-style motion helpers. Colour/position values approach their
        // target exponentially; scale uses a damped spring with a slight
        // overshoot on release. All motion is skipped when Windows animation
        // effects are off (SetupTheme.Motion).
        internal static Color Mix(Color from, Color to, double amount)
        {
            double t = Math.Max(0, Math.Min(1, amount));
            return Color.FromArgb((int)Math.Round(from.A + (to.A - from.A) * t), (int)Math.Round(from.R + (to.R - from.R) * t),
                (int)Math.Round(from.G + (to.G - from.G) * t), (int)Math.Round(from.B + (to.B - from.B) * t));
        }
        internal static double Approach(double current, double target, double rate)
        {
            double next = current + (target - current) * rate;
            return Math.Abs(target - next) < 0.003 ? target : next;
        }
        internal static double EaseOutCubic(double t) { t = Math.Max(0, Math.Min(1, t)); return 1 - Math.Pow(1 - t, 3); }

        internal static GraphicsPath Round(RectangleF bounds, float radius)
        {
            GraphicsPath path = new GraphicsPath();
            float d = Math.Min(radius * 2, Math.Min(bounds.Width, bounds.Height));
            path.AddArc(bounds.X, bounds.Y, d, d, 180, 90);
            path.AddArc(bounds.Right - d, bounds.Y, d, d, 270, 90);
            path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
            path.AddArc(bounds.X, bounds.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    // App-owned prompts share the same palette. No system-wide theme changes.
    internal sealed class SetupDialog : Form
    {
        internal SetupDialog(string message, string title, bool question)
        {
            Text = title; BackColor = SetupTheme.Paper; ForeColor = SetupTheme.Ink;
            Font = new Font("Microsoft YaHei UI", 10);
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            AutoScaleDimensions = new SizeF(96F, 96F); AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(560, 280); MinimumSize = new Size(440, 240);
            StartPosition = FormStartPosition.CenterParent; ShowInTaskbar = false;
            MinimizeBox = false; MaximizeBox = false;
            TableLayoutPanel layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), ColumnCount = 1, RowCount = 3 };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            Label heading = new Label { Text = title, AutoSize = true, Dock = DockStyle.Top,
                Font = new Font(Font.FontFamily, 15, FontStyle.Bold), Margin = new Padding(0, 0, 0, 14), UseMnemonic = false };
            Panel viewport = new Panel { Dock = DockStyle.Fill, AutoScroll = true, Margin = new Padding(0, 0, 0, 18) };
            Label body = new Label { Text = message, AutoSize = true, Dock = DockStyle.Top, UseMnemonic = false };
            viewport.Controls.Add(body);
            viewport.SizeChanged += delegate { body.MaximumSize = new Size(Math.Max(160, viewport.ClientSize.Width - SystemInformation.VerticalScrollBarWidth - 2), 0); };
            FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, FlowDirection = FlowDirection.RightToLeft, WrapContents = true, Margin = Padding.Empty };
            SetupButton accept = new SetupButton { Text = question ? "取消并关闭" : "确定", Primary = true, Danger = question,
                DialogResult = question ? DialogResult.Yes : DialogResult.OK, MinimumSize = new Size(question ? 128 : 100, 42), Margin = Padding.Empty };
            actions.Controls.Add(accept);
            if (question)
            {
                SetupButton keep = new SetupButton { Text = "继续安装", DialogResult = DialogResult.No, MinimumSize = new Size(128, 42), Margin = new Padding(0, 0, 12, 0) };
                actions.Controls.Add(keep); AcceptButton = keep; CancelButton = keep;
            }
            else { AcceptButton = accept; CancelButton = accept; }
            layout.Controls.Add(heading, 0, 0); layout.Controls.Add(viewport, 0, 1); layout.Controls.Add(actions, 0, 2);
            Controls.Add(layout);
            HandleCreated += delegate { SetupTheme.ApplyTitleBar(this); };
        }
        internal static DialogResult ShowQuestion(IWin32Window owner, string message, string title)
        { using (SetupDialog form = new SetupDialog(message, title, true)) return form.ShowDialog(owner); }
        internal static void ShowWarning(IWin32Window owner, string message, string title)
        { using (SetupDialog form = new SetupDialog(message, title, false)) { if (owner == null) form.ShowDialog(); else form.ShowDialog(owner); } }
    }

    /// <summary>Per-control 60 fps ticker that stops itself once settled.</summary>
    internal sealed class SetupMotion : IDisposable
    {
        private readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer { Interval = 15 };
        private readonly Func<bool> step;
        internal SetupMotion(Func<bool> stepValue)
        {
            step = stepValue;
            timer.Tick += delegate { if (!step()) timer.Stop(); };
        }
        internal void Kick() { if (!timer.Enabled) timer.Start(); }
        public void Dispose() { timer.Stop(); timer.Dispose(); }
    }

    /// <summary>Fades a top-level window in on first show, like an iOS app opening.</summary>
    internal static class SetupWindowMotion
    {
        internal static void Prepare(Form form)
        {
            if (!SetupTheme.Motion) return;
            form.Opacity = 0;
            Stopwatch clock = new Stopwatch();
            System.Windows.Forms.Timer fade = new System.Windows.Forms.Timer { Interval = 15 };
            fade.Tick += delegate
            {
                double t = clock.Elapsed.TotalMilliseconds / 280.0;
                if (form.IsDisposed || t >= 1) { fade.Stop(); fade.Dispose(); if (!form.IsDisposed) form.Opacity = 1; return; }
                form.Opacity = SetupTheme.EaseOutCubic(t);
            };
            form.Shown += delegate { clock.Start(); fade.Start(); };
            form.FormClosed += delegate { fade.Stop(); };
        }
    }

    internal sealed class SetupCard : Panel
    {
        internal SetupCard()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
            BackColor = SetupTheme.Paper;
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (GraphicsPath path = SetupTheme.Round(new RectangleF(0.5F, 0.5F, Width - 1, Height - 1), 16 * e.Graphics.DpiX / 96))
            using (Pen border = new Pen(SetupTheme.Line)) e.Graphics.DrawPath(border, path);
        }
    }

    internal sealed class SetupButton : Button
    {
        internal bool Primary;
        internal bool Danger;
        private bool hovered;
        private bool pressed;
        private double hover, press, scale = 1, velocity;
        private readonly SetupMotion motion;
        internal SetupButton()
        {
            motion = new SetupMotion(Step);
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            Cursor = Cursors.Hand;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Padding = new Padding(15, 9, 15, 9);
            UseVisualStyleBackColor = false;
        }
        protected override void OnMouseEnter(EventArgs e) { hovered = true; Animate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hovered = pressed = false; Animate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { pressed = true; Animate(); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { pressed = false; Animate(); base.OnMouseUp(e); }
        private void Animate()
        {
            if (!SetupTheme.Motion) { hover = hovered ? 1 : 0; press = pressed ? 1 : 0; scale = pressed ? 0.965 : 1; velocity = 0; Invalidate(); return; }
            motion.Kick();
        }
        private bool Step()
        {
            hover = SetupTheme.Approach(hover, hovered ? 1 : 0, 0.22);
            press = SetupTheme.Approach(press, pressed ? 1 : 0, pressed ? 0.55 : 0.2);
            // Damped spring: a quick dip on press, a soft overshoot on release.
            double target = pressed ? 0.965 : 1;
            velocity = (velocity + (target - scale) * 0.3) * 0.62;
            scale += velocity;
            bool springing = Math.Abs(velocity) > 0.0002 || Math.Abs(target - scale) > 0.0002;
            if (!springing) { scale = target; velocity = 0; }
            Invalidate();
            return springing || hover != (hovered ? 1 : 0) || press != (pressed ? 1 : 0);
        }
        protected override void Dispose(bool disposing) { if (disposing) motion.Dispose(); base.Dispose(disposing); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Parent == null ? SetupTheme.Paper : Parent.BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            Color baseFill = Primary ? (Danger ? SetupTheme.Destructive : SetupTheme.Accent) : SetupTheme.Secondary;
            Color fill = baseFill;
            if (!Enabled) fill = SetupTheme.Mix(baseFill, Parent == null ? SetupTheme.Paper : Parent.BackColor, 0.5);
            else
            {
                // Match the web buttons' 95% hover / 90% pressed brightness.
                fill = SetupTheme.Mix(fill, Primary ? SetupTheme.Mix(baseFill, Color.Black, 0.05) : SetupTheme.Secondary, hover);
                fill = SetupTheme.Mix(fill, Primary ? SetupTheme.Mix(baseFill, Color.Black, 0.10) : SetupTheme.Active, press);
            }
            // The rounded pill springs; the label stays crisp (GDI text ignores transforms).
            float s = Enabled ? (float)scale : 1F;
            float inset = (1 - s) / 2;
            RectangleF pill = new RectangleF(0.5F + Width * inset, 0.5F + Height * inset, (Width - 1) * s, (Height - 1) * s);
            using (GraphicsPath path = SetupTheme.Round(pill, 9 * e.Graphics.DpiX / 96))
            using (Brush brush = new SolidBrush(fill))
            using (Pen pen = new Pen(Primary && Enabled ? fill : SetupTheme.Line))
            { e.Graphics.FillPath(brush, path); e.Graphics.DrawPath(pen, path); }
            Color text = Primary ? (Danger ? SetupTheme.DestructiveInk : SetupTheme.AccentInk) : SetupTheme.Ink;
            if (!Enabled) text = SetupTheme.Mix(text, Parent == null ? SetupTheme.Paper : Parent.BackColor, 0.5);
            TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, text, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -6, -6), text, fill);
        }
    }

    internal sealed class SetupProgress : Control
    {
        private int value;
        private double shown;
        private ProgressBarStyle style;
        private readonly SetupMotion motion;
        internal double Phase;
        internal bool Failed;
        internal int Value
        {
            get { return value; }
            set
            {
                this.value = value;
                // Forward progress glides; a reset or a non-animated system snaps.
                if (!SetupTheme.Motion || value < shown || style == ProgressBarStyle.Marquee) { shown = value; Invalidate(); }
                else motion.Kick();
            }
        }
        internal ProgressBarStyle Style { get { return style; } set { style = value; Invalidate(); } }
        private bool Step() { shown = SetupTheme.Approach(shown, value, 0.14); Invalidate(); return shown != value; }
        protected override void Dispose(bool disposing) { if (disposing) motion.Dispose(); base.Dispose(disposing); }
        internal SetupProgress()
        {
            motion = new SetupMotion(Step);
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            AccessibleName = "操作进度";
            AccessibleRole = AccessibleRole.ProgressBar;
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            RectangleF track = new RectangleF(0, 0, Math.Max(1, Width), Math.Max(1, Height));
            using (GraphicsPath path = SetupTheme.Round(track, Height / 2F))
            using (Brush brush = new SolidBrush(SetupTheme.Line))
            {
                e.Graphics.FillPath(brush, path);
                e.Graphics.SetClip(path);
                float left = 0, width = (float)(Width * shown / 100.0);
                if (style == ProgressBarStyle.Marquee)
                {
                    width = Width * 0.30F;
                    left = SetupTheme.Motion ? (float)((Math.Sin(Phase * 1.45 - Math.PI / 2) + 1) / 2 * (Width - width)) : (Width - width) / 2;
                }
                if (width > 0)
                {
                    RectangleF area = new RectangleF(left, 0, Math.Max(1, width), Height);
                    using (GraphicsPath bar = SetupTheme.Round(area, Height / 2F))
                    using (Brush accent = new SolidBrush(Failed ? SetupTheme.Destructive : SetupTheme.Accent))
                    {
                        e.Graphics.FillPath(accent, bar);
                    }
                }
                e.Graphics.ResetClip();
            }
        }
    }

    internal sealed class SetupCheckBox : CheckBox
    {
        private double check = -1;
        private readonly SetupMotion motion;
        internal SetupCheckBox()
        {
            motion = new SetupMotion(Step);
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            Cursor = Cursors.Hand;
            UseVisualStyleBackColor = false;
        }
        public override Size GetPreferredSize(Size proposedSize)
        {
            Size text = TextRenderer.MeasureText(Text, Font);
            // The uninstall option uses a separate accessible text label. An
            // empty caption must still reserve space for its painted checkbox.
            int lineHeight = Math.Max(text.Height, TextRenderer.MeasureText("Mg", Font).Height);
            return new Size(text.Width + lineHeight + (int)Math.Ceiling(lineHeight * 0.55), lineHeight + 6);
        }
        protected override void OnCheckedChanged(EventArgs e)
        {
            if (!SetupTheme.Motion || check < 0) { check = Checked ? 1 : 0; Invalidate(); }
            else motion.Kick();
            base.OnCheckedChanged(e);
        }
        private bool Step() { check = SetupTheme.Approach(check, Checked ? 1 : 0, 0.2); Invalidate(); return check != (Checked ? 1 : 0); }
        protected override void Dispose(bool disposing) { if (disposing) motion.Dispose(); base.Dispose(disposing); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Parent == null ? SetupTheme.Panel : Parent.BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            float scale = e.Graphics.DpiX / 96;
            float size = Math.Min(16 * scale, Height - 4);
            if (check < 0) check = Checked ? 1 : 0;
            double amount = Enabled ? check : 0;
            // A small pop while the state changes, settling back to full size.
            float pop = 1 + 0.12F * (float)Math.Sin(Math.PI * check);
            float drawn = size * pop;
            RectangleF box = new RectangleF(0.5F + (size - drawn) / 2, (Height - drawn) / 2, drawn, drawn);
            using (GraphicsPath path = SetupTheme.Round(box, 4 * scale))
            using (Brush fill = new SolidBrush(SetupTheme.Mix(SetupTheme.Paper, SetupTheme.Accent, amount)))
            using (Pen border = new Pen(SetupTheme.Mix(SetupTheme.Line, SetupTheme.Accent, amount)))
            {
                e.Graphics.FillPath(fill, path);
                e.Graphics.DrawPath(border, path);
            }
            if (check > 0.02)
            {
                using (Pen tick = new Pen(Enabled ? SetupTheme.Paper : SetupTheme.Muted, 1.8F * scale))
                {
                    tick.StartCap = tick.EndCap = LineCap.Round;
                    PointF a = new PointF(box.X + drawn * 0.24F, box.Y + drawn * 0.52F), b = new PointF(box.X + drawn * 0.44F, box.Y + drawn * 0.71F), c = new PointF(box.X + drawn * 0.78F, box.Y + drawn * 0.3F);
                    // The tick draws itself: short stroke first, then the long one.
                    float first = (float)Math.Min(1, check / 0.4), second = (float)Math.Max(0, (check - 0.4) / 0.6);
                    PointF midpoint = new PointF(a.X + (b.X - a.X) * first, a.Y + (b.Y - a.Y) * first);
                    if (second <= 0) e.Graphics.DrawLine(tick, a, midpoint);
                    else e.Graphics.DrawLines(tick, new PointF[] { a, b, new PointF(b.X + (c.X - b.X) * second, b.Y + (c.Y - b.Y) * second) });
                }
            }
            Rectangle text = new Rectangle((int)(size + 8 * scale), 0, Math.Max(0, Width - (int)(size + 8 * scale)), Height);
            TextRenderer.DrawText(e.Graphics, Text, Font, text, Enabled ? SetupTheme.Ink : SetupTheme.Muted, TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, text);
        }
    }

    internal sealed class SetupHero : Control
    {
        // DeepSteam 2026-10-16 mark: the phyllotaxis dot mark replaces the orbit rings.
        // It blooms out of its center point on open; while setup works the
        // divergence angle drifts, so the spiral turns into a slow kaleidoscope.
        internal double Phase;
        internal bool Busy;
        private double morph;
        private const int Dots = 170;
        private const double Golden = 137.50776405;
        internal bool Settled { get { return morph <= 0.0001 && (!SetupTheme.Motion || Phase >= 1.9); } }
        internal SetupHero()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            AccessibleName = "DeepSteam 金色圆点旋涡标志";
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            Graphics g = e.Graphics;
            float scale = g.DpiX / 96F;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (Font eyebrow = new Font("Segoe UI", 8.5F, FontStyle.Bold))
            using (Font wordmark = new Font("Georgia", 34F, FontStyle.Regular))
            using (Font tagline = new Font("Microsoft YaHei UI", 11F))
            {
                TextRenderer.DrawText(g, "D E E P S T E A M   /   D E S K T O P", eyebrow, new Point(0, (int)(5 * scale)), SetupTheme.Muted);
                TextRenderer.DrawText(g, "DeepSteam", wordmark, new Point(-3, (int)(24 * scale)), SetupTheme.Ink);
                TextRenderer.DrawText(g, "让好奇心持续生长", tagline, new Point(0, (int)(89 * scale)), SetupTheme.Muted);
            }
            if (Width < 530 * scale) return;
            bool motion = SetupTheme.Motion;
            morph = motion ? SetupTheme.Approach(morph, Busy ? 1 : 0, 0.035) : 0;
            double bloom = motion ? SetupTheme.EaseOutCubic(Phase / 1.8) : 1;
            double cycle = Math.Sin(Math.PI * Math.Max(0, Phase - 1.8) / 9.0);
            double drift = morph * 0.8 * cycle * cycle;               // extra degrees per dot index
            float spin = (float)(-90 * (1 - bloom) + morph * Math.Sin(Phase * 0.21) * 24);
            float cx = Width - 92 * scale, cy = 64 * scale, radius = 60 * scale;
            g.TranslateTransform(cx, cy);
            using (GraphicsPath haloPath = new GraphicsPath())
            {
                float h = radius * 1.25F;
                haloPath.AddEllipse(-h, -h, 2 * h, 2 * h);
                using (PathGradientBrush halo = new PathGradientBrush(haloPath))
                {
                    halo.CenterColor = Color.FromArgb((int)(70 * bloom), 242, 178, 106);
                    halo.SurroundColors = new[] { Color.FromArgb(0, 224, 122, 69) };
                    halo.FocusScales = new PointF(0.05F, 0.05F);
                    g.FillEllipse(halo, -h, -h, 2 * h, 2 * h);
                }
            }
            g.RotateTransform(spin);
            Color inner = Color.FromArgb(255, 241, 214), outer = Color.FromArgb(110, 67, 48);
            float step = (float)(radius / Math.Sqrt(Dots));
            for (int k = Dots; k >= 1; k--)
            {
                double t = (double)k / Dots;
                double angle = (k * (Golden + drift)) * Math.PI / 180.0;
                float r = (float)(step * Math.Sqrt(k) * bloom);
                float size = (float)((1.3 + 2.4 * Math.Sqrt(t)) * scale * (0.4 + 0.6 * bloom));
                Color c = t < 0.45 ? SetupTheme.Mix(inner, SetupTheme.Accent, t / 0.45) : SetupTheme.Mix(SetupTheme.Accent, outer, (t - 0.45) / 0.55);
                int alpha = (int)(255 * Math.Min(1, (1 - t) / 0.22 + 0.15) * Math.Min(1, bloom * 1.6));
                using (Brush dot = new SolidBrush(Color.FromArgb(Math.Max(0, Math.Min(255, alpha)), c)))
                    g.FillEllipse(dot, (float)Math.Cos(angle) * r - size / 2, (float)Math.Sin(angle) * r - size / 2, size, size);
            }
            g.ResetTransform();
            g.TranslateTransform(cx, cy);
            float pulse = (float)(1 + morph * 0.18 * Math.Sin(Phase * 2.2));
            using (GraphicsPath corePath = new GraphicsPath())
            {
                float glow = 13 * scale * pulse;
                corePath.AddEllipse(-glow, -glow, 2 * glow, 2 * glow);
                using (PathGradientBrush core = new PathGradientBrush(corePath))
                {
                    core.CenterColor = Color.FromArgb(235, 255, 248, 234);
                    core.SurroundColors = new[] { Color.FromArgb(0, 242, 178, 106) };
                    g.FillEllipse(core, -glow, -glow, 2 * glow, 2 * glow);
                }
            }
            using (Brush center = new SolidBrush(Color.FromArgb(255, 255, 250, 240)))
                g.FillEllipse(center, -2.6F * scale * pulse, -2.6F * scale * pulse, 5.2F * scale * pulse, 5.2F * scale * pulse);
            g.ResetTransform();
        }
    }

    internal sealed class InstallerForm : Form
    {
        private readonly TextBox directory = new TextBox();
        private readonly Button browse = new SetupButton();
        private readonly Button install = new SetupButton();
        private readonly Button start = new SetupButton();
        private readonly Button stop = new SetupButton();
        private readonly Button cancel = new SetupButton();
        private readonly CheckBox shortcuts = new SetupCheckBox();
        private readonly CheckBox openAfter = new SetupCheckBox();
        private readonly Label state = new Label();
        private readonly TextBox output = new TextBox();
        private readonly SetupProgress progress = new SetupProgress();
        private readonly SetupHero hero = new SetupHero();
        private readonly Label tip = new Label();
        private readonly Label phaseLabel = new Label();
        private readonly Label progressValue = new Label();
        private readonly LinkLabel details = new LinkLabel();
        private readonly LinkLabel copyLog = new LinkLabel();
        private readonly Panel detailsPanel = new Panel();
        private readonly System.Windows.Forms.Timer animation = new System.Windows.Forms.Timer();
        private readonly Stopwatch motionClock = new Stopwatch();
        private readonly string[] tips = { "连接你选择的模型，围绕问题展开学习。", "打开资料文件夹，从自己的教材和文档开始学习。", "在同一工作区中继续对话、练习和复习。", "如需了解处理情况，可展开操作详情。" };
        private int tipIndex = -1;
        private readonly BackgroundWorker worker = new BackgroundWorker();
        private readonly string startupAction;
        private volatile bool cancelled;
        private bool busy;
        private bool installing;
        private bool closeAfterCancel;
        private bool requestedLaunch;
        private readonly object processLock = new object();
        private KillJob activeJob;
        private string operationRoot;

        internal InstallerForm(string action)
        {
            SuspendLayout();
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            startupAction = action;
            SetupWindowMotion.Prepare(this);
            Text = "DeepSteam 安装与启动";
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleDimensions = new SizeF(96F, 96F);
            AutoScaleMode = AutoScaleMode.Dpi;
            Font = new Font("Microsoft YaHei UI", 9.5F);
            BackColor = SetupTheme.Paper;
            ForeColor = SetupTheme.Ink;
            ClientSize = new Size(868, 700);
            MinimumSize = new Size(800, 670);
            DoubleBuffered = true;

            Panel viewport = new Panel();
            viewport.Dock = DockStyle.Fill;
            viewport.AutoScroll = true;
            Controls.Add(viewport);
            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Top;
            layout.AutoSize = true;
            layout.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            layout.Padding = new Padding(32, 20, 32, 18);
            layout.Margin = Padding.Empty;
            layout.ColumnCount = 1;
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            for (int i = 0; i < 6; i++) layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            viewport.Controls.Add(layout);
            hero.Dock = DockStyle.Top;
            hero.Height = 140;
            hero.Margin = new Padding(0, 0, 0, 10);
            layout.Controls.Add(hero, 0, 0);

            SetupCard setup = new SetupCard();
            setup.BackColor = SetupTheme.Panel;
            setup.Dock = DockStyle.Top;
            setup.AutoSize = true;
            setup.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            setup.Padding = new Padding(23, 20, 23, 21);
            setup.Margin = new Padding(0, 0, 0, 18);
            TableLayoutPanel settings = new TableLayoutPanel();
            settings.Dock = DockStyle.Top;
            settings.AutoSize = true;
            settings.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            settings.ColumnCount = 1;
            settings.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            settings.Margin = Padding.Empty;
            settings.BackColor = SetupTheme.Panel;
            for (int i = 0; i < 4; i++) settings.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            setup.Controls.Add(settings);
            Label directoryLabel = MakeLabel("设置 DeepSteam 安装位置", 12F, true);
            directoryLabel.Margin = new Padding(0, 0, 0, 7);
            settings.Controls.Add(directoryLabel, 0, 0);
            Label directoryHint = MakeLabel("请选择本机磁盘中的专用文件夹", 9F, false);
            directoryHint.ForeColor = SetupTheme.Muted;
            directoryHint.Margin = new Padding(0, 0, 0, 12);
            settings.Controls.Add(directoryHint, 0, 1);

            TableLayoutPanel folderRow = new TableLayoutPanel();
            folderRow.Dock = DockStyle.Top;
            folderRow.AutoSize = true;
            folderRow.ColumnCount = 2;
            folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            folderRow.Margin = new Padding(0, 0, 0, 14);
            Panel input = new SetupCard();
            input.Dock = DockStyle.Fill;
            input.Height = 44;
            input.Padding = new Padding(13, 11, 13, 10);
            input.Margin = new Padding(0, 0, 10, 0);
            directory.Anchor = AnchorStyles.Left | AnchorStyles.Right;
            directory.Dock = DockStyle.Top;
            directory.BorderStyle = BorderStyle.None;
            directory.BackColor = SetupTheme.Paper;
            directory.ForeColor = SetupTheme.Ink;
            directory.AccessibleName = "DeepSteam 安装位置";
            directory.Text = DefaultRoot();
            directory.TextChanged += delegate { UpdateButtons(); };
            input.Controls.Add(directory);
            ConfigureButton(browse, "选择文件夹", 108);
            browse.Margin = Padding.Empty;
            browse.Click += delegate { ChooseFolder(); };
            folderRow.Controls.Add(input, 0, 0);
            folderRow.Controls.Add(browse, 1, 0);
            settings.Controls.Add(folderRow, 0, 2);

            FlowLayoutPanel options = new FlowLayoutPanel();
            options.Dock = DockStyle.Top;
            options.AutoSize = true;
            options.Margin = Padding.Empty;
            options.BackColor = SetupTheme.Panel;
            shortcuts.Text = "创建桌面快捷方式";
            shortcuts.Checked = true;
            shortcuts.AutoSize = true;
            shortcuts.Margin = new Padding(0, 0, 24, 0);
            openAfter.Text = "安装完成后打开 DeepSteam";
            openAfter.Checked = true;
            openAfter.AutoSize = true;
            openAfter.Margin = Padding.Empty;
            options.Controls.Add(shortcuts);
            options.Controls.Add(openAfter);
            settings.Controls.Add(options, 0, 3);
            layout.Controls.Add(setup, 0, 1);

            FlowLayoutPanel buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Top;
            buttons.AutoSize = true;
            buttons.Margin = new Padding(0, 0, 0, 20);
            ConfigureButton(install, "安装 DeepSteam", 152);
            ((SetupButton)install).Primary = true;
            ConfigureButton(start, "打开软件", 106);
            ConfigureButton(stop, "停止服务", 106);
            ConfigureButton(cancel, "取消安装", 106);
            install.Click += delegate { BeginInstall(); };
            start.Click += delegate { BeginService(false); };
            stop.Click += delegate { BeginService(true); };
            cancel.Click += delegate { CancelInstall(); };
            buttons.Controls.AddRange(new Control[] { install, start, stop, cancel });
            layout.Controls.Add(buttons, 0, 2);

            SetupCard statusCard = new SetupCard();
            statusCard.BackColor = SetupTheme.Panel;
            statusCard.Dock = DockStyle.Top;
            statusCard.AutoSize = true;
            statusCard.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            statusCard.Padding = new Padding(23, 18, 23, 18);
            statusCard.Margin = new Padding(0, 0, 0, 12);
            TableLayoutPanel statusLayout = new TableLayoutPanel();
            statusLayout.Dock = DockStyle.Top;
            statusLayout.AutoSize = true;
            statusLayout.BackColor = SetupTheme.Panel;
            statusLayout.ColumnCount = 2;
            statusLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            statusLayout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            for (int i = 0; i < 4; i++) statusLayout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            phaseLabel.Text = "准备就绪";
            phaseLabel.Font = new Font(Font, FontStyle.Bold);
            phaseLabel.AutoSize = true;
            phaseLabel.Margin = new Padding(0, 0, 0, 7);
            progressValue.AutoSize = true;
            progressValue.ForeColor = SetupTheme.Muted;
            progressValue.Margin = Padding.Empty;
            statusLayout.Controls.Add(phaseLabel, 0, 0);
            statusLayout.Controls.Add(progressValue, 1, 0);
            state.Text = "选择安装位置后即可开始。安装包已包含运行环境和本地文档工具。";
            state.AutoSize = true;
            state.Dock = DockStyle.Top;
            state.ForeColor = SetupTheme.Muted;
            state.Margin = new Padding(0, 0, 0, 15);
            statusLayout.Controls.Add(state, 0, 1);
            statusLayout.SetColumnSpan(state, 2);
            progress.Dock = DockStyle.Top;
            progress.Height = 6;
            progress.Margin = new Padding(0, 0, 0, 14);
            statusLayout.Controls.Add(progress, 0, 2);
            statusLayout.SetColumnSpan(progress, 2);
            tip.Text = tips[0];
            tip.AutoSize = true;
            tip.ForeColor = SetupTheme.Muted;
            tip.Font = new Font("Microsoft YaHei UI", 9F);
            tip.Margin = Padding.Empty;
            statusLayout.Controls.Add(tip, 0, 3);
            statusLayout.SetColumnSpan(tip, 2);
            statusCard.Controls.Add(statusLayout);
            layout.Controls.Add(statusCard, 0, 3);
            statusLayout.SizeChanged += delegate
            {
                int max = Math.Max(80, statusLayout.ClientSize.Width);
                state.MaximumSize = new Size(max, 0);
                tip.MaximumSize = new Size(max, 0);
            };

            TableLayoutPanel diagnostics = new TableLayoutPanel();
            diagnostics.Dock = DockStyle.Top;
            diagnostics.AutoSize = true;
            diagnostics.ColumnCount = 2;
            diagnostics.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            diagnostics.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            diagnostics.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            diagnostics.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            diagnostics.Margin = Padding.Empty;
            details.Text = "展开操作详情 +";
            details.AutoSize = true;
            details.LinkColor = details.ActiveLinkColor = SetupTheme.Muted;
            details.LinkBehavior = LinkBehavior.HoverUnderline;
            details.Margin = new Padding(0, 2, 0, 8);
            details.LinkClicked += delegate { SetDetails(!detailsPanel.Visible); };
            copyLog.Text = "复制详情";
            copyLog.AutoSize = true;
            copyLog.Visible = false;
            copyLog.LinkColor = copyLog.ActiveLinkColor = SetupTheme.Muted;
            copyLog.LinkBehavior = LinkBehavior.HoverUnderline;
            copyLog.LinkClicked += delegate { try { if (output.TextLength > 0) Clipboard.SetText(output.Text); } catch (ExternalException) { state.Text = "复制未完成，请重试或在详情中选择文字。"; } };
            diagnostics.Controls.Add(details, 0, 0);
            diagnostics.Controls.Add(copyLog, 1, 0);
            detailsPanel.Dock = DockStyle.Top;
            detailsPanel.Height = 154;
            detailsPanel.Visible = false;
            detailsPanel.Padding = new Padding(12);
            detailsPanel.BackColor = SetupTheme.Panel;
            output.Multiline = true;
            output.ReadOnly = true;
            output.ScrollBars = ScrollBars.Vertical;
            output.Dock = DockStyle.Fill;
            output.BorderStyle = BorderStyle.None;
            output.BackColor = SetupTheme.Panel;
            output.ForeColor = SetupTheme.Ink;
            output.Font = new Font("Microsoft YaHei UI", 8.5F);
            output.AccessibleName = "操作详情与诊断信息";
            detailsPanel.Controls.Add(output);
            diagnostics.Controls.Add(detailsPanel, 0, 1);
            diagnostics.SetColumnSpan(detailsPanel, 2);
            layout.Controls.Add(diagnostics, 0, 4);
            Label version = MakeLabel("WINDOWS  ·  " + Program.DisplayVersion(Path.GetDirectoryName(Application.ExecutablePath)), 8F, false);
            version.ForeColor = SetupTheme.Muted;
            version.Margin = new Padding(0, 16, 0, 0);
            layout.Controls.Add(version, 0, 5);

            animation.Interval = 16;
            animation.Tick += delegate
            {
                if (!Visible || WindowState == FormWindowState.Minimized) return;
                double elapsed = motionClock.Elapsed.TotalSeconds;
                if (SetupTheme.Motion)
                {
                    hero.Phase = progress.Phase = elapsed;
                    hero.Busy = busy;
                    hero.Invalidate();
                    if (progress.Style == ProgressBarStyle.Marquee) progress.Invalidate();
                    int next = (int)(elapsed / 4.2) % tips.Length;
                    if (busy && next != tipIndex) { tipIndex = next; tip.Text = tips[next]; }
                }
                if (!busy && elapsed > 2.4 && hero.Settled) animation.Stop();
            };
            FormClosed += delegate { animation.Stop(); animation.Dispose(); };
            worker.WorkerSupportsCancellation = true;
            worker.DoWork += DoWork;
            worker.RunWorkerCompleted += Completed;
            FormClosing += ClosingForm;
            Shown += delegate
            {
                ApplyDarkTitleBar();
                Rectangle work = Screen.FromControl(this).WorkingArea;
                int safeWidth = Math.Max(340, work.Width - 64), safeHeight = Math.Max(420, work.Height - 64);
                MinimumSize = new Size(Math.Min(MinimumSize.Width, safeWidth), Math.Min(MinimumSize.Height, safeHeight));
                Size = new Size(Math.Min(Width, safeWidth), Math.Min(Height, safeHeight));
                Location = new Point(work.Left + (work.Width - Width) / 2, work.Top + (work.Height - Height) / 2);
                motionClock.Start();
                if (SetupTheme.Motion) animation.Start();
                UpdateButtons();
                if (IsComplete(directory.Text)) { phaseLabel.Text = "已安装，可直接使用"; state.Text = "DeepSteam 已安装，打开软件即可继续学习。"; }
                if (startupAction == "--launch") BeginService(false);
                else if (startupAction == "--stop") BeginService(true);
            };
            UpdateButtons();
            ResumeLayout(true);
        }

        private static void ConfigureButton(Button button, string text, int width)
        {
            button.Text = text;
            button.MinimumSize = new Size(width, 42);
            button.Margin = new Padding(0, 0, 10, 0);
        }

        private static Label MakeLabel(string text, float size, bool bold)
        {
            Label label = new Label();
            label.Text = text;
            label.Font = new Font("Microsoft YaHei UI", size, bold ? FontStyle.Bold : FontStyle.Regular);
            label.AutoSize = true;
            label.BackColor = Color.Transparent;
            return label;
        }

        private void SetDetails(bool visible)
        {
            detailsPanel.Visible = copyLog.Visible = visible;
            details.Text = visible ? "收起操作详情 -" : "展开操作详情 +";
        }

        private void ApplyDarkTitleBar()
        {
            SetupTheme.ApplyTitleBar(this);
        }

        private string DefaultRoot()
        {
            string ownDirectory = Path.GetDirectoryName(Application.ExecutablePath);
            bool ownHasMarker = File.Exists(Path.Combine(ownDirectory, Program.InstalledMarker)) ||
                File.Exists(Path.Combine(ownDirectory, Program.InstallingMarker));
            bool explicitOwnSelection = InstallLocation.UseOwnSelection(startupAction, ownHasMarker);
            return InstallLocation.SelectDefault(ownDirectory, explicitOwnSelection,
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                !explicitOwnSelection && InstallLocation.PreferredDUsable());
        }

        private void ChooseFolder()
        {
            using (FolderBrowserDialog picker = new FolderBrowserDialog())
            {
                picker.Description = "请选择 DeepSteam 专用安装文件夹，不会覆盖已有的个人文件。";
                picker.ShowNewFolderButton = true;
                if (Directory.Exists(directory.Text)) picker.SelectedPath = directory.Text;
                if (picker.ShowDialog(this) == DialogResult.OK)
                {
                    string selected = picker.SelectedPath;
                    if (!String.Equals(Path.GetFileName(selected.TrimEnd('\\')), "DeepSteam", StringComparison.OrdinalIgnoreCase) &&
                        !File.Exists(Path.Combine(selected, Program.InstallingMarker)) && !File.Exists(Path.Combine(selected, Program.InstalledMarker)))
                        selected = Path.Combine(selected, "DeepSteam");
                    directory.Text = selected;
                }
            }
        }

        private void UpdateButtons()
        {
            bool complete = IsComplete(directory.Text);
            directory.Enabled = browse.Enabled = !busy;
            shortcuts.Enabled = openAfter.Enabled = !busy;
            install.Enabled = !busy && !complete;
            start.Enabled = stop.Enabled = !busy && complete;
            cancel.Enabled = busy && installing && !cancelled;
            ((SetupButton)install).Primary = !complete;
            ((SetupButton)start).Primary = complete;
            bool resumable = false;
            try { resumable = !complete && File.Exists(Path.Combine(directory.Text, Program.InstallingMarker)); }
            catch (ArgumentException) { }
            catch (NotSupportedException) { }
            install.Text = resumable ? "继续安装" : "安装 DeepSteam";
            install.Invalidate();
            start.Invalidate();
        }

        private static bool IsComplete(string root)
        {
            try { return File.Exists(Path.Combine(root, Program.InstalledMarker)); }
            catch (ArgumentException) { return false; }
            catch (NotSupportedException) { return false; }
        }

        private string ValidatedRoot()
        {
            string root = Path.GetFullPath(directory.Text.Trim()).TrimEnd('\\');
            if (!Path.IsPathRooted(root) || root.StartsWith("\\\\") || root.Length <= 3)
                throw new IOException("请选择本机磁盘中的专用文件夹，不要选择磁盘根目录或网络共享位置。");
            if (root.Length > 100) throw new IOException("安装位置过长，请选择较短路径，例如 D:\\DeepSteam。");
            Package.EnsureNoReparsePoint(root);
            return root;
        }

        private void BeginInstall()
        {
            if (busy) return;
            try
            {
                operationRoot = ValidatedRoot();
                if (Directory.Exists(operationRoot) && Directory.GetFileSystemEntries(operationRoot).Length > 0 &&
                    !File.Exists(Path.Combine(operationRoot, Program.InstallingMarker)))
                    throw new IOException("此文件夹中已有文件，请选择新的 DeepSteam 专用文件夹；已有内容不会被覆盖。");
                requestedLaunch = openAfter.Checked;
                BeginOperation(true, "install");
            }
            catch (Exception ex) { ShowError(ex.Message); }
        }

        private void BeginService(bool stopping)
        {
            if (busy) return;
            try
            {
                operationRoot = ValidatedRoot();
                if (!File.Exists(Path.Combine(operationRoot, Program.InstalledMarker)))
                    throw new IOException("此位置的安装尚未完成，请先点击安装或继续安装。");
                BeginOperation(false, stopping ? "stop" : "start");
            }
            catch (Exception ex) { ShowError(ex.Message); }
        }

        private void BeginOperation(bool isInstall, string action)
        {
            busy = true;
            installing = isInstall;
            cancelled = false;
            progress.Value = 0;
            progress.Failed = false;
            progress.Style = ProgressBarStyle.Marquee;
            progressValue.Text = "进行中";
            phaseLabel.ForeColor = SetupTheme.Ink;
            phaseLabel.Text = isInstall ? "正在校验安装包" : action == "stop" ? "正在停止" : "准备启动";
            state.Text = isInstall ? "正在校验安装包完整性，通过后开始解压。" : action == "stop" ? "正在安全停止本地服务，请稍候。" : "正在检查运行环境并打开软件窗口。";
            tipIndex = -1;
            motionClock.Restart();
            if (SetupTheme.Motion) animation.Start();
            UpdateButtons();
            worker.RunWorkerAsync(new Operation { Action = action, Root = operationRoot, Shortcuts = shortcuts.Checked });
        }

        private void DoWork(object sender, DoWorkEventArgs e)
        {
            Operation op = (Operation)e.Argument;
            if (op.Action == "install")
            {
                Log("Installation directory: " + op.Root);
                PayloadSummary summary = Package.Validate();
                Package.EnsureDiskSpace(op.Root, summary.Bytes);
                Directory.CreateDirectory(op.Root);
                File.WriteAllText(Path.Combine(op.Root, Program.InstallingMarker), "DeepSteam " + Program.Version, new UTF8Encoding(false));
                SetStatus("正在将程序、运行环境和文档工具解压到所选文件夹。", false);
                Package.Extract(op.Root, Log, SetProgress, delegate { return cancelled; });
                if (cancelled) throw new OperationCanceledException();
                CopyLauncher(op.Root);
                SetStatus("正在校验和配置运行环境，首次安装可能需要几分钟。", true);
                RunScript(op.Root, "Install-DeepSteam.ps1", true);
                if (cancelled) throw new OperationCanceledException();
                File.WriteAllText(Path.Combine(op.Root, Program.InstalledMarker), "DeepSteam " + Program.Version + "\r\n" + DateTime.UtcNow.ToString("o"), new UTF8Encoding(false));
                if (File.Exists(Path.Combine(op.Root, Program.InstallingMarker))) File.Delete(Path.Combine(op.Root, Program.InstallingMarker));
                UninstallRegistration.Register(op.Root);
                if (op.Shortcuts)
                {
                    try { CreateShortcuts(op.Root); }
                    catch (Exception ex) { Log("Installation completed, but desktop shortcuts could not be created: " + ex.Message + "; open DeepSteam.exe in the installation directory instead."); }
                }
                Log("Installation complete. Launch DeepSteam, then connect a model or open a workspace from the sidebar.");
            }
            else RunScript(op.Root, op.Action == "stop" ? "Stop-DeepSteam.ps1" : "Start-DeepSteam.ps1", false);
            e.Result = op.Action;
        }

        private static void CopyLauncher(string root)
        {
            string destination = Path.Combine(root, "DeepSteam.exe");
            if (String.Equals(Path.GetFullPath(destination), Path.GetFullPath(Application.ExecutablePath), StringComparison.OrdinalIgnoreCase)) return;
            if (!File.Exists(destination)) File.Copy(Application.ExecutablePath, destination, false);
        }

        private void RunScript(string root, string scriptName, bool cancellable)
        {
            string script = Path.Combine(root, "installer", scriptName);
            if (!File.Exists(script)) throw new FileNotFoundException("缺少启动文件，请检查安装包是否完整。", scriptName);
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
            info.Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + Quote(script) + " -InstallRoot " + Quote(root);
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.StandardOutputEncoding = Encoding.UTF8;
            info.StandardErrorEncoding = Encoding.UTF8;
            using (Process process = new Process())
            {
                process.StartInfo = info;
                process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Log(e.Data); };
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Log(e.Data); };
                KillJob job = cancellable ? new KillJob() : null;
                try
                {
                    lock (processLock)
                    {
                        if (cancelled) throw new OperationCanceledException();
                        process.Start();
                        try { if (job != null) job.Add(process); }
                        catch { try { process.Kill(); } catch { } throw; }
                        activeJob = job;
                    }
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();
                    process.WaitForExit();
                    if (cancelled) throw new OperationCanceledException();
                    if (process.ExitCode != 0) throw new IOException("操作未完成（退出代码 " + process.ExitCode + "）。请展开操作详情。已完成的文件会保留，可继续安装。");
                }
                finally
                {
                    lock (processLock) { activeJob = null; if (job != null) job.Dispose(); }
                }
            }
        }

        private void CancelInstall()
        {
            if (!busy || !installing) return;
            cancelled = true;
            lock (processLock) { if (activeJob != null) activeJob.Dispose(); }
            state.Text = "正在停止安装，已完成的文件会保留，之后可继续安装。";
            phaseLabel.Text = "正在取消";
            UpdateButtons();
        }

        private void Completed(object sender, RunWorkerCompletedEventArgs e)
        {
            bool wasInstall = installing;
            busy = installing = false;
            animation.Stop();
            progress.Style = ProgressBarStyle.Continuous;
            if (cancelled || e.Error is OperationCanceledException)
            {
                state.Text = "安装已取消。再次选择此文件夹即可继续，已有文件未删除。";
                phaseLabel.Text = "安装已暂停";
                progressValue.Text = "已取消";
                tip.Text = "已完成的文件已保留，可稍后继续安装。";
                Log(state.Text);
            }
            else if (e.Error != null) ShowError(e.Error.Message);
            else
            {
                progress.Value = 100;
                string action = e.Result as string;
                state.Text = action == "install" ? "DeepSteam 安装完成，打开软件即可开始学习。" : action == "stop" ? "本地服务已停止，需要时可从桌面重新打开 DeepSteam。" : "DeepSteam 窗口已打开，后续启动进度将在软件中显示。";
                phaseLabel.Text = action == "install" ? "安装完成" : action == "stop" ? "已安全停止" : "软件窗口已打开";
                progressValue.Text = "已完成";
                tip.Text = action == "stop" ? "学习记录已保留，下次打开可继续使用。" : "让好奇心持续生长";
                Log(state.Text);
            }
            UpdateButtons();
            // The installed launch/stop entry is a bootstrap, not a second
            // persistent application. Successful handoff must release its PE
            // file so a later uninstall can remove the installed launcher.
            if (!wasInstall && e.Error == null && !cancelled &&
                (startupAction == "--launch" || startupAction == "--stop")) { Close(); return; }
            if (closeAfterCancel) { Close(); return; }
            if (wasInstall && e.Error == null && !cancelled && requestedLaunch) BeginService(false);
        }

        private void ClosingForm(object sender, FormClosingEventArgs e)
        {
            if (!busy) return;
            e.Cancel = true;
            if (installing && SetupDialog.ShowQuestion(this, "安装仍在进行，是否取消并关闭？已完成的文件将保留。", "DeepSteam") == DialogResult.Yes)
            {
                closeAfterCancel = true;
                CancelInstall();
            }
            else if (!installing) state.Text = "请等待当前启动或停止操作完成。";
        }

        private void SetProgress(int value)
        {
            UI(delegate { progress.Style = ProgressBarStyle.Continuous; progress.Value = Math.Max(0, Math.Min(100, value)); progressValue.Text = progress.Value + "%"; phaseLabel.Text = "正在解压"; });
        }

        private void SetStatus(string message, bool indeterminate)
        {
            UI(delegate { state.Text = message; phaseLabel.Text = indeterminate ? "正在配置运行环境" : "正在解压"; progressValue.Text = indeterminate ? "进行中" : "0%"; progress.Style = indeterminate ? ProgressBarStyle.Marquee : ProgressBarStyle.Continuous; });
        }

        private void ShowError(string message)
        {
            state.Text = "尚未完成：" + message;
            phaseLabel.Text = "需要处理";
            phaseLabel.ForeColor = SetupTheme.Destructive;
            progress.Failed = true;
            progressValue.Text = "尚未完成";
            tip.Text = "请查看下方详情，已有文件和学习记录会保留。";
            SetDetails(true);
            Log(state.Text);
        }

        private void Log(string message)
        {
            string safe = Regex.Replace(message, @"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)(\s*[:=]\s*)\S+", "$1$2[hidden]");
            safe = Regex.Replace(safe, @"(https?://)[^\s/@]+:[^\s/@]+@", "$1[hidden]@");
            safe = Regex.Replace(safe, @"\bsk-[A-Za-z0-9_-]{16,}\b", "[hidden]");
            if (safe.Length > 4000) safe = safe.Substring(0, 4000) + " …";
            UI(delegate
            {
                if (output.TextLength > 180000) output.Text = output.Text.Substring(output.TextLength - 120000);
                output.AppendText(safe + Environment.NewLine);
            });
        }

        private void UI(Action action)
        {
            if (IsDisposed || !IsHandleCreated) return;
            try { if (InvokeRequired) BeginInvoke(action); else action(); }
            catch (InvalidOperationException) { }
        }

        internal static string Quote(string text)
        {
            StringBuilder result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in text)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); slashes = 0; continue; }
                result.Append('\\', slashes); slashes = 0; result.Append(c);
            }
            result.Append('\\', slashes * 2);
            return result.Append('"').ToString();
        }

        internal static void CreateShortcuts(string root)
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(shellType);
            try
            {
                string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                MakeShortcut(shell, Path.Combine(desktop, "DeepSteam.lnk"), root, "--launch", "启动 DeepSteam 教育智能体");
                MakeShortcut(shell, Path.Combine(desktop, "关闭 DeepSteam.lnk"), root, "--stop", "关闭 DeepSteam 本机服务");
                UninstallRegistration.CreateUninstallShortcut(root);
            }
            finally { if (shell != null && Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell); }
        }

        private static void MakeShortcut(object shell, string file, string root, string args, string description)
        {
            // Preserve unrelated existing shortcuts instead of silently replacing them.
            if (File.Exists(file)) file = Path.Combine(Path.GetDirectoryName(file), Path.GetFileNameWithoutExtension(file) + " " + Program.Version + ".lnk");
            if (File.Exists(file)) return;
            object shortcut = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { file });
            try
            {
                Type type = shortcut.GetType();
                type.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { Path.Combine(root, "DeepSteam.exe") });
                type.InvokeMember("Arguments", BindingFlags.SetProperty, null, shortcut, new object[] { args });
                type.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { root });
                type.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { description });
                type.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { Path.Combine(root, "DeepSteam.ico") + ",0" });
                type.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
            }
            finally { if (shortcut != null && Marshal.IsComObject(shortcut)) Marshal.FinalReleaseComObject(shortcut); }
        }

        private sealed class Operation
        {
            internal string Action;
            internal string Root;
            internal bool Shortcuts;
        }
    }

    // Per-user uninstall registration. The manifest is anchored in HKCU so a
    // forged marker, edited file list or a neighbouring installation cannot
    // authorize deletion. Only packaged program files are candidates; neither
    // an entire install folder nor a workspace is recursively removed.
    internal sealed class UninstallContext
    {
        internal string Root, Id, Version, Manifest;
        internal List<UninstallFile> Files = new List<UninstallFile>();
        internal List<UninstallLink> Links = new List<UninstallLink>();
        internal List<string> DataRoots = new List<string>();
        // A verified pre-removal snapshot only adds protection. It lets a
        // partially removed install retry after its Python reader is gone.
        internal bool WorkspaceSnapshotReady;
        internal List<string> WorkspaceSnapshot = new List<string>();
    }
    internal sealed class UninstallFile { internal string Path, Hash; internal long Bytes; }
    internal sealed class UninstallLink { internal string Path, Target; }

    internal static class UninstallRegistration
    {
        internal const string ManifestName = ".deepsteam-uninstall-manifest";
        internal const string IdName = ".deepsteam-uninstall-id";
        internal const string RegistryParent = @"Software\Microsoft\Windows\CurrentVersion\Uninstall";
        internal static string RegistryName(string id) { return RegistryParent + "\\DeepSteam-" + id; }
        internal static string B64(string value) { return Convert.ToBase64String(Encoding.UTF8.GetBytes(value)); }
        internal static string UnB64(string value) { return Encoding.UTF8.GetString(Convert.FromBase64String(value)); }
        [ThreadStatic] private static byte[] hashBuffer;
        internal static string Sha(string path)
        { return Sha(path, null); }
        internal static string Sha(string path, Action<int> bytesRead)
        {
            PlainPath(path);
            using (FileStream input = new FileStream(Package.Extended(path), FileMode.Open, FileAccess.Read, FileShare.Read, 64 * 1024, FileOptions.SequentialScan))
            using (SHA256 sha = SHA256.Create())
            {
                byte[] buffer = hashBuffer ?? (hashBuffer = new byte[64 * 1024]); int count;
                while ((count = input.Read(buffer, 0, buffer.Length)) != 0)
                { sha.TransformBlock(buffer, 0, count, buffer, 0); if (bytesRead != null) bytesRead(count); }
                sha.TransformFinalBlock(buffer, 0, 0);
                return BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
            }
        }
        internal static object Json(string path)
        {
            Assembly assembly = Assembly.Load("System.Web.Extensions, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35");
            Type type = assembly.GetType("System.Web.Script.Serialization.JavaScriptSerializer", true);
            object serializer = Activator.CreateInstance(type);
            type.GetProperty("MaxJsonLength").SetValue(serializer, 64 * 1024 * 1024, null);
            return type.GetMethod("DeserializeObject").Invoke(serializer, new object[] { File.ReadAllText(Package.Extended(path), Encoding.UTF8) });
        }
        internal static string Root(string value)
        {
            if (String.IsNullOrEmpty(value) || !Path.IsPathRooted(value) || value.StartsWith("\\\\") || value.StartsWith("//") || value.StartsWith(@"\\?\"))
                throw new IOException("The uninstall location must be an absolute path on a regular local drive.");
            string full = Path.GetFullPath(value).TrimEnd('\\');
            if (full.Length <= 3 || String.Equals(full, Path.GetPathRoot(full).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
                throw new IOException("A drive root cannot be used as the uninstall location.");
            foreach (string segment in value.Replace('/', '\\').Split('\\'))
                if (segment == "." || segment == ".." || segment.EndsWith(".") || segment.EndsWith(" "))
                    throw new IOException("The uninstall location contains an ambiguous path.");
            PlainPath(full);
            return full;
        }
        internal static void PlainPath(string path)
        {
            string current = Path.GetFullPath(path);
            while (!String.IsNullOrEmpty(current))
            {
                try
                {
                    if ((File.GetAttributes(Package.Extended(current)) & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("The uninstall path cannot pass through links or directory junctions. Files were preserved.");
                }
                catch (FileNotFoundException) { }
                catch (DirectoryNotFoundException) { }
                current = Path.GetDirectoryName(current);
            }
        }
        internal static string Child(string root, string value)
        {
            string normal = Package.EntryPath(value).TrimEnd('/');
            string full = Path.GetFullPath(Path.Combine(root, normal.Replace('/', '\\')));
            if (!full.StartsWith(root + "\\", StringComparison.OrdinalIgnoreCase)) throw new IOException("An uninstall file escapes the installation directory.");
            return full;
        }
        internal static bool Under(string path, string folder)
        {
            return String.Equals(path, folder, StringComparison.OrdinalIgnoreCase) || path.StartsWith(folder.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
        }
        internal static bool Protected(string path)
        {
            string value = path.Replace('\\', '/').ToLowerInvariant();
            // These exact factory files describe packaged OCR engines. They are
            // not account or workspace configuration. Ownership still requires
            // the reviewed SHA; edited installed bytes remain user-owned.
            bool factoryOcrConfig = value == "runtime/python/lib/site-packages/rapidocr/config.yaml";
            bool factoryMineruMetadata = value == "runtime/mineru/runtime.json";
            foreach (string prefix in new string[] { "data", "logs", "cache", "reports", "extensions", "runtime/temp", "runtime/deeptutor-home", "runtime/harness-state", "runtime/openmaic-standalone/data", "upstream/openmaic/data" })
                if (value == prefix || value.StartsWith(prefix + "/", StringComparison.Ordinal)) return true;
            return value == "deepsteam-storage.json" || value.EndsWith("/process.json") || (value.EndsWith("/runtime.json") && !factoryMineruMetadata) ||
                value.EndsWith("/workspace-folders.json") || value.EndsWith("/desktop-claims.json") || value.EndsWith(".sqlite3") ||
                value.EndsWith(".sqlite3-wal") || value.EndsWith(".sqlite3-shm") || value.EndsWith(".log") ||
                value.Contains("/.local/") || value.Contains("/desktop-claims/") || (value.EndsWith("/config.yaml") && !factoryOcrConfig) ||
                value.EndsWith("/config.json") || value.EndsWith("/settings.json") || value == "installer/deepsteam-uninstall-retained.txt";
        }
        internal static void Register(string root)
        {
            root = Root(root);
            string completed = Path.Combine(root, Program.InstalledMarker); PlainPath(completed);
            if (!File.Exists(completed) || new FileInfo(completed).Length > 8192) throw new IOException("Installation is incomplete; an uninstall entry cannot be registered.");
            string firstLine = File.ReadAllLines(completed, Encoding.UTF8)[0];
            if (!firstLine.StartsWith("DeepSteam ", StringComparison.Ordinal) || firstLine.Length <= 10) throw new IOException("The installation completion marker is invalid.");
            string executable = Path.Combine(root, "Uninstall-DeepSteam.exe");
            UninstallContext previous = null;
            if (File.Exists(Path.Combine(root, IdName)))
            {
                // Re-registration has to validate the earlier trusted record
                // before it can replace only the public uninstaller binary.
                previous = Verify(root);
            }
            PlainPath(executable);
            if (File.Exists(executable)) File.Delete(executable);
            Package.WriteBootstrap(Application.ExecutablePath, executable);
            string id = Guid.NewGuid().ToString("N");
            string previousId = File.Exists(Path.Combine(root, IdName)) ? File.ReadAllText(Path.Combine(root, IdName)).Trim() : null;
            UninstallContext context = new UninstallContext { Root = root, Id = previousId ?? id, Version = firstLine.Substring(10),
                Manifest = Path.Combine(root, ManifestName) };
            Dictionary<string, object> payload = (Dictionary<string, object>)Json(Path.Combine(root, "installer", "payload-manifest.json"));
            HashSet<string> names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (object raw in (object[])payload["files"])
            {
                Dictionary<string, object> row = (Dictionary<string, object>)raw;
                string name = Package.EntryPath((string)row["path"]).TrimEnd('/');
                if (Protected(name)) continue;
                Child(root, name);
                if (!names.Add(name)) throw new IOException("The uninstall manifest contains a duplicate path.");
                context.Files.Add(new UninstallFile { Path = name, Hash = (string)row["sha256"], Bytes = Convert.ToInt64(row["bytes"]) });
            }
            foreach (string name in new string[] { "DeepSteam.exe", "Uninstall-DeepSteam.exe", "installer/payload-manifest.json", Program.InstalledMarker })
            {
                string target = Child(root, name);
                context.Files.RemoveAll(delegate(UninstallFile item) { return String.Equals(item.Path, name, StringComparison.OrdinalIgnoreCase); });
                context.Files.Add(new UninstallFile { Path = name, Hash = Sha(target), Bytes = new FileInfo(target).Length });
            }
            string linksPath = Path.Combine(root, "installer", "junctions.json");
            if (File.Exists(linksPath))
            {
                object linksValue = Json(linksPath);
                object[] links = linksValue is object[] ? (object[])linksValue : (object[])((Dictionary<string, object>)linksValue)["junctions"];
                foreach (object raw in links)
                {
                    Dictionary<string, object> row = (Dictionary<string, object>)raw;
                    string path = (string)row["path"], target = (string)row["target"];
                    Child(root, path); Child(root, target);
                    context.Links.Add(new UninstallLink { Path = path, Target = target });
                }
            }
            context.DataRoots.Add(root);
            if (previous != null)
                foreach (string folder in previous.DataRoots)
                    if (!String.Equals(folder, root, StringComparison.OrdinalIgnoreCase)) context.DataRoots.Add(folder);
            Write(context);
            CreateUninstallShortcut(root);
        }
        internal static void AtomicBytes(string path, byte[] bytes)
        {
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            using (FileStream stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
            for (int attempt = 0; ; attempt++)
            {
                try
                {
                    if (File.Exists(path)) File.Replace(temporary, path, null);
                    else File.Move(temporary, path);
                    return;
                }
                catch (IOException) { if (attempt >= 11) throw; Thread.Sleep(50); }
                catch (UnauthorizedAccessException) { if (attempt >= 11) throw; Thread.Sleep(50); }
            }
        }
        internal static string ManifestText(UninstallContext context)
        {
            Root(context.Root);
            StringBuilder data = new StringBuilder("DeepSteamUninstallV1\n");
            data.Append(context.Id).Append('\n').Append(B64(context.Root)).Append('\n').Append(B64(context.Version)).Append('\n');
            foreach (UninstallFile row in context.Files)
                data.Append("F\t").Append(B64(row.Path)).Append('\t').Append(row.Hash).Append('\t').Append(row.Bytes).Append('\n');
            foreach (UninstallLink row in context.Links)
                data.Append("J\t").Append(B64(row.Path)).Append('\t').Append(B64(row.Target)).Append('\n');
            foreach (string folder in context.DataRoots) data.Append("D\t").Append(B64(folder)).Append('\n');
            if (context.WorkspaceSnapshotReady)
            {
                data.Append("S\tworkspaces-v1\n");
                foreach (string folder in context.WorkspaceSnapshot) data.Append("W\t").Append(B64(folder)).Append('\n');
            }
            return data.ToString();
        }
        internal static void Write(UninstallContext context)
        {
            AtomicBytes(context.Manifest, new UTF8Encoding(false).GetBytes(ManifestText(context)));
#if DEEPSTEAM_REVIEW_TEST
            ReviewFaults.AfterWrite("manifest");
#endif
            AtomicBytes(Path.Combine(context.Root, IdName), new UTF8Encoding(false).GetBytes(context.Id));
#if DEEPSTEAM_REVIEW_TEST
            ReviewFaults.AfterWrite("identity");
#endif
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(RegistryName(context.Id)))
            {
                key.SetValue("DisplayName", "DeepSteam 学习助手"); key.SetValue("Publisher", "DeepSteam");
                key.SetValue("DisplayVersion", context.Version); key.SetValue("InstallLocation", context.Root);
                key.SetValue("DisplayIcon", Path.Combine(context.Root, "DeepSteam.exe"));
                key.SetValue("UninstallString", InstallerForm.Quote(Path.Combine(context.Root, "Uninstall-DeepSteam.exe")));
                key.SetValue("InstallationId", context.Id); key.SetValue("ManifestSha256", Sha(context.Manifest));
                key.SetValue("NoModify", 1, RegistryValueKind.DWord); key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }
#if DEEPSTEAM_REVIEW_TEST
            ReviewFaults.AfterWrite("registry");
#endif
        }
        internal static void BindData(string root, string dataRoot)
        {
            UninstallContext context = Verify(root);
            dataRoot = Root(dataRoot);
            if (String.Equals(dataRoot, context.Root, StringComparison.OrdinalIgnoreCase)) return;
            if (Under(dataRoot, context.Root) || Under(context.Root, dataRoot)) throw new IOException("Data and program directories cannot overlap.");
            // A small existing local routing file is authoritative only for
            // binding; it never grants permission to delete by itself.
            string routing = Path.Combine(context.Root, "deepsteam-storage.json"); PlainPath(routing);
            if (!File.Exists(routing) || new FileInfo(routing).Length > 8192) throw new IOException("An external data location was not configured for this installation.");
            Dictionary<string, object> value = (Dictionary<string, object>)Json(routing);
            if (value.Count != 2 || Convert.ToInt32(value["version"]) != 1 || !String.Equals(Root((string)value["state_root"]), dataRoot, StringComparison.OrdinalIgnoreCase))
                throw new IOException("External data settings do not match.");
            if (!Directory.Exists(dataRoot) || !Path.GetFileName(dataRoot).StartsWith("DeepSteam-Data", StringComparison.OrdinalIgnoreCase))
                throw new IOException("Only a dedicated directory explicitly named DeepSteam-Data can be bound. Other directories are preserved.");
            string marker = Path.Combine(dataRoot, ".deepsteam-data-owner"); PlainPath(marker);
            if (File.Exists(marker) && File.ReadAllText(marker).Trim() != context.Id)
            {
                string earlier = File.ReadAllText(marker).Trim();
                if (!Regex.IsMatch(earlier, "^[a-f0-9]{32}$")) throw new IOException("The data ownership marker is invalid. Registration was not changed.");
                using (RegistryKey previousOwner = Registry.CurrentUser.OpenSubKey(RegistryName(earlier)))
                    if (previousOwner != null) throw new IOException("The data still belongs to another installation. Registration was not changed.");
            }
            File.WriteAllText(marker, context.Id, new UTF8Encoding(false));
            if (!context.DataRoots.Exists(delegate(string folder) { return String.Equals(folder, dataRoot, StringComparison.OrdinalIgnoreCase); })) context.DataRoots.Add(dataRoot);
            Write(context);
        }
        internal static UninstallContext Verify(string root)
        {
            root = Root(root);
            string marker = Path.Combine(root, IdName);
            if (!File.Exists(marker) || new FileInfo(marker).Length > 64) throw new IOException("No trusted registration was found for this installation. No files were deleted.");
            PlainPath(marker);
            string id = File.ReadAllText(marker).Trim();
            if (!Regex.IsMatch(id, "^[a-f0-9]{32}$")) throw new IOException("The installation identity is invalid. No files were deleted.");
            string expected;
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RegistryName(id)))
            {
                if (key == null || !String.Equals(key.GetValue("InstallationId") as string, id, StringComparison.Ordinal) ||
                    !String.Equals(key.GetValue("InstallLocation") as string, root, StringComparison.OrdinalIgnoreCase))
                    throw new IOException("The installation directory does not match the Windows registration. No files were deleted.");
                expected = key.GetValue("ManifestSha256") as string;
            }
            return Read(root, id, expected);
        }
        internal static UninstallContext Read(string root, string id, string expected)
        {
            root = Root(root);
            string file = Path.Combine(root, ManifestName);
            PlainPath(file);
            if (!File.Exists(file) || new FileInfo(file).Length > 64 * 1024 * 1024 || !Regex.IsMatch(expected ?? "", "^[a-f0-9]{64}$") || Sha(file) != expected)
                throw new IOException("The uninstall manifest was modified or is incomplete. No files were deleted.");
            string[] lines = File.ReadAllLines(file, Encoding.UTF8);
            if (lines.Length < 5 || lines[0] != "DeepSteamUninstallV1" || lines[1] != id ||
                !String.Equals(UnB64(lines[2]), root, StringComparison.OrdinalIgnoreCase)) throw new IOException("Uninstall identity verification failed.");
            UninstallContext context = new UninstallContext { Root = root, Id = id, Version = UnB64(lines[3]), Manifest = file };
            HashSet<string> names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (int index = 4; index < lines.Length; index++)
            {
                if (lines[index].Length == 0) continue;
                string[] row = lines[index].Split('\t');
                if (row[0] == "F" && row.Length == 4)
                {
                    string path = UnB64(row[1]); Child(root, path);
                    if (!names.Add(path) || Protected(path) || !Regex.IsMatch(row[2], "^[a-f0-9]{64}$")) throw new IOException("The uninstall file manifest is unsafe.");
                    long length; if (!Int64.TryParse(row[3], out length) || length < 0) throw new IOException("An uninstall file length is invalid.");
                    context.Files.Add(new UninstallFile { Path = path, Hash = row[2], Bytes = length });
                }
                else if (row[0] == "J" && row.Length == 3)
                {
                    string path = UnB64(row[1]), target = UnB64(row[2]); Child(root, path); Child(root, target);
                    if (!names.Add(path)) throw new IOException("The uninstall link manifest contains a duplicate entry.");
                    context.Links.Add(new UninstallLink { Path = path, Target = target });
                }
                else if (row[0] == "D" && row.Length == 2)
                {
                    string target = Root(UnB64(row[1]));
                    if (!String.Equals(target, root, StringComparison.OrdinalIgnoreCase) && (Under(target, root) || Under(root, target)))
                        throw new IOException("The external data directory cannot overlap the program directory.");
                    context.DataRoots.Add(target);
                }
                else if (row[0] == "S" && row.Length == 2 && row[1] == "workspaces-v1" && !context.WorkspaceSnapshotReady)
                    context.WorkspaceSnapshotReady = true;
                else if (row[0] == "W" && row.Length == 2 && context.WorkspaceSnapshotReady)
                {
                    string folder = UnB64(row[1]);
                    if (!Path.IsPathRooted(folder)) throw new IOException("The workspace protection snapshot contains an invalid path.");
                    context.WorkspaceSnapshot.Add(Path.GetFullPath(folder).TrimEnd('\\'));
                }
                else throw new IOException("The uninstall manifest format is invalid.");
            }
            if (!context.Files.Exists(delegate(UninstallFile row) { return row.Path == Program.InstalledMarker; }) ||
                !context.Files.Exists(delegate(UninstallFile row) { return row.Path == "Uninstall-DeepSteam.exe"; }) || context.DataRoots.Count == 0)
                throw new IOException("The uninstall manifest lacks the installation identity or program entry.");
            string installed = Path.Combine(root, Program.InstalledMarker);
            UninstallFile installedRow = context.Files.Find(delegate(UninstallFile row) { return row.Path == Program.InstalledMarker; });
            PlainPath(installed);
            if (!File.Exists(installed) || Sha(installed) != installedRow.Hash || !File.ReadAllText(installed).StartsWith("DeepSteam " + context.Version + "\r\n", StringComparison.Ordinal))
                throw new IOException("Installation completion verification failed. No files were deleted.");
            return context;
        }
        internal static void CreateUninstallShortcut(string root)
        {
            string idFile = Path.Combine(root, IdName);
            if (!File.Exists(idFile)) return;
            string id = File.ReadAllText(idFile).Trim();
            if (!Regex.IsMatch(id, "^[a-f0-9]{32}$")) throw new IOException("Cannot create an uninstall entry for an unknown installation.");
            string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "DeepSteam-" + id.Substring(0, 8));
            PlainPath(folder); Directory.CreateDirectory(folder);
            object shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            object link = null;
            try
            {
                string destination = Path.Combine(folder, "Uninstall DeepSteam.lnk");
                PlainPath(destination);
                link = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { destination });
                Type type = link.GetType();
                if (File.Exists(destination))
                {
                    string existing = (string)type.InvokeMember("TargetPath", BindingFlags.GetProperty, null, link, null);
                    if (!String.Equals(existing, Path.Combine(root, "Uninstall-DeepSteam.exe"), StringComparison.OrdinalIgnoreCase))
                        throw new IOException("The Start menu uninstall entry points to another program. The entry was preserved.");
                }
                type.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { Path.Combine(root, "Uninstall-DeepSteam.exe") });
                type.InvokeMember("Arguments", BindingFlags.SetProperty, null, link, new object[] { "" });
                type.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { root });
                type.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "Uninstall DeepSteam; preserve learning records and user workspaces by default" });
                type.InvokeMember("IconLocation", BindingFlags.SetProperty, null, link, new object[] { Path.Combine(root, "Uninstall-DeepSteam.ico") + ",0" });
                type.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
            }
            finally
            {
                if (link != null && Marshal.IsComObject(link)) Marshal.FinalReleaseComObject(link);
                if (Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell);
            }
        }
    }

    // Incremental updates preserve the earlier HKCU-anchored ownership list.
    // The updater never scans the installation to adopt arbitrary user files.
    internal static class UninstallUpgrade
    {
        // Exact immutable SDK source locations contain words also used by private
        // state folders. This exception permits code files only, never tokens,
        // accounts or configuration, and the receipt SHA remains mandatory.
        private static bool FactorySdkCode(string value)
        {
            string sdk = "runtime/harness/node_modules/@anthropic-ai/sdk/";
            string[] credentialNames = { "credential-chain", "identity-token", "oidc-federation", "token-cache", "types", "user-oauth" };
            string[] workspaceNames = { "index", "members", "rate-limits", "service-accounts", "workspaces" };
            string[] prefixes = { "lib/credentials/", "resources/beta/organization/workspaces/", "src/lib/credentials/", "src/resources/beta/organization/workspaces/" };
            string[] compiledSuffixes = { ".js", ".js.map", ".mjs", ".mjs.map", ".d.ts", ".d.ts.map", ".d.mts", ".d.mts.map" };
            for (int index = 0; index < prefixes.Length; index++)
            {
                string prefix = sdk + prefixes[index];
                if (!value.StartsWith(prefix, StringComparison.Ordinal)) continue;
                string leaf = value.Substring(prefix.Length);
                string[] names = (index == 0 || index == 2) ? credentialNames : workspaceNames;
                string[] suffixes = index >= 2 ? new string[] { ".ts" } : compiledSuffixes;
                foreach (string name in names)
                    foreach (string suffix in suffixes)
                        if (leaf == name + suffix) return true;
                return false;
            }
            return false;
        }
        private static bool FactoryMineruModel(string value)
        {
            string prefix = "models/mineru/";
            if (!value.StartsWith(prefix, StringComparison.Ordinal)) return false;
            string leaf = value.Substring(prefix.Length);
            foreach (string model in new string[] {
                "mineru-4_models_onnx/layout/pp-doclayoutv2/inference.onnx", "mineru-4_models_onnx/layout/pp-doclayoutv2/inference.yml",
                "mineru-4_models_onnx/mfr/pp_formulanet_plus_m/pp-formulanet_plus-m.onnx", "mineru-4_models_onnx/mfr/pp_formulanet_plus_m/pp-formulanet_plus-m_inference.yml",
                "mineru-4_models_onnx/ocr/paddleocr/ch_pp-ocrv6_small_rec_infer.onnx", "mineru-4_models_onnx/ocr/paddleocr/ch_pp-ocrv6_small_rec_inference.yml",
                "mineru-4_models_onnx/ocr/paddleocr/ch_pp-ocrv6_tiny_det_infer.onnx", "mineru-4_models_onnx/ocr/paddleocr/ch_pp-ocrv6_tiny_det_inference.yml",
                "mineru-4_models_onnx/ocr/paddleocr/seal_pp-ocrv4_det_infer.onnx", "mineru-4_models_onnx/ocr/paddleocr/seal_pp-ocrv4_det_inference.yml",
                "mineru-4_models_onnx/readme.md", "mineru-4_models_onnx/table/pp-lcnet_x1_0_table_cls.onnx", "mineru-4_models_onnx/table/slanet-plus.onnx",
                "mineru-4_models_onnx/table/unet.onnx", "mineru-4_models_onnx/manifest.json",
                "mineru2.5-pro-2605-1.2b-gguf/.mineru_complete", "mineru2.5-pro-2605-1.2b-gguf/mineru2.5-pro-2605-1.2b-q8_0.gguf",
                "mineru2.5-pro-2605-1.2b-gguf/mmproj-mineru2.5-pro-2605-1.2b-q8_0.gguf", "runtime-models.json" })
                if (leaf == model) return true;
            return false;
        }
        internal static bool PublicProgramPath(string path)
        {
            string value = Package.EntryPath(path).TrimEnd('/').ToLowerInvariant();
            if (UninstallRegistration.Protected(value)) return false;
            if (value == "deepsteam.exe" || value == "uninstall-deepsteam.exe" || value.StartsWith(".deepsteam-")) return false;
            bool factorySdkCode = FactorySdkCode(value);
            foreach (string segment in value.Split('/'))
                if (segment == ".env" || segment.StartsWith(".env.") || (segment == "credentials" && !factorySdkCode) || segment == "secrets" ||
                    segment == "auth.json" || segment == "tokens.json" || segment == "account.json" || segment == "accounts.json" ||
                    (segment == "workspaces" && !factorySdkCode) || segment == "user-data" || segment == "userdata" || segment == "session-store") return false;
            bool publicCaBundle = value == "runtime/mineru/lib/site-packages/certifi/cacert.pem";
            if (value.EndsWith(".sqlite") || value.EndsWith(".db") || (value.EndsWith(".pem") && !publicCaBundle) || value.EndsWith(".key")) return false;
            if (FactoryMineruModel(value)) return true;
            foreach (string file in new string[] { "main.cjs", "preload.cjs", "bilibili.cjs", "policy.cjs", "transport.cjs", "storage-migration.cjs", "oauth-placeholder.cjs", "starting.html", "package.json" })
                if (value == "desktop/" + file) return true;
            foreach (string prefix in new string[] { "portal/", "integration/", "scripts/", "installer/", "licenses/", "upstream/",
                "runtime/python/", "runtime/deeptutor-packages/", "runtime/native-frontends/", "runtime/openmaic-standalone/",
                "runtime/desktop/", "runtime/harness/", "runtime/node/", "runtime/mineru/", "runtime/pglite/", "runtime/render-service/", "demo/" })
                if (value.StartsWith(prefix, StringComparison.Ordinal)) return true;
            return value == "release.md" || value == "release-identity.json" || value == "local-build-info.json" || value == "guide.md" || value == "user-guide.txt" || value == "agents.md" || value == "package-manifest.json" || value == "public-source-manifest.json" || value == "requirements-demo.txt" || value == "runtime/native-frontend.json" || value == "runtime/openmaic-frontend.json" ||
                value == "runtime/harness-runtime.json" || value == "readme.md" || value == "requirements.txt" ||
                value == "pyproject.toml" || value == "notice.md" || value == "license";
        }
        internal static string Serialize(object value)
        {
            Assembly assembly = Assembly.Load("System.Web.Extensions, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35");
            Type type = assembly.GetType("System.Web.Script.Serialization.JavaScriptSerializer", true);
            object serializer = Activator.CreateInstance(type);
            type.GetProperty("MaxJsonLength").SetValue(serializer, 64 * 1024 * 1024, null);
            return (string)type.GetMethod("Serialize", new Type[] { typeof(object) }).Invoke(serializer, new object[] { value });
        }
        internal static void Report(string path, object value, string root)
        {
            string full = Path.GetFullPath(path);
            if (!Path.IsPathRooted(path) || !full.EndsWith(".json", StringComparison.OrdinalIgnoreCase) || UninstallRegistration.Under(full, root))
                throw new IOException("Write the verification report to an explicit JSON file outside the program directory.");
            UninstallRegistration.PlainPath(full);
            File.WriteAllText(full, Serialize(value), new UTF8Encoding(false));
        }
        internal static string Shortcut(UninstallContext context)
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "DeepSteam-" + context.Id.Substring(0, 8), "Uninstall DeepSteam.lnk");
        }
        internal static void Check(string root, string report)
        {
            UninstallContext context = UninstallRegistration.Verify(root);
            VerifyBootstrap(context);
            foreach (string relative in new string[] { "DeepSteam.exe", "Uninstall-DeepSteam.exe" })
            {
                UninstallFile row = context.Files.Find(delegate(UninstallFile item) { return String.Equals(item.Path, relative, StringComparison.OrdinalIgnoreCase); });
                string file = UninstallRegistration.Child(context.Root, relative);
                if (row == null || !File.Exists(file) || new FileInfo(file).Length != row.Bytes || UninstallRegistration.Sha(file) != row.Hash)
                    throw new IOException("The uninstall entry does not match its registration. Uninstallation was not performed.");
            }
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(UninstallRegistration.RegistryName(context.Id)))
                if ((string)key.GetValue("DisplayVersion") != context.Version ||
                    (string)key.GetValue("UninstallString") != InstallerForm.Quote(Path.Combine(context.Root, "Uninstall-DeepSteam.exe")))
                    throw new IOException("The Windows uninstall entry or version is out of sync.");
            string shortcut = Shortcut(context); UninstallRegistration.PlainPath(shortcut);
            if (!File.Exists(shortcut)) throw new IOException("The Start menu uninstall entry is missing.");
            object shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell")); object link = null;
            try
            {
                link = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { shortcut });
                Type type = link.GetType();
                string target = (string)type.InvokeMember("TargetPath", BindingFlags.GetProperty, null, link, null);
                string arguments = (string)type.InvokeMember("Arguments", BindingFlags.GetProperty, null, link, null);
                if (!String.Equals(target, Path.Combine(context.Root, "Uninstall-DeepSteam.exe"), StringComparison.OrdinalIgnoreCase) || arguments != "")
                    throw new IOException("The Start menu uninstall entry points to the wrong destination.");
            }
            finally
            {
                if (link != null && Marshal.IsComObject(link)) Marshal.FinalReleaseComObject(link);
                if (Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell);
            }
            Report(report, new { passed = true, version = context.Version, root = context.Root, installation_id = context.Id,
                registered_files = context.Files.Count, registered_links = context.Links.Count, data_roots = context.DataRoots.Count,
                shortcut = shortcut, defaults_preserve_data = true, program_files_deleted = 0, data_files_deleted = 0,
                services_stopped = false, real_model_calls = 0 }, context.Root);
        }
        internal static void VerifyBootstrap(UninstallContext context)
        {
            string file = UninstallRegistration.Child(context.Root, "Uninstall-DeepSteam.exe");
            UninstallRegistration.PlainPath(file);
            UninstallFile row = context.Files.Find(delegate(UninstallFile item) { return item.Path == "Uninstall-DeepSteam.exe"; });
            if (!File.Exists(file) || new FileInfo(file).Length > 4 * 1024 * 1024)
                throw new IOException("旧版卸载组件的打包格式不正确，请先更新 DeepSteam。");
            if (row == null || new FileInfo(file).Length != row.Bytes || UninstallRegistration.Sha(file) != row.Hash)
                throw new IOException("卸载组件与安装记录不一致，请修复或更新 DeepSteam。");
        }
        internal static void Refresh(string root, string receiptPath, string receiptHash, string report, bool dryRun)
        {
            if (!dryRun) RecoverRefresh(root, receiptPath, receiptHash);
            UninstallContext previous = UninstallRegistration.Verify(root); root = previous.Root;
            if (!Regex.IsMatch(receiptHash ?? "", "^[a-f0-9]{64}$") || UninstallRegistration.Sha(receiptPath) != receiptHash)
                throw new IOException("Update receipt verification failed. The uninstall manifest was not expanded.");
            Dictionary<string, object> receipt = (Dictionary<string, object>)UninstallRegistration.Json(receiptPath);
            string kind = receipt["kind"] as string;
            bool repairEntriesOnly = kind == "deepsteam-uninstall-repair-entries-v1";
            if ((!repairEntriesOnly && kind != "deepsteam-uninstall-update-v1") ||
                !String.Equals(UninstallRegistration.Root((string)receipt["root"]), root, StringComparison.OrdinalIgnoreCase) ||
                (string)receipt["installation_id"] != previous.Id ||
                (string)receipt["previous_manifest_sha256"] != UninstallRegistration.Sha(previous.Manifest) ||
                (string)receipt["target_version"] != Program.Version ||
                (string)receipt["updater_sha256"] != UninstallRegistration.Sha(Application.ExecutablePath))
                throw new IOException("The update receipt does not match this installation, version, or updater.");
            if (UninstallRegistration.Under(Application.ExecutablePath, root) || new FileInfo(Application.ExecutablePath).Length > 4 * 1024 * 1024)
                throw new IOException("Use a verified small updater outside the program directory.");
            // Snapshot the receipt bytes as well as its caller-pinned digest;
            // any changed input during validation aborts before mutation.
            UninstallContext next = new UninstallContext { Root = root, Id = previous.Id, Version = Program.Version, Manifest = previous.Manifest };
            Dictionary<string, UninstallFile> files = new Dictionary<string, UninstallFile>(StringComparer.OrdinalIgnoreCase);
            foreach (UninstallFile row in previous.Files) files.Add(row.Path, row);
            HashSet<string> additions = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (repairEntriesOnly) ValidateEntryRepair(previous, receipt);
            foreach (object raw in (object[])receipt["files"])
            {
                Dictionary<string, object> row = (Dictionary<string, object>)raw;
                string name = Package.EntryPath((string)row["path"]).TrimEnd('/'), hash = (string)row["sha256"];
                long bytes = Convert.ToInt64(row["bytes"]);
                if (!PublicProgramPath(name) || !additions.Add(name) || bytes < 0 || !Regex.IsMatch(hash ?? "", "^[a-f0-9]{64}$"))
                    throw new IOException("The update receipt contains a duplicate, data, credential, or non-program path.");
                string file = UninstallRegistration.Child(root, name); UninstallRegistration.PlainPath(file);
                if (!File.Exists(Package.Extended(file)) || new FileInfo(Package.Extended(file)).Length != bytes || UninstallRegistration.Sha(file) != hash)
                    throw new IOException("The deployed program does not match the update receipt: " + name);
                files[name] = new UninstallFile { Path = name, Hash = hash, Bytes = bytes };
            }
            if (!repairEntriesOnly && additions.Count == 0) throw new IOException("An empty update manifest cannot be used to register again.");
            foreach (UninstallFile row in files.Values) next.Files.Add(row);
            next.Links.AddRange(previous.Links); next.DataRoots.AddRange(previous.DataRoots);
            object requestedLinks;
            if (receipt.TryGetValue("links", out requestedLinks))
            {
                object[] values = requestedLinks as object[];
                if (values == null || repairEntriesOnly && values.Length != 0)
                    throw new IOException("Dependency links require a program-only update receipt.");
                HashSet<string> names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (object raw in values)
                {
                    Dictionary<string, object> row = raw as Dictionary<string, object>;
                    if (row == null || row.Count != 2 || !row.ContainsKey("path") || !row.ContainsKey("target"))
                        throw new IOException("Invalid dependency-link record.");
                    string name = Package.EntryPath((string)row["path"]).TrimEnd('/');
                    string target = Package.EntryPath((string)row["target"]).TrimEnd('/');
                    if (!PublicProgramPath(name) || !PublicProgramPath(target) || !names.Add(name) || files.ContainsKey(name) ||
                        !name.StartsWith("runtime/openmaic-standalone/node_modules/", StringComparison.Ordinal) ||
                        !target.StartsWith("runtime/openmaic-standalone/", StringComparison.Ordinal) ||
                        !files.ContainsKey(target + "/package.json"))
                        throw new IOException("Dependency link is outside the reviewed packaged program.");
                    VerifyProgramLink(root, name, target);
                    UninstallLink existing = next.Links.Find(delegate(UninstallLink item) { return String.Equals(item.Path, name, StringComparison.OrdinalIgnoreCase); });
                    if (existing != null && !String.Equals(existing.Target, target, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("An existing dependency link cannot be redirected by this update.");
                    if (existing == null) next.Links.Add(new UninstallLink { Path = name, Target = target });
                }
            }
            next.WorkspaceSnapshotReady = previous.WorkspaceSnapshotReady;
            next.WorkspaceSnapshot.AddRange(previous.WorkspaceSnapshot);
            // No on-disk backup of the installation or learning data is made.
            // Only four small program metadata/binary objects are held in memory
            // while committing the version and inventory together.
            string[] ownNames = new string[] { "DeepSteam.exe", "Uninstall-DeepSteam.exe", Program.InstalledMarker };
            Dictionary<string, byte[]> originals = new Dictionary<string, byte[]>();
            foreach (string relative in ownNames)
            {
                string file = UninstallRegistration.Child(root, relative); UninstallRegistration.PlainPath(file);
                if (!File.Exists(file) || new FileInfo(file).Length > 4 * 1024 * 1024) throw new IOException("The program entry is missing or has an unexpected size.");
                originals.Add(relative, File.ReadAllBytes(file));
            }
            Report(report, new { passed = true, dry_run = dryRun, previous_version = previous.Version, version = next.Version,
                root = root, installation_id = previous.Id, prior_files = previous.Files.Count, reviewed_update_files = additions.Count,
                repair_entries_only = repairEntriesOnly,
                merged_files = next.Files.Count, retained_data_roots = next.DataRoots.Count, directory_scan_used = false, applied = false,
                data_files_changed = 0, services_stopped = false, real_model_calls = 0 }, root);
            if (dryRun) return;
            if (UninstallRegistration.Sha(receiptPath) != receiptHash || UninstallRegistration.Sha(previous.Manifest) != (string)receipt["previous_manifest_sha256"])
                throw new IOException("Update inputs changed during verification. Registration was not updated.");
            if (repairEntriesOnly) ValidateEntryRepair(previous, receipt);
            byte[] markerBytes = new UTF8Encoding(false).GetBytes("DeepSteam " + next.Version + "\r\n" + DateTime.UtcNow.ToString("o"));
            byte[] updaterBytes = File.ReadAllBytes(Application.ExecutablePath);
            foreach (string relative in ownNames)
            {
                byte[] bytes = relative == Program.InstalledMarker ? markerBytes : updaterBytes;
                next.Files.RemoveAll(delegate(UninstallFile row) { return String.Equals(row.Path, relative, StringComparison.OrdinalIgnoreCase); });
                next.Files.Add(new UninstallFile { Path = relative, Hash = BytesHash(bytes), Bytes = bytes.Length });
            }
            List<object> journalFiles = new List<object>();
            foreach (string relative in ownNames)
                journalFiles.Add(new { path = relative, before = Convert.ToBase64String(originals[relative]), before_sha = BytesHash(originals[relative]),
                    after_sha = BytesHash(relative == Program.InstalledMarker ? markerBytes : updaterBytes) });
            byte[] oldManifest = File.ReadAllBytes(previous.Manifest);
            journalFiles.Add(new { path = UninstallRegistration.ManifestName, before = Convert.ToBase64String(oldManifest), before_sha = BytesHash(oldManifest),
                after_sha = BytesHash(new UTF8Encoding(false).GetBytes(UninstallRegistration.ManifestText(next))) });
            string journalPath = receiptPath + ".ownership-journal.json";
            Dictionary<string, object> journal = new Dictionary<string, object> {
                { "root", root }, { "id", previous.Id }, { "receipt_sha256", receiptHash },
                { "updater_sha256", BytesHash(updaterBytes) }, { "status", "prepared" }, { "files", journalFiles.ToArray() } };
            UninstallRegistration.AtomicBytes(journalPath, new UTF8Encoding(false).GetBytes(Serialize(journal)));
            try
            {
                foreach (string relative in ownNames)
                {
                    string file = UninstallRegistration.Child(root, relative);
                    if (relative == Program.InstalledMarker)
                        UninstallRegistration.AtomicBytes(file, markerBytes);
                    else UninstallRegistration.AtomicBytes(file, updaterBytes);
#if DEEPSTEAM_REVIEW_TEST
                    ReviewFaults.AfterWrite(relative);
#endif
                    next.Files.RemoveAll(delegate(UninstallFile row) { return String.Equals(row.Path, relative, StringComparison.OrdinalIgnoreCase); });
                    next.Files.Add(new UninstallFile { Path = relative, Hash = UninstallRegistration.Sha(file), Bytes = new FileInfo(file).Length });
                }
                UninstallRegistration.Write(next);
                UninstallRegistration.CreateUninstallShortcut(root);
                Check(root, report);
                journal["status"] = "committed";
                UninstallRegistration.AtomicBytes(journalPath, new UTF8Encoding(false).GetBytes(Serialize(journal)));
            }
            catch
            {
                foreach (KeyValuePair<string, byte[]> item in originals)
                    UninstallRegistration.AtomicBytes(UninstallRegistration.Child(root, item.Key), item.Value);
                UninstallRegistration.Write(previous);
                journal["status"] = "rolled_back";
                UninstallRegistration.AtomicBytes(journalPath, new UTF8Encoding(false).GetBytes(Serialize(journal)));
                throw;
            }
        }
        private static string BytesHash(byte[] bytes)
        {
            using (SHA256 sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }
        private static void RecoverRefresh(string root, string receiptPath, string receiptHash)
        {
            string journalPath = receiptPath + ".ownership-journal.json";
            if (!File.Exists(journalPath)) return;
            Dictionary<string, object> journal = (Dictionary<string, object>)UninstallRegistration.Json(journalPath);
            if ((string)journal["status"] != "prepared") return;
            root = UninstallRegistration.Root(root);
            if (!String.Equals((string)journal["root"], root, StringComparison.OrdinalIgnoreCase) ||
                (string)journal["receipt_sha256"] != receiptHash || UninstallRegistration.Sha(receiptPath) != receiptHash ||
                (string)journal["updater_sha256"] != UninstallRegistration.Sha(Application.ExecutablePath))
                throw new IOException("Pending ownership transaction does not match this updater and receipt.");
            HashSet<string> allowed = new HashSet<string>(new string[] { "DeepSteam.exe", "Uninstall-DeepSteam.exe", Program.InstalledMarker, UninstallRegistration.ManifestName });
            object[] files = (object[])journal["files"];
            if (files.Length != allowed.Count) throw new IOException("Invalid ownership recovery inventory.");
            foreach (object raw in files)
            {
                Dictionary<string, object> row = (Dictionary<string, object>)raw;
                string name = (string)row["path"];
                if (!allowed.Remove(name) || BytesHash(Convert.FromBase64String((string)row["before"])) != (string)row["before_sha"])
                    throw new IOException("Ownership recovery bytes failed validation.");
                string path = UninstallRegistration.Child(root, name); UninstallRegistration.PlainPath(path);
                string hash = UninstallRegistration.Sha(path);
                if (hash != (string)row["before_sha"] && hash != (string)row["after_sha"])
                    throw new IOException("An unrelated edit prevents ownership recovery: " + name);
            }
            foreach (object raw in files)
            {
                Dictionary<string, object> row = (Dictionary<string, object>)raw;
                UninstallRegistration.AtomicBytes(UninstallRegistration.Child(root, (string)row["path"]), Convert.FromBase64String((string)row["before"]));
            }
            UninstallContext previous = UninstallRegistration.Read(root, (string)journal["id"], UninstallRegistration.Sha(Path.Combine(root, UninstallRegistration.ManifestName)));
            UninstallRegistration.Write(previous);
            journal["status"] = "rolled_back";
            UninstallRegistration.AtomicBytes(journalPath, new UTF8Encoding(false).GetBytes(Serialize(journal)));
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "CreateFileW")]
        private static extern SafeFileHandle OpenLinkDirectory(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "GetFinalPathNameByHandleW")]
        private static extern uint FinalLinkDirectory(SafeFileHandle handle, StringBuilder path, uint size, uint flags);
        private static void VerifyProgramLink(string root, string name, string target)
        {
            string link = UninstallRegistration.Child(root, name), expected = UninstallRegistration.Child(root, target);
            UninstallRegistration.PlainPath(Path.GetDirectoryName(link));
            UninstallRegistration.PlainPath(expected);
            if (!Directory.Exists(expected) || !Directory.Exists(link) ||
                (File.GetAttributes(Package.Extended(link)) & FileAttributes.ReparsePoint) == 0)
                throw new IOException("A reviewed packaged dependency link is missing.");
            using (SafeFileHandle handle = OpenLinkDirectory(Package.Extended(link), 0, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero))
            {
                if (handle.IsInvalid) throw new IOException("A dependency link could not be verified.");
                StringBuilder resolved = new StringBuilder(32768);
                uint count = FinalLinkDirectory(handle, resolved, (uint)resolved.Capacity, 0);
                if (count == 0 || count >= resolved.Capacity) throw new IOException("A dependency link could not be resolved.");
                string final = resolved.ToString();
                if (final.StartsWith(@"\\?\", StringComparison.Ordinal)) final = final.Substring(4);
                if (!String.Equals(final.TrimEnd('\\'), expected.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
                    throw new IOException("A dependency link points outside its reviewed target.");
            }
        }
        private static void ValidateEntryRepair(UninstallContext previous, Dictionary<string, object> receipt)
        {
            // This separate receipt repairs surviving entry points after a
            // late interrupted uninstall. It cannot add program ownership,
            // recreate missing entries, or authorize any user/data file.
            object rawFiles, rawEntries;
            if (!receipt.TryGetValue("files", out rawFiles) || !(rawFiles is object[]) || ((object[])rawFiles).Length != 0 ||
                !receipt.TryGetValue("entries", out rawEntries) || !(rawEntries is object[]) || ((object[])rawEntries).Length != 2)
                throw new IOException("An entry-repair receipt must contain only the two original entries and no additional program files.");
            HashSet<string> names = new HashSet<string>(StringComparer.Ordinal);
            foreach (object raw in (object[])rawEntries)
            {
                Dictionary<string, object> row = raw as Dictionary<string, object>;
                if (row == null || row.Count != 3 || !row.ContainsKey("path") || !row.ContainsKey("sha256") || !row.ContainsKey("bytes"))
                    throw new IOException("An entry-repair record has an invalid format.");
                string name = row["path"] as string, hash = row["sha256"] as string;
                if ((name != "DeepSteam.exe" && name != "Uninstall-DeepSteam.exe") || !names.Add(name))
                    throw new IOException("Entry repair can only verify the two distinct, explicit original entries.");
                long bytes = Convert.ToInt64(row["bytes"]);
                UninstallFile owned = previous.Files.Find(delegate(UninstallFile file) { return file.Path == name; });
                if (owned == null || owned.Hash != hash || owned.Bytes != bytes || bytes <= 0 || bytes > 4 * 1024 * 1024)
                    throw new IOException("The entry-repair receipt does not match the previous trusted ownership.");
                string path = UninstallRegistration.Child(previous.Root, name); UninstallRegistration.PlainPath(path);
                if (new FileInfo(Package.Extended(path)).Length != bytes || UninstallRegistration.Sha(path) != hash)
                    throw new IOException("The previous entry is missing or changed. The file was not overwritten: " + name);
            }
        }
    }

    internal sealed class UninstallWindowLease : IDisposable
    {
        private readonly Mutex mutex;
        private EventWaitHandle activate;
        private RegisteredWaitHandle waiter;
        internal readonly bool Owner;
        internal UninstallWindowLease(string id)
        {
            if (!Regex.IsMatch(id ?? "", "^[a-f0-9]{32}$")) throw new IOException("The uninstall window identity is invalid.");
            string prefix = @"Local\DeepSteam-Uninstall-" + id;
            mutex = new Mutex(false, prefix);
            try { Owner = mutex.WaitOne(0); }
            catch (AbandonedMutexException) { Owner = true; }
            if (Owner) activate = new EventWaitHandle(false, EventResetMode.AutoReset, prefix + "-Activate");
            else
            {
                try { using (EventWaitHandle existing = EventWaitHandle.OpenExisting(prefix + "-Activate")) existing.Set(); }
                catch (WaitHandleCannotBeOpenedException) { } // Owner is still opening its window.
            }
        }
        internal void Attach(Form form)
        {
            if (!Owner) throw new InvalidOperationException("Only the owning worker may attach its window.");
            waiter = ThreadPool.RegisterWaitForSingleObject(activate, delegate(object state, bool timeout)
            {
                if (form.IsDisposed || !form.IsHandleCreated) return;
                try { form.BeginInvoke(new Action(delegate {
                    if (form.IsDisposed) return;
                    if (form.WindowState == FormWindowState.Minimized) form.WindowState = FormWindowState.Normal;
                    form.Show(); form.Activate(); form.BringToFront();
                })); }
                catch (InvalidOperationException) { }
            }, null, Timeout.Infinite, false);
        }
        public void Dispose()
        {
            if (waiter != null) waiter.Unregister(null);
            if (activate != null) activate.Dispose();
            if (Owner) mutex.ReleaseMutex();
            mutex.Dispose();
        }
    }

    internal static class Uninstaller
    {
        internal static bool IsUninstaller(string path) { return String.Equals(Path.GetFileName(path), "Uninstall-DeepSteam.exe", StringComparison.OrdinalIgnoreCase); }
        internal static int Open(string[] args)
        {
            try
            {
                bool worker = args.Length == 3 && args[0] == "--uninstall-worker";
                string root = worker ? args[1] : Path.GetDirectoryName(Application.ExecutablePath);
                UninstallContext context = UninstallRegistration.Verify(root);
                if (worker && args[2] != context.Id) throw new IOException("The uninstall worker identity is invalid.");
                if (!worker)
                {
                    string temporary = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Temp", "DeepSteam-Uninstall", Guid.NewGuid().ToString("N"));
                    UninstallRegistration.Root(temporary);
                    if (UninstallRegistration.Under(temporary, root)) throw new IOException("The temporary uninstall directory cannot be inside the program directory.");
                    Directory.CreateDirectory(temporary);
                    string copy = Path.Combine(temporary, "Uninstall-DeepSteam.exe");
                    string source = Path.Combine(root, "Uninstall-DeepSteam.exe");
                    UninstallUpgrade.VerifyBootstrap(context);
                    File.Copy(source, copy, false);
                    Process.Start(new ProcessStartInfo { FileName = copy, Arguments = "--uninstall-worker " + InstallerForm.Quote(root) + " " + context.Id,
                        WorkingDirectory = temporary, UseShellExecute = false });
                    return 0;
                }
                // The temporary worker owns singleton lifetime; its installed
                // bootstrap deliberately exits so it never locks removal.
                using (UninstallWindowLease lease = new UninstallWindowLease(context.Id))
                {
                    if (lease.Owner)
                    {
                        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                        using (UninstallForm form = new UninstallForm(context))
                        {
                            form.Shown += delegate { lease.Attach(form); };
                            Application.Run(form);
                        }
                    }
                }
                ScheduleTemporaryCleanup();
                return 0;
            }
            catch (Exception ex) { SetupDialog.ShowWarning(null, ex.Message, "DeepSteam 卸载尚未完成"); return 1; }
        }
        private static void ScheduleTemporaryCleanup()
        {
            // Small temporary bootstrap files only. This helper never traverses
            // the installation or data directory, and uses one native shell.
            string executable = Application.ExecutablePath;
            string folder = Path.GetDirectoryName(executable);
            string expectedParent = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Temp", "DeepSteam-Uninstall");
            if (!String.Equals(Path.GetDirectoryName(folder), expectedParent, StringComparison.OrdinalIgnoreCase) || !Regex.IsMatch(Path.GetFileName(folder), "^[a-f0-9]{32}$")) return;
            UninstallRegistration.Root(folder);
            string helper = Path.Combine(folder, "cleanup.ps1");
            string script = "$ErrorActionPreference = 'Stop'\r\n" +
                "$taskFolder = '" + folder.Replace("'", "''") + "'\r\n" +
                "$taskExecutable = '" + executable.Replace("'", "''") + "'\r\n" +
                "$taskSelf = '" + helper.Replace("'", "''") + "'\r\n" +
                "$taskPid = " + Process.GetCurrentProcess().Id + "\r\n" +
                "$taskCreated = '" + Process.GetCurrentProcess().StartTime.ToUniversalTime().ToString("o") + "'\r\n" +
                "if ([IO.Path]::GetFullPath($taskExecutable) -ne (Join-Path $taskFolder 'Uninstall-DeepSteam.exe')) { exit 1 }\r\n" +
                "if ([IO.Path]::GetFullPath($taskSelf) -ne (Join-Path $taskFolder 'cleanup.ps1')) { exit 1 }\r\n" +
                "$taskParent = Get-Item -LiteralPath $taskFolder\r\n" +
                "if (($taskParent.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { exit 1 }\r\n" +
                "$taskAncestor = $taskParent\r\n" +
                "while ($taskAncestor) { if (($taskAncestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { exit 1 }; $taskAncestor = $taskAncestor.Parent }\r\n" +
                "$taskProcess = Get-Process -Id $taskPid -ErrorAction SilentlyContinue\r\n" +
                "if ($taskProcess -and $taskProcess.StartTime.ToUniversalTime().ToString('o') -eq $taskCreated) { $taskProcess.WaitForExit() }\r\n" +
                "foreach ($taskFile in @($taskExecutable, $taskSelf)) {\r\n" +
                "  if (Test-Path -LiteralPath $taskFile) { $taskItem = Get-Item -LiteralPath $taskFile; if (($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { exit 1 }; Remove-Item -LiteralPath $taskFile -Force }\r\n" +
                "}\r\n" +
                "if ((Get-ChildItem -LiteralPath $taskFolder -Force | Measure-Object).Count -eq 0) { Remove-Item -LiteralPath $taskFolder }\r\n";
            File.WriteAllText(helper, script, new UTF8Encoding(true));
            Process.Start(new ProcessStartInfo { FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe"),
                Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + InstallerForm.Quote(helper),
                WorkingDirectory = expectedParent, UseShellExecute = false, CreateNoWindow = true });
        }
    }

    // A progress event describes observed work, never a timer-generated percentage.
    internal sealed class UninstallProgress
    {
        internal int RunId;
        internal string Phase, Message;
        internal long Completed, Attempted, Total = -1, Pending, Retained, BytesRead, ElapsedMilliseconds;
        internal double? EtaMinimumSeconds, EtaMaximumSeconds;
        internal int? Percent { get { return Total > 0 ? (int?)Math.Min(100, Math.Floor(100.0 * Completed / Total)) : null; } }
    }
    internal sealed class UninstallProgressReporter
    {
        private readonly Action<UninstallProgress> publish;
        private readonly Func<long> clock;
        private readonly long started;
        private readonly int runId;
        private long lastPublished = -1000, lastRateTime, lastRateCompleted, lastAdvance;
        private readonly Queue<double> rates = new Queue<double>();
        private string phase = "verify", message = "正在核验卸载登记……";
        private long completed, attempted, total = -1, pending, retained, bytes;
        internal UninstallProgressReporter(Action<UninstallProgress> sink, int run) : this(sink, run, ProductionClock()) { }
        internal UninstallProgressReporter(Action<UninstallProgress> sink, int run, Func<long> now)
        { publish = sink; runId = run; clock = now; started = clock(); lastRateTime = lastAdvance = started; }
        private static Func<long> ProductionClock() { Stopwatch watch = Stopwatch.StartNew(); return delegate { return watch.ElapsedMilliseconds; }; }
        internal void Phase(string value, string text, long count)
        { phase = value; message = text; total = count; completed = attempted = 0; rates.Clear(); lastRateTime = lastAdvance = clock(); lastRateCompleted = 0; Emit(true); }
        internal void Finalizing()
        { phase = "finalize"; message = "正在完成卸载入口和登记处理……"; rates.Clear(); Emit(true); }
        internal void Counts(long done, long tried, long blocked, long kept)
        { if (done != completed) lastAdvance = clock(); completed = done; attempted = tried; pending = blocked; retained = kept; Emit(false); }
        internal void ReadBytes(int count) { bytes += count; Emit(false); }
        internal void Discovered(long count) { attempted = count; Emit(false); }
        internal void Waiting(string text) { message = text; rates.Clear(); lastRateTime = clock(); lastRateCompleted = completed; Emit(true); }
        internal void Complete()
        { if (pending != 0 || total < 1) throw new InvalidOperationException("Pending items remain. Uninstallation cannot be reported as complete."); completed = attempted = total; phase = "complete"; message = "卸载完成"; Emit(true); }
        internal void Emit(bool force)
        {
            long now = clock(); if (!force && now - lastPublished < 200) return;
            if (phase == "remove" && now - lastRateTime >= 1000)
            {
                rates.Enqueue(1000.0 * (completed - lastRateCompleted) / (now - lastRateTime));
                while (rates.Count > 4) rates.Dequeue(); lastRateTime = now; lastRateCompleted = completed;
            }
            UninstallProgress value = new UninstallProgress { RunId = runId, Phase = phase, Message = message,
                Completed = completed, Attempted = attempted, Total = total, Pending = pending, Retained = retained,
                BytesRead = bytes, ElapsedMilliseconds = now - started };
            if (phase == "remove" && total > completed && pending == 0 && rates.Count >= 3 && now - lastAdvance < 1500)
            {
                double min = Double.MaxValue, max = 0; foreach (double rate in rates) { min = Math.Min(min, rate); max = Math.Max(max, rate); }
                if (min > 0 && max <= min * 2)
                {
                    value.EtaMinimumSeconds = Math.Max(1, Math.Floor((total - completed) / max * 0.8));
                    value.EtaMaximumSeconds = Math.Max(value.EtaMinimumSeconds.Value, Math.Ceiling((total - completed) / min * 1.2));
                }
            }
            lastPublished = now; if (publish != null) publish(value);
        }
    }

    internal sealed class UninstallForm : Form
    {
        private readonly UninstallContext context;
        private readonly CheckBox removeData = new SetupCheckBox();
        private readonly SetupButton start = new SetupButton { Primary = true, Danger = true };
        private readonly SetupButton cancel = new SetupButton();
        private readonly SetupProgress progress = new SetupProgress();
        private readonly System.Windows.Forms.Timer progressAnimation = new System.Windows.Forms.Timer { Interval = 16 };
        private readonly Label status = new Label();
        private readonly Label progressDetails = new Label();
        private readonly System.Windows.Forms.Timer progressRefresh = new System.Windows.Forms.Timer { Interval = 200 };
        private readonly object progressGate = new object();
        private UninstallProgress latestProgress;
        private UninstallProgress lastAppliedProgress;
        private long lastAppliedTicks;
        private int progressRun;
        private bool progressFinished;
        private bool busy;
        private readonly bool testNoDialog;
        internal string Failure;
        internal string TestFailureStack;
        internal UninstallForm(UninstallContext value) : this(value, false) { }
        internal UninstallForm(UninstallContext value, bool testNoDialogValue)
        {
            SuspendLayout();
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            testNoDialog = testNoDialogValue; context = value; Text = "卸载 DeepSteam";
            if (!testNoDialog) SetupWindowMotion.Prepare(this);
            AutoScaleDimensions = new SizeF(96F, 96F); AutoScaleMode = AutoScaleMode.Dpi;
            BackColor = SetupTheme.Paper; ForeColor = SetupTheme.Ink; Font = new Font("Microsoft YaHei UI", 10);
            ClientSize = new Size(720, 510); MinimumSize = new Size(560, 400); StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.Sizable; MaximizeBox = false;

            TableLayoutPanel outer = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2, Padding = new Padding(28), Margin = Padding.Empty };
            outer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            outer.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); outer.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            Panel viewport = new Panel { Dock = DockStyle.Fill, AutoScroll = true, Margin = Padding.Empty, Name = "uninstall-scroll-body" };
            TableLayoutPanel body = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, ColumnCount = 1, Margin = Padding.Empty };
            body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            Label title = TextBlock("卸载 DeepSteam", SetupTheme.Ink, 0, 18);
            title.Font = new Font(Font.FontFamily, 19, FontStyle.Bold);
            Label description = TextBlock("移除软件并保留学习内容。\r\n默认保留学习记录、模型设置、导入文件和工作区。", SetupTheme.Ink, 0, 22);
            Label path = TextBlock("版本：" + context.Version + "\r\n安装位置：" + context.Root, SetupTheme.Muted, 0, 22);
            TableLayoutPanel choice = new TableLayoutPanel { AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Dock = DockStyle.Top,
                ColumnCount = 2, Margin = new Padding(0, 0, 0, 20), Padding = new Padding(16), BackColor = SetupTheme.Panel };
            choice.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize)); choice.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            removeData.Text = ""; removeData.AutoSize = true; removeData.Checked = false; removeData.Margin = new Padding(0, 4, 12, 0);
            removeData.AccessibleName = "同时移除应用记录、设置和缓存";
            Label choiceText = TextBlock("同时移除应用记录、设置和缓存", SetupTheme.Ink, 0, 4);
            Label choiceHint = TextBlock("导入文件和工作区仍会保留。", SetupTheme.Muted, 0, 0);
            choiceText.Cursor = Cursors.Hand; choiceText.Click += delegate { if (removeData.Enabled) removeData.Checked = !removeData.Checked; };
            choice.Controls.Add(removeData, 0, 0); choice.Controls.Add(choiceText, 1, 0); choice.Controls.Add(choiceHint, 1, 1);
            status.Text = "确认后将关闭 DeepSteam 并移除软件。"; status.ForeColor = SetupTheme.Muted;
            status.AutoSize = true; status.Dock = DockStyle.Top; status.Margin = new Padding(0, 0, 0, 12);
            body.Controls.Add(title, 0, 0); body.Controls.Add(description, 0, 1); body.Controls.Add(path, 0, 2); body.Controls.Add(choice, 0, 3); body.Controls.Add(status, 0, 4);
            viewport.Controls.Add(body); outer.Controls.Add(viewport, 0, 0);
            TableLayoutPanel footer = new TableLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
                ColumnCount = 1, Margin = new Padding(0, 16, 0, 0), Padding = Padding.Empty };
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            progress.Dock = DockStyle.Top; progress.Height = 6; progress.Margin = new Padding(0, 0, 0, 12); progress.Style = ProgressBarStyle.Marquee;
            progress.Visible = false;
            progressAnimation.Tick += delegate { if (progress.Style == ProgressBarStyle.Marquee) { progress.Phase += 0.016; progress.Invalidate(); } };
            progressDetails.AutoSize = true; progressDetails.Dock = DockStyle.Top; progressDetails.ForeColor = SetupTheme.Muted;
            progressDetails.Margin = new Padding(0, 0, 0, 12); progressDetails.UseMnemonic = false;
            progressRefresh.Tick += delegate { FlushLatestProgress(); };
            FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
                FlowDirection = FlowDirection.RightToLeft, WrapContents = true, Margin = Padding.Empty, Padding = Padding.Empty, Name = "uninstall-actions" };
            cancel.Text = "取消"; cancel.MinimumSize = new Size(100, 44); cancel.Margin = new Padding(0, 0, 12, 0); cancel.Click += delegate { if (!busy) Close(); };
            start.Text = "卸载 DeepSteam"; start.MinimumSize = new Size(160, 44); start.Margin = Padding.Empty;
            actions.Controls.Add(start); actions.Controls.Add(cancel);
            footer.Controls.Add(progressDetails, 0, 0); footer.Controls.Add(progress, 0, 1); footer.Controls.Add(actions, 0, 2); outer.Controls.Add(footer, 0, 1);
            Controls.Add(outer);
            // Width is constrained, height is measured from the actual font.
            // Long paths and high DPI text wrap; the footer never scrolls away.
            Action wrap = delegate {
                int width = Math.Max(180, viewport.ClientSize.Width - SystemInformation.VerticalScrollBarWidth - 2);
                foreach (Label label in new Label[] { title, description, path, status }) label.MaximumSize = new Size(width, 0);
                int inner = Math.Max(100, width - choice.Padding.Horizontal - removeData.Width - removeData.Margin.Horizontal - 12);
                choiceText.MaximumSize = new Size(inner, 0); choiceHint.MaximumSize = new Size(inner, 0);
                body.Width = width;
                progressDetails.MaximumSize = new Size(Math.Max(180, footer.ClientSize.Width), 0);
            };
            viewport.SizeChanged += delegate { wrap(); };
            Shown += delegate {
                ApplyDarkTitleBar();
                Rectangle work = Screen.FromControl(this).WorkingArea;
                MinimumSize = new Size(Math.Min(MinimumSize.Width, Math.Max(340, work.Width - 40)), Math.Min(MinimumSize.Height, Math.Max(300, work.Height - 40)));
                Size = new Size(Math.Min(Width, work.Width - 40), Math.Min(Height, work.Height - 40));
                Location = new Point(work.Left + (work.Width - Width) / 2, work.Top + (work.Height - Height) / 2); wrap();
            };
            start.Click += delegate { Begin(); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) e.Cancel = true; };
            FormClosed += delegate { progressAnimation.Stop(); progressAnimation.Dispose(); progressRefresh.Stop(); progressRefresh.Dispose(); };
            CancelButton = cancel; ResumeLayout(true); wrap();
        }
        private static Label TextBlock(string text, Color color, int top, int bottom)
        { return new Label { Text = text, ForeColor = color, AutoSize = true, Dock = DockStyle.Top, Margin = new Padding(0, top, 0, bottom), UseMnemonic = false }; }
        private void ApplyDarkTitleBar()
        {
            SetupTheme.ApplyTitleBar(this);
        }
        private void Begin()
        {
            if (busy) return;
            if (start.Text == "关闭") { Close(); return; }
            busy = true; Failure = null; TestFailureStack = null; start.Enabled = false; cancel.Enabled = false; removeData.Enabled = false; bool deleteData = removeData.Checked;
            ResetProgress(progressRun + 1); progress.Visible = true; if (SetupTheme.Motion) progressAnimation.Start(); progressRefresh.Start();
            UninstallProgressReporter reporter = new UninstallProgressReporter(QueueProgress, progressRun);
            BackgroundWorker worker = new BackgroundWorker();
            worker.DoWork += delegate(object sender, DoWorkEventArgs e)
            {
                reporter.Phase("verify", "正在核验卸载登记……", -1);
                UninstallContext fresh = UninstallRegistration.Verify(context.Root);
                e.Result = UninstallCore.RemoveWithProgress(fresh, deleteData, delegate(UninstallContext item) { UninstallCore.Stop(item, reporter); }, reporter, true);
            };
            worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs e)
            {
                FlushLatestProgress(); progressRefresh.Stop(); progressAnimation.Stop();
                busy = false; start.Enabled = true; cancel.Enabled = true;
                if (e.Error != null) { status.Text = e.Error is UninstallPendingException ? "可移除项目已处理，其余项目已保留。请关闭占用文件的程序后重试。" : "卸载尚未完成，已保留卸载入口，可稍后重试。"; start.Text = "重试卸载"; removeData.Enabled = true; Failure = e.Error.Message;
                    UninstallPendingException remaining = e.Error as UninstallPendingException;
                    FinishProgress(false, status.Text, remaining == null ? (long?)null : remaining.PendingCount);
                    if (testNoDialog) TestFailureStack = e.Error.StackTrace;
                    if (!testNoDialog) SetupDialog.ShowWarning(this, e.Error.Message, "DeepSteam 卸载尚未完成"); return; }
                status.Text = (string)e.Result; start.Text = "关闭"; start.Danger = false; FinishProgress(true, status.Text);
            };
            worker.RunWorkerAsync();
        }
        internal void ResetProgress(int run)
        {
            lock (progressGate) { progressRun = run; progressFinished = false; latestProgress = null; lastAppliedProgress = null; }
            progress.Value = 0; progress.Style = ProgressBarStyle.Marquee; progressDetails.Text = "正在准备卸载，正在统计项目";
        }
        internal void QueueProgress(UninstallProgress value)
        { lock (progressGate) { if (!progressFinished && value.RunId == progressRun) latestProgress = value; } }
        internal void FlushLatestProgress()
        {
            UninstallProgress value;
            lock (progressGate) { value = latestProgress; latestProgress = null; }
            if (value != null) ApplyProgress(value);
            else if (!progressFinished && lastAppliedProgress != null)
            {
                long silent = (long)(1000.0 * (Stopwatch.GetTimestamp() - lastAppliedTicks) / Stopwatch.Frequency);
                if (silent >= 1500)
                {
                    progressDetails.Text = Regex.Replace(progressDetails.Text, "此阶段预计剩余：[^\\r\\n]*秒", "正在等待 · 剩余时间暂不可用");
                    progressDetails.Text = Regex.Replace(progressDetails.Text, "已用时：[0-9]+ 秒", "已用时：" + ((lastAppliedProgress.ElapsedMilliseconds + silent) / 1000) + " 秒");
                }
            }
        }
        internal void ApplyProgress(UninstallProgress value)
        {
            if (progressFinished || value.RunId != progressRun) return;
            lastAppliedProgress = value; lastAppliedTicks = Stopwatch.GetTimestamp();
            status.Text = value.Message;
            bool fixedTotal = value.Total > 0 && (value.Phase == "check" || value.Phase == "remove" || value.Phase == "finalize" || value.Phase == "complete");
            progress.Style = fixedTotal ? ProgressBarStyle.Continuous : ProgressBarStyle.Marquee;
            progress.Value = fixedTotal ? value.Percent.Value : 0;
            string label = value.Phase == "check" ? "正在核验清单" : value.Phase == "finalize" ? "正在完成卸载登记" : "已核验项目";
            string detail = fixedTotal ? label + " " + value.Percent + "% · 已完成 " + value.Completed + " / " + value.Total + " 项" :
                "正在统计项目" + (value.Phase == "discover" || value.Phase == "workspaces" ? " · 已发现 " + value.Attempted + " 项" : "");
            if (value.Phase == "remove" || value.Phase == "finalize") detail += " · 已处理 " + value.Attempted + " 项（含文件夹和登记信息）";
            if (value.Pending > 0) detail += " · 待处理 " + value.Pending + " 项";
            if (value.Retained > 0) detail += " · 已保护 " + value.Retained + " 项";
            if (value.Phase == "check") detail += " · 已读取 " + (value.BytesRead / (1024.0 * 1024.0)).ToString("0.0") + " MB";
            detail += "\r\n已用时：" + (value.ElapsedMilliseconds / 1000) + " 秒 · " +
                (value.EtaMinimumSeconds.HasValue ? "此阶段预计剩余：" + value.EtaMinimumSeconds.Value.ToString("0") + "–" + value.EtaMaximumSeconds.Value.ToString("0") + " 秒" : "剩余时间暂不可用");
            progressDetails.Text = detail;
        }
        internal void FinishProgress(bool success, string message)
        { FinishProgress(success, message, null); }
        private void FinishProgress(bool success, string message, long? pendingCount)
        {
            lock (progressGate) { progressFinished = true; latestProgress = null; }
            progress.Style = ProgressBarStyle.Continuous; status.Text = message;
            if (success) { progress.Value = 100; progressDetails.Text = "100% · 卸载完成"; }
            else
            {
                progress.Value = 0; progress.Visible = false;
                string counts = lastAppliedProgress != null && (lastAppliedProgress.Phase == "remove" || lastAppliedProgress.Phase == "finalize") ?
                    " · 已完成 " + lastAppliedProgress.Completed + " / " + lastAppliedProgress.Total + " 项" : "";
                long blocked = pendingCount ?? (lastAppliedProgress == null ? 0 : lastAppliedProgress.Pending);
                if (blocked > 0) counts += " · 待处理 " + blocked + " 项";
                progressDetails.Text = "尚未完成" + counts + " · 已保留待处理项目和重试入口，剩余时间暂不可用";
            }
        }
    }

    internal sealed class UninstallPendingException : IOException
    {
        internal UninstallPendingException(string message) : base(message) { }
        internal int PendingCount;
    }

    // This index caches lexical boundaries only, never filesystem attributes or
    // permission results. Deletion still checks the live ancestor chain.
    internal sealed class UninstallProtectionIndex
    {
        private readonly HashSet<string> exact = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private readonly List<string> ordered;
        internal UninstallProtectionIndex(IEnumerable<string> folders)
        { foreach (string folder in folders) exact.Add(Path.GetFullPath(folder).TrimEnd('\\')); ordered = new List<string>(exact); ordered.Sort(StringComparer.OrdinalIgnoreCase); }
        internal bool Within(string value)
        {
            string path = Path.GetFullPath(value).TrimEnd('\\');
            while (!String.IsNullOrEmpty(path))
            { if (exact.Contains(path)) return true; path = Path.GetDirectoryName(path); if (path != null) path = path.TrimEnd('\\'); }
            return false;
        }
        internal bool Overlaps(string value)
        {
            if (Within(value)) return true;
            string prefix = Path.GetFullPath(value).TrimEnd('\\') + "\\";
            int index = ordered.BinarySearch(prefix, StringComparer.OrdinalIgnoreCase); if (index < 0) index = ~index;
            return index < ordered.Count && ordered[index].StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
        }
    }
    internal sealed class UninstallRetryQueue
    {
        private sealed class Item { internal string Path; internal Action Action; }
        private readonly List<Item> waiting = new List<Item>();
        private readonly Dictionary<string, string> pending;
        private readonly Func<long> clock;
        private readonly Action<int> sleep;
        internal long WaitedMilliseconds;
        internal int RetryAttempts;
        internal UninstallRetryQueue(Dictionary<string, string> failures) : this(failures, ProductionClock(), Thread.Sleep) { }
        internal UninstallRetryQueue(Dictionary<string, string> failures, Func<long> now, Action<int> delay)
        { pending = failures; clock = now; sleep = delay; }
        private static Func<long> ProductionClock() { Stopwatch watch = Stopwatch.StartNew(); return delegate { return watch.ElapsedMilliseconds; }; }
        internal static bool SharingViolation(IOException error)
        {
            Win32Exception native = error.InnerException as Win32Exception;
            int code = native != null ? native.NativeErrorCode : error.HResult & 0xffff;
            return code == 32 || code == 33;
        }
        internal void Submit(string path, Action action)
        {
            try { UninstallCore.TryItem(path, pending, action, true); }
            catch (IOException) { waiting.Add(new Item { Path = path, Action = action }); }
        }
        internal void Drain(Action<int> report)
        {
            long deadline = clock() + 3000;
            for (int round = 0; waiting.Count > 0 && round < 15 && clock() < deadline; round++)
            {
                if (report != null) report(waiting.Count);
                int delay = (int)Math.Min(200, deadline - clock()); if (delay <= 0) break;
                sleep(delay); WaitedMilliseconds += delay;
                for (int index = waiting.Count - 1; index >= 0 && clock() < deadline; index--)
                {
                    Item item = waiting[index];
                    try { RetryAttempts++; UninstallCore.TryItem(item.Path, pending, item.Action, true); waiting.RemoveAt(index); }
                    catch (IOException) { }
                }
            }
            foreach (Item item in waiting) pending[item.Path] = "文件仍被占用；已保留，可关闭占用程序后重试";
            waiting.Clear();
        }
    }

    internal static class UninstallCore
    {
        internal static bool OverlapsProtected(string path, List<string> protectedFolders)
        {
            foreach (string folder in protectedFolders)
                if (UninstallRegistration.Under(path, folder) || UninstallRegistration.Under(folder, path)) return true;
            return false;
        }
        internal static List<string> WorkspaceFolders(UninstallContext context)
        { return WorkspaceFolders(context, null); }
        private static List<string> WorkspaceFolders(UninstallContext context, UninstallProgressReporter progress)
        {
            List<string> result = new List<string>(context.WorkspaceSnapshot);
            long discovered = 0;
            foreach (string dataRoot in context.DataRoots)
            {
                // These are fixed application-owned summaries, never an arbitrary
                // supplied path. Invalid summaries fail closed before deletion.
                foreach (string relative in new string[] { "runtime/harness-state/profile/workspace-folders.json", "runtime/harness-state/workspace-folders.json" })
                {
                    string file = UninstallRegistration.Child(dataRoot, relative);
                    // File.Exists hides access errors as false. An unreadable
                    // workspace registration cannot authorize any deletion.
                    if (!Exists(file)) continue;
                    UninstallRegistration.PlainPath(file);
                    if (new FileInfo(file).Length > 4 * 1024 * 1024) throw new IOException("工作区登记过大，已保留数据并停止卸载。");
                    Dictionary<string, object> value = (Dictionary<string, object>)UninstallRegistration.Json(file);
                    if (Convert.ToInt32(value["schema"]) != 1) throw new IOException("工作区登记格式未知，已停止卸载。");
                    foreach (object raw in (object[])value["folders"])
                    {
                        string folder = raw as string;
                        if (String.IsNullOrEmpty(folder) || !Path.IsPathRooted(folder)) throw new IOException("工作区位置不正确，已停止卸载。");
                        result.Add(Path.GetFullPath(folder).TrimEnd('\\'));
                    }
                }
                foreach (string relative in new string[] { "data/deeptutor", "data/materials", "data/uploads",
                    "runtime/harness-state/profile/attachments", "runtime/harness-state/attachments", "runtime/deeptutor-home/data" })
                    result.Add(UninstallRegistration.Child(dataRoot, relative));
                List<string> nativeCatalogs = new List<string>();
                // Native catalogs were fully read before the first deletion.
                // The hash-anchored snapshot survives a missing Python runtime
                // and can only retain additional locations, never own files.
                if (!context.WorkspaceSnapshotReady || Exists(Path.Combine(context.Root, "runtime", "python", "python.exe")))
                    FindNativeCatalogs(UninstallRegistration.Child(dataRoot, "runtime/deeptutor-home"), nativeCatalogs,
                        delegate { discovered++; if (progress != null) progress.Discovered(discovered); });
                foreach (string catalog in nativeCatalogs)
                {
                    if (progress != null) progress.Waiting("正在读取原有工作区登记；导入文件与工作区会保留……");
                    result.AddRange(ReadNativeCatalog(context, catalog, progress));
                }
            }
            return new List<string>(new HashSet<string>(result, StringComparer.OrdinalIgnoreCase));
        }
        internal static void FindNativeCatalogs(string folder, List<string> files)
        { FindNativeCatalogs(folder, files, null); }
        private static void FindNativeCatalogs(string folder, List<string> files, Action found)
        {
            if (!Exists(folder)) return;
            UninstallRegistration.PlainPath(folder);
            foreach (string entry in Directory.EnumerateFileSystemEntries(Package.Extended(folder)))
            {
                if (found != null) found();
                string path = entry.StartsWith(@"\\?\") ? entry.Substring(4) : entry;
                // A linked catalog could hide registered workspaces. Fail closed
                // rather than treating an unreadable native catalog as empty.
                FileAttributes attributes = File.GetAttributes(entry);
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("原有学习目录包含链接，无法完整核验工作区；已保留所有文件。");
                if ((attributes & FileAttributes.Directory) != 0) FindNativeCatalogs(path, files, found);
                else if (String.Equals(Path.GetFileName(path), "workspaces.sqlite3", StringComparison.OrdinalIgnoreCase)) files.Add(path);
            }
        }
        internal static List<string> ReadNativeCatalog(UninstallContext context, string catalog)
        { return ReadNativeCatalog(context, catalog, null); }
        private static List<string> ReadNativeCatalog(UninstallContext context, string catalog, UninstallProgressReporter progress)
        {
            string python = Path.Combine(context.Root, "runtime", "python", "python.exe");
            UninstallFile row = context.Files.Find(delegate(UninstallFile file) { return file.Path == "runtime/python/python.exe"; });
            if (row == null || !File.Exists(python) || UninstallRegistration.Sha(python) != row.Hash)
                throw new IOException("无法使用可信的本机读取器核验原有工作区；已保留所有文件。");
            UninstallRegistration.PlainPath(catalog);
            string code = "import base64,json,sqlite3,sys; from pathlib import Path; " +
                "db=sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True); " +
                "rows=db.execute('SELECT payload FROM workspaces').fetchall(); " +
                "paths=[json.loads(raw[0]).get('path') for raw in rows]; " +
                "tables={r[0] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")}; " +
                "meta=db.execute(\"SELECT value FROM metadata WHERE key='root'\").fetchall() if 'metadata' in tables else []; " +
                "paths += [json.loads(r[0]) for r in meta]; db.close(); " +
                "[print(base64.b64encode(p.encode('utf-8')).decode('ascii')) for p in paths if isinstance(p,str) and p]";
            List<string> output = new List<string>(); int characters = 0;
            ProcessStartInfo info = new ProcessStartInfo { FileName = python,
                Arguments = "-I -B -c " + InstallerForm.Quote(code) + " " + InstallerForm.Quote(catalog),
                WorkingDirectory = context.Root, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true };
            using (Process helper = new Process())
            {
                helper.StartInfo = info;
                helper.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) {
                    if (e.Data != null) lock (output) { characters += e.Data.Length; if (characters < 4 * 1024 * 1024) output.Add(e.Data); }
                };
                helper.ErrorDataReceived += delegate { };
                helper.Start(); helper.BeginOutputReadLine(); helper.BeginErrorReadLine();
                if (!WaitForExit(helper, 30000, progress, "正在读取原有工作区登记；尚未删除文件……")) { helper.Kill(); throw new IOException("原有工作区登记读取超时；未开始删除文件。"); }
                helper.WaitForExit();
                if (helper.ExitCode != 0 || characters >= 4 * 1024 * 1024) throw new IOException("原有工作区登记无法完整读取；未开始删除文件。");
            }
            List<string> result = new List<string>();
            foreach (string encoded in output)
            {
                string path = UninstallRegistration.UnB64(encoded);
                if (!Path.IsPathRooted(path)) throw new IOException("原有工作区路径不正确；未开始删除文件。");
                result.Add(Path.GetFullPath(path).TrimEnd('\\'));
            }
            return result;
        }
        internal static void Stop(UninstallContext context)
        { Stop(context, null); }
        internal static void Stop(UninstallContext context, UninstallProgressReporter progress)
        {
            CloseInstalledLaunchers(context, progress);
            string desktop = Path.Combine(context.Root, "runtime", "desktop", "DeepSteam Desktop.exe");
            bool quitRequested = false;
            foreach (Process process in Process.GetProcesses())
            {
                try
                {
                    if (!String.Equals(process.MainModule.FileName, desktop, StringComparison.OrdinalIgnoreCase)) continue;
                    DateTime created = process.StartTime;
                    if (process.StartTime != created || !String.Equals(process.MainModule.FileName, desktop, StringComparison.OrdinalIgnoreCase)) continue;
                    if (!quitRequested && SupportsGracefulQuit(context))
                    {
                        UninstallFile desktopRow = context.Files.Find(delegate(UninstallFile file) { return file.Path == "runtime/desktop/DeepSteam Desktop.exe"; });
                        UninstallRegistration.PlainPath(desktop);
                        if (desktopRow == null || new FileInfo(desktop).Length != desktopRow.Bytes || UninstallRegistration.Sha(desktop) != desktopRow.Hash)
                            throw new IOException("桌面程序已被改写，无法自动请求退出；请手动退出 DeepSteam 后重试。");
                        using (Process request = Process.Start(new ProcessStartInfo { FileName = desktop,
                            Arguments = "--quit --install-root=" + InstallerForm.Quote(context.Root), WorkingDirectory = context.Root,
                            UseShellExecute = false, CreateNoWindow = true })) { }
                        quitRequested = true;
                    }
                    if (quitRequested && WaitForExit(process, 2000, progress, "正在请求 DeepSteam 退出，包括隐藏的托盘窗口……")) continue;
                    if (process.StartTime != created || !String.Equals(process.MainModule.FileName, desktop, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("桌面进程身份发生变化，已停止卸载。");
                    // Old versions do not handle --quit. Keep their graceful
                    // window-close fallback; never kill a busy or hidden process.
                    if (process.MainWindowHandle != IntPtr.Zero) process.CloseMainWindow();
                    if (!WaitForExit(process, quitRequested ? 88000 : 90000, progress, "正在等待 DeepSteam 保存状态并退出……")) throw new IOException("DeepSteam 正在关闭，请稍后重试；未强制结束其他程序。");
                }
                catch (Win32Exception) { }
                catch (InvalidOperationException) { }
                finally { process.Dispose(); }
            }
            string script = Path.Combine(context.Root, "installer", "Stop-DeepSteam.ps1");
            UninstallFile record = context.Files.Find(delegate(UninstallFile row) { return row.Path == "installer/Stop-DeepSteam.ps1"; });
            if (record != null && File.Exists(script))
            {
                UninstallRegistration.PlainPath(script);
                if (!File.Exists(script) || UninstallRegistration.Sha(script) != record.Hash) throw new IOException("关闭服务脚本已被改写；请手动关闭 DeepSteam 后重试。");
                ProcessStartInfo info = new ProcessStartInfo { FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe"),
                    Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + InstallerForm.Quote(script) + " -InstallRoot " + InstallerForm.Quote(context.Root),
                    WorkingDirectory = context.Root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
                using (Process helper = new Process())
                {
                    helper.StartInfo = info; helper.OutputDataReceived += delegate { }; helper.ErrorDataReceived += delegate { };
                    helper.Start(); helper.BeginOutputReadLine(); helper.BeginErrorReadLine();
                    if (!WaitForExit(helper, 180000, progress, "正在关闭本次安装的后台服务；尚未删除文件……")) throw new IOException("本次安装的服务仍在退出，未开始删除。请等待后重试。");
                    if (helper.ExitCode != 0) throw new IOException("本次安装的服务未能完整关闭，未开始删除。请关闭 DeepSteam 后重试。");
                }
            }
            foreach (Process process in Process.GetProcesses())
            {
                try
                {
                    if (process.Id != Process.GetCurrentProcess().Id && UninstallRegistration.Under(process.MainModule.FileName, context.Root))
                        throw new IOException("仍有本次安装的程序在运行，未开始删除。请关闭相关程序后重试。");
                }
                catch (Win32Exception) { }
                catch (InvalidOperationException) { }
                finally { process.Dispose(); }
            }
        }
        internal static bool SupportsGracefulQuit(UninstallContext context)
        {
            foreach (string name in new string[] { "desktop/package.json", "runtime/desktop/resources/app/package.json" })
            {
                UninstallFile row = context.Files.Find(delegate(UninstallFile file) { return file.Path == name; });
                if (row == null) continue;
                string path = UninstallRegistration.Child(context.Root, name); if (!Exists(path)) continue;
                UninstallRegistration.PlainPath(path);
                if (row.Bytes > 64 * 1024 || new FileInfo(path).Length != row.Bytes || UninstallRegistration.Sha(path) != row.Hash)
                    throw new IOException("桌面退出能力登记已被改写；请手动退出 DeepSteam 后重试。");
                Dictionary<string, object> value = UninstallRegistration.Json(path) as Dictionary<string, object>; object protocol;
                if (value != null && value.TryGetValue("deepsteamGracefulQuitProtocol", out protocol) && protocol is int && (int)protocol == 1) return true;
            }
            return false;
        }
        internal static bool IsServiceLauncherCommand(string command, string executable)
        {
            int count;
            IntPtr values = CommandLineToArgvW(command ?? "", out count);
            if (values == IntPtr.Zero) return false;
            try
            {
                if (count < 1 || count > 2) return false;
                string first = Marshal.PtrToStringUni(Marshal.ReadIntPtr(values));
                if (!Path.IsPathRooted(first) || !String.Equals(Path.GetFullPath(first), executable, StringComparison.OrdinalIgnoreCase)) return false;
                if (count == 1) return true;
                string argument = Marshal.PtrToStringUni(Marshal.ReadIntPtr(values, IntPtr.Size));
                return argument == "--launch" || argument == "--stop";
            }
            finally { LocalFree(values); }
        }
        private static string LauncherCommand(Process process)
        {
            int required;
            NtQueryInformationProcess(process.Handle, 60, IntPtr.Zero, 0, out required);
            if (required < 16 || required > 128 * 1024) throw new IOException("无法核验旧启动器状态；请自行关闭该窗口后重试。");
            IntPtr buffer = Marshal.AllocHGlobal(required);
            try
            {
                if (NtQueryInformationProcess(process.Handle, 60, buffer, required, out required) != 0)
                    throw new IOException("无法核验旧启动器状态；请自行关闭该窗口后重试。");
                int length = (ushort)Marshal.ReadInt16(buffer);
                IntPtr text = Marshal.ReadIntPtr(buffer, IntPtr.Size == 8 ? 8 : 4);
                long offset = text.ToInt64() - buffer.ToInt64();
                if (length % 2 != 0 || offset < 0 || offset + length > required) throw new IOException("启动器进程参数不完整。");
                return Marshal.PtrToStringUni(text, length / 2);
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }
        internal static void CloseInstalledLaunchers(UninstallContext context)
        { CloseInstalledLaunchers(context, null); }
        private static void CloseInstalledLaunchers(UninstallContext context, UninstallProgressReporter progress)
        {
            string expected = Path.Combine(context.Root, "DeepSteam.exe");
            UninstallFile row = context.Files.Find(delegate(UninstallFile file) { return file.Path == "DeepSteam.exe"; });
            foreach (Process process in Process.GetProcesses())
            {
                try
                {
                    if (process.Id == Process.GetCurrentProcess().Id || !String.Equals(process.MainModule.FileName, expected, StringComparison.OrdinalIgnoreCase)) continue;
                    DateTime created = process.StartTime;
                    if (row == null || !File.Exists(expected) || new FileInfo(expected).Length != row.Bytes || UninstallRegistration.Sha(expected) != row.Hash ||
                        !IsServiceLauncherCommand(LauncherCommand(process), expected))
                        throw new IOException("仍有安装或未知启动器在运行；请完成或取消该窗口后重试。未强制结束程序。");
                    if (process.StartTime != created || !String.Equals(process.MainModule.FileName, expected, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("启动器身份发生变化，已停止卸载。");
                    // Graceful close only: the launcher's busy handler refuses
                    // to close during startup/installation. Never force-kill it.
                    if (process.MainWindowHandle == IntPtr.Zero || !process.CloseMainWindow() || !WaitForExit(process, 10000, progress, "正在等待本次安装的启动窗口关闭……"))
                        throw new IOException("启动器仍在忙碌或没有可关闭窗口；请自行关闭后重试。未强制结束程序。");
                }
                catch (Win32Exception) { }
                catch (InvalidOperationException) { }
                finally { process.Dispose(); }
            }
        }
        private static bool WaitForExit(Process process, int timeout, UninstallProgressReporter progress, string message)
        {
            Stopwatch watch = Stopwatch.StartNew();
            do
            {
                if (process.WaitForExit((int)Math.Min(500, Math.Max(0, timeout - watch.ElapsedMilliseconds)))) return true;
                if (progress != null) progress.Waiting(message);
            } while (watch.ElapsedMilliseconds < timeout);
            return process.HasExited;
        }
        [DllImport("ntdll.dll")]
        private static extern int NtQueryInformationProcess(IntPtr process, int informationClass, IntPtr information, int length, out int returned);
        [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CommandLineToArgvW(string commandLine, out int count);
        [DllImport("kernel32.dll")]
        private static extern IntPtr LocalFree(IntPtr pointer);
        internal static string Remove(UninstallContext context, bool deleteData, Action<UninstallContext> stop, Action<string> progress, bool registration)
        {
            string last = null;
            return RemoveWithProgress(context, deleteData, stop, new UninstallProgressReporter(delegate(UninstallProgress value) {
                if (value.Message != last) { last = value.Message; progress(value.Message); }
            }, 0), registration);
        }
        internal static string RemoveWithProgress(UninstallContext context, bool deleteData, Action<UninstallContext> stop, UninstallProgressReporter progress, bool registration)
        {
            UninstallRegistration.Root(context.Root);
            progress.Phase("stop", "正在关闭本次安装的 DeepSteam 服务……", -1); stop(context);
            progress.Phase("workspaces", "正在核验工作区保护范围；尚未删除文件……", -1);
            List<string> protectedFolders = WorkspaceFolders(context, progress);
            UninstallProtectionIndex protection = new UninstallProtectionIndex(protectedFolders);
            List<string> files = new List<string>(); List<string> retained = new List<string>();
            Dictionary<string, string> pending = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            UninstallRetryQueue retry = new UninstallRetryQueue(pending);
            HashSet<string> directories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            progress.Phase("check", "正在核对程序清单；用户文件与改写的文件会保留……", context.Files.Count);
            long checkedFiles = 0;
            foreach (UninstallFile row in context.Files)
            {
                UninstallFile candidate = row;
                string path = UninstallRegistration.Child(context.Root, row.Path);
                retry.Submit(path, delegate {
                    if (!Exists(path)) return;
                    UninstallRegistration.PlainPath(path);
                    if (protection.Overlaps(path) || new FileInfo(Package.Extended(path)).Length != candidate.Bytes || UninstallRegistration.Sha(path, progress.ReadBytes) != candidate.Hash)
                    { retained.Add(candidate.Path); return; }
                    CheckUnlocked(path);
                    files.Add(path); string folder = Path.GetDirectoryName(path);
                    while (!String.Equals(folder, context.Root, StringComparison.OrdinalIgnoreCase)) { directories.Add(folder); folder = Path.GetDirectoryName(folder); }
                });
                checkedFiles++; progress.Counts(checkedFiles, checkedFiles, pending.Count, retained.Count);
            }
            progress.Emit(true);
            List<string> dataFiles = new List<string>(); List<string> dataFolders = new List<string>();
            if (deleteData)
            {
                progress.Phase("discover", "正在统计所选应用记录、设置与缓存……", -1);
                long discovered = 0;
                foreach (string dataRoot in context.DataRoots)
                {
                    if (!String.Equals(dataRoot, context.Root, StringComparison.OrdinalIgnoreCase))
                    {
                        string owner = Path.Combine(dataRoot, ".deepsteam-data-owner"); UninstallRegistration.PlainPath(owner);
                        if (!File.Exists(owner) || File.ReadAllText(owner).Trim() != context.Id)
                            throw new IOException("独立数据目录未绑定本次安装；已停止，未删除数据。");
                    }
                    foreach (string relative in new string[] { "data/learning.sqlite3", "data/learning.sqlite3-wal", "data/learning.sqlite3-shm", "deepsteam-storage.json" })
                    {
                        string file = UninstallRegistration.Child(dataRoot, relative);
                        if (!protection.Overlaps(file))
                            TryItem(file, pending, delegate { if (Exists(file)) dataFiles.Add(file); });
                    }
                    foreach (string relative in new string[] { "cache", "logs", "runtime/temp", "runtime/deeptutor-home", "runtime/harness-state", "runtime/openmaic-standalone/data", "data/openmaic" })
                        CollectData(UninstallRegistration.Child(dataRoot, relative), protection, dataFiles, dataFolders, pending,
                            delegate { discovered++; progress.Discovered(discovered); });
                }
                List<string> candidates = new List<string>(new HashSet<string>(dataFiles, StringComparer.OrdinalIgnoreCase)); dataFiles.Clear();
                foreach (string candidate in candidates)
                {
                    string path = candidate;
                    retry.Submit(path, delegate { UninstallRegistration.PlainPath(path); CheckUnlocked(path); dataFiles.Add(path); });
                }
            }
            progress.Phase("locks", "正在完成删除条件核验；短暂占用将进行有界重试……", -1);
            retry.Drain(delegate(int count) { progress.Waiting("正在等待 " + count + " 项短暂占用解除；权限受限项已保留……"); });
            // Validate every junction before deleting files. Declared links are
            // removed as links only; their targets are never traversed.
            List<string> links = new List<string>();
            foreach (UninstallLink row in context.Links)
            {
                string path = UninstallRegistration.Child(context.Root, row.Path);
                if (protection.Overlaps(path)) { retained.Add(row.Path); continue; }
                bool nested = false;
                foreach (UninstallLink parent in context.Links)
                    if (parent.Path != row.Path && UninstallRegistration.Under(path, UninstallRegistration.Child(context.Root, parent.Path))) { nested = true; break; }
                if (nested) continue;
                TryItem(path, pending, delegate {
                    if (!Exists(path)) return;
                    UninstallRegistration.PlainPath(Path.GetDirectoryName(path));
                    if ((File.GetAttributes(Package.Extended(path)) & FileAttributes.ReparsePoint) == 0) { retained.Add(row.Path); return; }
                    string target = FinalPath(path), expected = UninstallRegistration.Child(context.Root, row.Target);
                    if (!String.Equals(target, expected, StringComparison.OrdinalIgnoreCase)) { retained.Add(row.Path); return; }
                    links.Add(path); directories.Add(Path.GetDirectoryName(path));
                });
            }
            bool snapshotChanged = !context.WorkspaceSnapshotReady;
            foreach (string folder in protectedFolders)
                if (!context.WorkspaceSnapshot.Exists(delegate(string saved) { return String.Equals(saved, folder, StringComparison.OrdinalIgnoreCase); }))
                { context.WorkspaceSnapshot.Add(folder); snapshotChanged = true; }
            if (snapshotChanged)
            {
                context.WorkspaceSnapshotReady = true;
                CommitWorkspaceSnapshot(context);
            }
            // Keep the installed marker and both entry points until every other
            // removal succeeds. A mid-way failure remains launchable for retry.
            List<string> finalFiles = new List<string>();
            files.RemoveAll(delegate(string path) {
                string name = Path.GetFileName(path);
                if (name == Program.InstalledMarker || name == "DeepSteam.exe" || name == "Uninstall-DeepSteam.exe") { finalFiles.Add(path); return true; }
                return false;
            });
            finalFiles.Sort(delegate(string left, string right) {
                return Path.GetFileName(left) == "Uninstall-DeepSteam.exe" ? 1 : Path.GetFileName(right) == "Uninstall-DeepSteam.exe" ? -1 : 0;
            });
            directories.UnionWith(dataFolders);
            List<string> ordered = new List<string>(directories); ordered.Sort(delegate(string left, string right) { return right.Length.CompareTo(left.Length); });
            // The denominator includes unresolved preflight items and one atomic
            // finalization unit. A failed or rolled-back uninstall cannot hit 100%.
            long completed = 0, attempted = pending.Count;
            progress.Phase("remove", "正在移除已核验的程序与所选数据……", (long)links.Count + files.Count + dataFiles.Count + ordered.Count + pending.Count + 1);
            progress.Counts(completed, attempted, pending.Count, retained.Count);
            UninstallRetryQueue removals = new UninstallRetryQueue(pending);
            Action<string, Action> remove = delegate(string path, Action action) {
                attempted++;
                removals.Submit(path, delegate {
                    try { action(); } catch (FileNotFoundException) { } catch (DirectoryNotFoundException) { }
                    completed++; progress.Counts(completed, attempted, pending.Count, retained.Count);
                });
                progress.Counts(completed, attempted, pending.Count, retained.Count);
            };
            foreach (string candidate in links) { string path = candidate; remove(path, delegate { UninstallRegistration.PlainPath(Path.GetDirectoryName(path)); Directory.Delete(Package.Extended(path), false); }); }
            foreach (string candidate in files) { string path = candidate; remove(path, delegate { UninstallRegistration.PlainPath(path); File.Delete(Package.Extended(path)); }); }
            foreach (string candidate in dataFiles) { string path = candidate; remove(path, delegate { UninstallRegistration.PlainPath(path); File.Delete(Package.Extended(path)); }); }
            removals.Drain(delegate(int count) { progress.Waiting("正在等待 " + count + " 项短暂占用解除；其他可移除项已处理……"); });
            progress.Counts(completed, attempted, pending.Count, retained.Count);
            progress.Waiting("正在清理空目录；用户文件所在目录会保留……");
            foreach (string folder in ordered)
            {
                attempted++; if (TryItem(folder, pending, delegate { TryEmpty(folder); })) completed++;
                progress.Counts(completed, attempted, pending.Count, retained.Count);
            }
            progress.Emit(true);
            if (pending.Count > 0) throw Pending(context, pending);
            progress.Finalizing(); attempted++; progress.Counts(completed, attempted, pending.Count, retained.Count);
            // A previous retry report is our diagnostic, never a user input.
            string oldReport = UninstallRegistration.Child(context.Root, "installer/deepsteam-uninstall-retained.txt");
            TryItem(oldReport, pending, delegate { UninstallRegistration.PlainPath(oldReport); File.Delete(Package.Extended(oldReport)); });
            if (deleteData)
                foreach (string folder in context.DataRoots)
                    if (!String.Equals(folder, context.Root, StringComparison.OrdinalIgnoreCase))
                    {
                        string owner = Path.Combine(folder, ".deepsteam-data-owner");
                        TryItem(owner, pending, delegate { UninstallRegistration.PlainPath(owner); if (Exists(owner) && File.ReadAllText(owner).Trim() == context.Id) CheckUnlocked(owner); });
                    }
            foreach (string name in new string[] { UninstallRegistration.ManifestName, UninstallRegistration.IdName })
            {
                string file = Path.Combine(context.Root, name);
                TryItem(file, pending, delegate { UninstallRegistration.PlainPath(file); CheckUnlocked(file); });
            }
            if (pending.Count > 0) throw Pending(context, pending);
            // Final identities are small. Keep their bytes until all final
            // deletes succeed so a last-moment lock remains retryable too.
            Dictionary<string, byte[]> finalBytes = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
            if (deleteData)
                foreach (string folder in context.DataRoots)
                    if (!String.Equals(folder, context.Root, StringComparison.OrdinalIgnoreCase))
                    {
                        string owner = Path.Combine(folder, ".deepsteam-data-owner");
                        TryItem(owner, pending, delegate { if (Exists(owner)) finalBytes.Add(owner, File.ReadAllBytes(owner)); });
                    }
            foreach (string path in finalFiles)
                TryItem(path, pending, delegate { UninstallRegistration.PlainPath(path); CheckUnlocked(path); finalBytes.Add(path, File.ReadAllBytes(Package.Extended(path))); });
            if (pending.Count > 0) throw Pending(context, pending);
            foreach (string path in finalFiles) TryItem(path, pending, delegate { UninstallRegistration.PlainPath(path); File.Delete(Package.Extended(path)); });
            if (pending.Count > 0)
            {
                foreach (KeyValuePair<string, byte[]> item in finalBytes)
                    if (!File.Exists(Package.Extended(item.Key)))
                        TryItem(item.Key, pending, delegate { UninstallRegistration.PlainPath(item.Key); File.WriteAllBytes(Package.Extended(item.Key), item.Value); });
                throw Pending(context, pending);
            }
            string finalizingPath = context.Root;
            try
            {
                // Ownership markers are kept until all selected removals finish.
                if (deleteData)
                    foreach (string folder in context.DataRoots)
                        if (!String.Equals(folder, context.Root, StringComparison.OrdinalIgnoreCase))
                        {
                            string owner = Path.Combine(folder, ".deepsteam-data-owner"); finalizingPath = owner; UninstallRegistration.PlainPath(owner);
                            if (File.Exists(owner) && File.ReadAllText(owner).Trim() == context.Id) File.Delete(owner);
                        }
                finalizingPath = context.Root;
                if (registration) RemoveShortcuts(context);
                finalizingPath = Path.Combine(context.Root, UninstallRegistration.ManifestName); File.Delete(finalizingPath);
                finalizingPath = Path.Combine(context.Root, UninstallRegistration.IdName); File.Delete(finalizingPath);
                finalizingPath = context.Root;
                if (registration) Registry.CurrentUser.DeleteSubKeyTree(UninstallRegistration.RegistryName(context.Id), false);
            }
            catch (Exception)
            {
                foreach (KeyValuePair<string, byte[]> item in finalBytes)
                    if (!File.Exists(Package.Extended(item.Key))) { UninstallRegistration.PlainPath(item.Key); File.WriteAllBytes(Package.Extended(item.Key), item.Value); }
                UninstallRegistration.Write(context);
                pending[finalizingPath] = "卸载登记或最后的入口清理未完成；已恢复重试入口";
                throw Pending(context, pending);
            }
            TryEmpty(Path.Combine(context.Root, "installer"));
            TryEmpty(context.Root);
            progress.Complete();
            return "程序已卸载。" + (deleteData ? "可安全移除的应用记录、设置与缓存已清理；导入附件、文件库、工作区及与它们共用的数据目录已保留。" : "学习记录、配置、导入文件与工作区已保留。") +
                (retained.Count > 0 ? "另保留 " + retained.Count + " 个被改写的程序文件或目录。" : "");
        }
        private static void CommitWorkspaceSnapshot(UninstallContext context)
        {
            // Atomically replace only the manifest, then update its existing
            // trust anchor. Keep a same-directory rollback until both succeed;
            // do not rewrite the installation ID or other registration fields.
            string original = File.ReadAllText(context.Manifest, Encoding.UTF8), originalHash = UninstallRegistration.Sha(context.Manifest);
            StringBuilder content = new StringBuilder(original);
            if (!original.EndsWith("\n", StringComparison.Ordinal)) content.Append('\n');
            bool hadSnapshot = false; HashSet<string> savedRows = new HashSet<string>(StringComparer.Ordinal);
            foreach (string line in original.Split('\n'))
            { if (line == "S\tworkspaces-v1") hadSnapshot = true; else if (line.StartsWith("W\t", StringComparison.Ordinal)) savedRows.Add(line); }
            if (!hadSnapshot) content.Append("S\tworkspaces-v1\n");
            foreach (string folder in context.WorkspaceSnapshot)
            {
                string row = "W\t" + UninstallRegistration.B64(folder);
                if (savedRows.Add(row)) content.Append(row).Append('\n');
            }
            string temporary = context.Manifest + ".snapshot-" + Guid.NewGuid().ToString("N"), backup = temporary + ".previous";
            bool replaced = false, keepBackup = false;
            try
            {
                UninstallRegistration.PlainPath(temporary); UninstallRegistration.PlainPath(backup);
                File.WriteAllText(temporary, content.ToString(), new UTF8Encoding(false));
                string hash = UninstallRegistration.Sha(temporary);
                File.Replace(temporary, context.Manifest, backup); replaced = true;
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(UninstallRegistration.RegistryName(context.Id), true))
                { if (key == null) throw new IOException("卸载登记不可写，未开始移除文件。"); key.SetValue("ManifestSha256", hash); }
            }
            catch
            {
                if (replaced)
                {
                    try
                    {
                        File.Replace(backup, context.Manifest, null);
                        string currentHash;
                        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(UninstallRegistration.RegistryName(context.Id)))
                            currentHash = key == null ? originalHash : key.GetValue("ManifestSha256") as string;
                        if (!String.Equals(currentHash, originalHash, StringComparison.Ordinal))
                            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(UninstallRegistration.RegistryName(context.Id), true))
                                if (key != null) key.SetValue("ManifestSha256", originalHash);
                    }
                    catch { keepBackup = true; throw new IOException("工作区保护快照登记失败，尚未开始移除程序；原清单备份保留在：" + backup); }
                }
                context.WorkspaceSnapshotReady = false; context.WorkspaceSnapshot.Clear(); throw;
            }
            finally
            {
                foreach (string file in new string[] { temporary, backup })
                    if (!keepBackup || file != backup)
                        try { UninstallRegistration.PlainPath(file); File.Delete(file); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            }
        }
        internal static void CollectData(string folder, List<string> protectedFolders, List<string> files, List<string> directories)
        { CollectData(folder, new UninstallProtectionIndex(protectedFolders), files, directories, new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase), null); }
        private static void CollectData(string folder, UninstallProtectionIndex protection, List<string> files, List<string> directories, Dictionary<string, string> pending, Action found)
        {
            if (protection.Within(folder)) return;
            TryItem(folder, pending, delegate {
                if (!Exists(folder)) return;
                UninstallRegistration.PlainPath(folder);
                foreach (string entry in Directory.EnumerateFileSystemEntries(Package.Extended(folder)))
                {
                    if (found != null) found();
                    string path = entry.StartsWith(@"\\?\") ? entry.Substring(4) : entry;
                    if (protection.Within(path)) continue;
                    TryItem(path, pending, delegate {
                        FileAttributes attributes = File.GetAttributes(entry);
                        if ((attributes & FileAttributes.ReparsePoint) != 0) return;
                        if ((attributes & FileAttributes.Directory) != 0) CollectData(path, protection, files, directories, pending, found); else files.Add(path);
                    });
                }
                directories.Add(folder);
            });
        }
        private static bool WithinProtected(string path, List<string> protectedFolders)
        {
            foreach (string folder in protectedFolders) if (UninstallRegistration.Under(path, folder)) return true;
            return false;
        }
        private static bool Exists(string path)
        {
            try { File.GetAttributes(Package.Extended(path)); return true; }
            catch (FileNotFoundException) { return false; }
            catch (DirectoryNotFoundException) { return false; }
        }
        internal static bool TryItem(string path, Dictionary<string, string> pending, Action action)
        { return TryItem(path, pending, action, false); }
        internal static bool TryItem(string path, Dictionary<string, string> pending, Action action, bool retrySharing)
        {
            try { action(); return true; }
            catch (FileNotFoundException) { return true; }
            catch (DirectoryNotFoundException) { return true; }
            catch (UnauthorizedAccessException) { pending[path] = "Access denied; preserved"; return false; }
            catch (IOException error) { if (retrySharing && UninstallRetryQueue.SharingViolation(error)) throw; pending[path] = "File in use, unsafe path, or temporarily inaccessible; preserved"; return false; }
            catch (System.Security.SecurityException) { pending[path] = "The current user lacks access; preserved"; return false; }
        }
        private static UninstallPendingException Pending(UninstallContext context, Dictionary<string, string> pending)
        {
            StringBuilder all = new StringBuilder("Removable items were processed. The following items remain. The uninstall entry and registration were preserved; close programs using the files and retry.\r\n");
            List<string> paths = new List<string>(pending.Keys); paths.Sort(StringComparer.OrdinalIgnoreCase);
            foreach (string path in paths) all.Append(path).Append(" — ").Append(pending[path]).Append("\r\n");
            string report = UninstallRegistration.Child(context.Root, "installer/deepsteam-uninstall-retained.txt");
            bool saved = false;
            try { UninstallRegistration.PlainPath(report); Directory.CreateDirectory(Path.GetDirectoryName(report)); File.WriteAllText(Package.Extended(report), all.ToString(), new UTF8Encoding(false)); saved = true; }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            catch (System.Security.SecurityException) { }
            StringBuilder visible = new StringBuilder("Removable items were processed. There are " + pending.Count + " pending items. The uninstall entry and registration were preserved.\r\nClose programs using the files, then click Retry uninstall. Imported attachments and workspaces remain preserved.\r\n\r\n");
            for (int index = 0; index < Math.Min(paths.Count, 8); index++) visible.Append(paths[index]).Append(" — ").Append(pending[paths[index]]).Append("\r\n");
            if (saved) visible.Append("\r\nComplete remaining-items report: ").Append(report);
            else if (paths.Count > 8) visible.Append("There are ").Append(paths.Count - 8).Append(" additional items. The remaining-items report could not be written. Restore access, then retry.");
            return new UninstallPendingException(visible.ToString()) { PendingCount = pending.Count };
        }
        internal static void CheckUnlocked(string path)
        {
            // Shared readers that permit deletion are fine. Only Win32 sharing /
            // lock violations receive a bounded queue retry; access denial never
            // waits per file and never changes permissions or readonly attributes.
            UninstallRegistration.PlainPath(path);
            using (SafeFileHandle check = CreateFile(Package.Extended(path), 0x00010000, 7, IntPtr.Zero, 3, 0, IntPtr.Zero))
                if (check.IsInvalid)
                {
                    int code = Marshal.GetLastWin32Error(); if (code == 2 || code == 3) return;
                    Win32Exception error = new Win32Exception(code);
                    if (code == 5) throw new UnauthorizedAccessException("The current user lacks delete permission. The file was preserved.", error);
                    throw new IOException("The file cannot be removed yet. Close programs using it, then retry.", error);
                }
        }
        internal static void TryEmpty(string folder)
        {
            if (!Exists(folder)) return;
            UninstallRegistration.PlainPath(folder);
            using (IEnumerator<string> entries = Directory.EnumerateFileSystemEntries(Package.Extended(folder)).GetEnumerator())
                if (entries.MoveNext()) return;
            Directory.Delete(Package.Extended(folder), false);
        }
        private static string FinalPath(string folder)
        {
            using (SafeFileHandle handle = CreateFile(Package.Extended(folder), 0, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero))
            {
                if (handle.IsInvalid) throw new IOException("The dependency link could not be verified.");
                StringBuilder value = new StringBuilder(32768); uint length = GetFinalPathNameByHandle(handle, value, (uint)value.Capacity, 0);
                if (length == 0 || length >= value.Capacity) throw new IOException("The dependency link target could not be verified.");
                string path = value.ToString(); return path.StartsWith(@"\\?\") ? path.Substring(4).TrimEnd('\\') : path.TrimEnd('\\');
            }
        }
        private static void RemoveShortcuts(UninstallContext context)
        {
            object shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            try
            {
                List<string> paths = new List<string>();
                string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                foreach (string pattern in new string[] { "DeepSteam*.lnk", "Stop DeepSteam*.lnk" }) paths.AddRange(Directory.GetFiles(desktop, pattern));
                string menu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "DeepSteam-" + context.Id.Substring(0, 8));
                paths.Add(Path.Combine(menu, "Uninstall DeepSteam.lnk"));
                foreach (string file in paths)
                {
                    if (!File.Exists(file)) continue; UninstallRegistration.PlainPath(file);
                    object link = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { file });
                    try
                    {
                        string target = (string)link.GetType().InvokeMember("TargetPath", BindingFlags.GetProperty, null, link, null);
                        string arguments = (string)link.GetType().InvokeMember("Arguments", BindingFlags.GetProperty, null, link, null);
                        bool match = String.Equals(target, Path.Combine(context.Root, "DeepSteam.exe"), StringComparison.OrdinalIgnoreCase) && (arguments == "--launch" || arguments == "--stop");
                        match = match || (String.Equals(target, Path.Combine(context.Root, "Uninstall-DeepSteam.exe"), StringComparison.OrdinalIgnoreCase) && String.Equals(file, Path.Combine(menu, "Uninstall DeepSteam.lnk"), StringComparison.OrdinalIgnoreCase));
                        if (match) File.Delete(file);
                    }
                    finally { if (Marshal.IsComObject(link)) Marshal.FinalReleaseComObject(link); }
                }
                TryEmpty(menu);
            }
            finally { if (Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell); }
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr security, uint disposition, uint flags, IntPtr template);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint GetFinalPathNameByHandle(SafeFileHandle handle, StringBuilder value, uint count, uint flags);
    }

    internal sealed class KillJob : IDisposable
    {
        private IntPtr handle;
        internal KillJob()
        {
            handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            limits.BasicLimitInformation.LimitFlags = 0x00002000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            int size = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            IntPtr pointer = Marshal.AllocHGlobal(size);
            try
            {
                Marshal.StructureToPtr(limits, pointer, false);
                if (!SetInformationJobObject(handle, 9, pointer, (uint)size)) throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            catch { Dispose(); throw; }
            finally { Marshal.FreeHGlobal(pointer); }
        }

        internal void Add(Process process)
        {
            if (!AssignProcessToJobObject(handle, process.Handle)) throw new Win32Exception(Marshal.GetLastWin32Error(), "A safely cancelable installation process could not be created.");
        }

        public void Dispose()
        {
            if (handle == IntPtr.Zero) return;
            CloseHandle(handle);
            handle = IntPtr.Zero;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS
        {
            public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
            public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);
    }
}
