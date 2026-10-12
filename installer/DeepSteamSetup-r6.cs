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
        internal const string Version = "2026.10.12-r7-harness-tools";
        internal const string InstallingMarker = ".deepsteam-installing";
        internal const string InstalledMarker = ".deepsteam-installed";

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
                    if (args.Length < 2) throw new ArgumentException("An installation directory is required.");
                    string root = Path.GetFullPath(args[1]).TrimEnd('\\');
                    if (!Path.IsPathRooted(args[1]) || root.StartsWith("\\\\") || root.Length <= 3)
                        throw new IOException("Choose a dedicated absolute path on a local drive.");
                    if (root.Length > 100) throw new IOException("The installation path is too long. Choose a shorter dedicated directory.");
                    Package.EnsureNoReparsePoint(root);
                    bool resume = args[0] == "--resume-install-to";
                    if (resume)
                    {
                        string marker = Path.Combine(root, InstallingMarker);
                        if (!Directory.Exists(root) || !File.Exists(marker) ||
                            File.Exists(Path.Combine(root, InstalledMarker)) ||
                            File.ReadAllText(marker, Encoding.UTF8).Trim() != "DeepSteam " + Version)
                            throw new IOException("Resume is only available for an unfinished installation of this version in its dedicated directory.");
                    }
                    else if (Directory.Exists(root) && Directory.GetFileSystemEntries(root).Length > 0)
                        throw new IOException("Automatic installation requires an empty directory and never overwrites existing content.");
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
                if (process.ExitCode != 0) throw new IOException(name + " exit code " + process.ExitCode);
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
                if (file.Length < 64) throw new InvalidDataException("The installer is incomplete. Download the complete installation files again.");
                file.Seek(-64, SeekOrigin.End);
                byte[] trailer = new byte[64];
                ReadExactly(file, trailer, 0, trailer.Length);
                bool embedded = HasTrailerMagic(trailer);
                if (!embedded)
                {
                    // Windows refuses PE files larger than 4 GiB. Such releases
                    // keep the exact same verified payload next to a small EXE.
                    string companion = Path.ChangeExtension(Application.ExecutablePath, ".payload.dat");
                    if (!File.Exists(companion)) throw new InvalidDataException("The installer payload is missing. Keep the EXE and matching payload.dat in the same folder.");
                    file.Dispose();
                    file = new FileStream(companion, FileMode.Open, FileAccess.Read,
                        FileShare.Read, 128 * 1024, FileOptions.SequentialScan);
                    if (file.Length < 64) throw new InvalidDataException("The companion payload file is incomplete.");
                    file.Seek(-64, SeekOrigin.End);
                    ReadExactly(file, trailer, 0, trailer.Length);
                }
                for (int i = 0; i < TrailerMagic.Length; i++)
                    if (trailer[i] != TrailerMagic[i]) throw new InvalidDataException("The bundled payload is missing. Download the complete installation files again.");
                long offset = BitConverter.ToInt64(trailer, 16);
                long length = BitConverter.ToInt64(trailer, 24);
                if (offset < (embedded ? 1 : 0) || length < 22 || offset > file.Length - 64 || length != file.Length - 64 - offset)
                    throw new InvalidDataException("The payload offset or length is invalid. Download the complete installation files again.");
                PayloadSegmentStream stream = new PayloadSegmentStream(file, offset, length);
                if (!payloadHashVerified)
                {
                    byte[] actual;
                    using (SHA256 sha = SHA256.Create()) actual = sha.ComputeHash(stream);
                    int difference = 0;
                    for (int i = 0; i < actual.Length; i++) difference |= actual[i] ^ trailer[32 + i];
                    if (difference != 0) throw new InvalidDataException("Installer integrity verification failed. Download the complete installation files again.");
                    payloadHashVerified = true;
                }
                stream.Position = 0;
                return stream;
            }
            catch { file.Dispose(); throw; }
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
                if (read == 0) throw new EndOfStreamException("The installer is truncated.");
                offset += read; count -= read;
            }
        }

        internal static string EntryPath(string name)
        {
            string normalized = name.Replace('\\', '/');
            if (String.IsNullOrEmpty(normalized) || normalized.StartsWith("/") || normalized.IndexOf(':') >= 0 || normalized.IndexOf('\0') >= 0)
                throw new InvalidDataException("The installer contains an unsafe file path.");
            string[] parts = normalized.Split('/');
            for (int i = 0; i < parts.Length; i++)
            {
                string part = parts[i];
                if (part == ".." || part == "." || (part.Length == 0 && i != parts.Length - 1) ||
                    part.EndsWith(".") || part.EndsWith(" ") || part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                    throw new InvalidDataException("The installer contains an unsafe file path.");
                string stem = part.Split('.')[0].ToUpperInvariant();
                if (Regex.IsMatch(stem, "^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$"))
                    throw new InvalidDataException("The installer contains a reserved Windows filename.");
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
                    if (!names.Add(normalized.TrimEnd('/'))) throw new InvalidDataException("The installer contains a duplicate file path.");
                    if ((entry.ExternalAttributes >> 16 & 0xF000) == 0xA000)
                        throw new InvalidDataException("The installer cannot contain symbolic links.");
                    if (!normalized.EndsWith("/")) { summary.Files++; checked { summary.Bytes += entry.Length; } }
                }
            }
            foreach (string required in Required)
                if (!names.Contains(required)) throw new InvalidDataException("The installer is missing " + required);
            if (summary.Files == 0) throw new InvalidDataException("The installer payload is empty.");
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
                if (manifest == null || manifest.Length > 64 * 1024 * 1024) throw new IOException("The public file manifest is missing from the installer.");
                string expected;
                using (Stream input = manifest.Open())
                using (SHA256 sha = SHA256.Create()) expected = BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
                if (UninstallRegistration.Sha(Path.Combine(root, "installer", "payload-manifest.json")) != expected)
                    throw new IOException("The installation manifest does not match this installer.");
            }
        }

        internal static void EnsureNoReparsePoint(string path)
        {
            DirectoryInfo current = new DirectoryInfo(Extended(path));
            while (current != null)
            {
                if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("The installation path cannot pass through symbolic links or directory junctions. Choose a regular folder.");
                current = current.Parent;
            }
        }

        internal static void EnsureDiskSpace(string root, long bytes)
        {
            DriveInfo drive = new DriveInfo(Path.GetPathRoot(root));
            if (!drive.IsReady) throw new IOException("The installation drive is not ready.");
            if (!String.Equals(drive.DriveFormat, "NTFS", StringComparison.OrdinalIgnoreCase))
                throw new IOException("Choose an NTFS drive. Application dependencies use directory junctions and the payload may exceed 4 GB.");
            long required = checked(bytes + 512L * 1024L * 1024L);
            if (drive.AvailableFreeSpace < required)
                throw new IOException("Not enough disk space. At least " + ((required + 1073741823L) / 1073741824L) + " GB of free space is required.");
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
                        throw new InvalidDataException("An installation file path escapes the destination folder.");
                    string folder = relative.EndsWith(Path.DirectorySeparatorChar.ToString()) ? target : Path.GetDirectoryName(target);
                    EnsureNoReparsePoint(folder);
                    Directory.CreateDirectory(Extended(folder));
                    if (relative.EndsWith(Path.DirectorySeparatorChar.ToString())) continue;
                    string extendedTarget = Extended(target);
                    if (File.Exists(extendedTarget))
                    {
                        if ((File.GetAttributes(extendedTarget) & FileAttributes.ReparsePoint) != 0)
                            throw new IOException("The destination contains a file link. Choose a new installation directory.");
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
                                if (output.Length != entry.Length) throw new InvalidDataException("The extracted file length does not match the manifest.");
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
        internal static readonly Color Paper = Color.FromArgb(26, 25, 24);
        internal static readonly Color Panel = Color.FromArgb(36, 34, 32);
        internal static readonly Color Ink = Color.FromArgb(238, 234, 226);
        internal static readonly Color Muted = Color.FromArgb(170, 163, 154);
        internal static readonly Color Accent = Color.FromArgb(212, 115, 75);
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
        private bool hovered;
        private bool pressed;
        internal SetupButton()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            Cursor = Cursors.Hand;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Padding = new Padding(15, 9, 15, 9);
            UseVisualStyleBackColor = false;
        }
        protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hovered = pressed = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { pressed = true; Invalidate(); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { pressed = false; Invalidate(); base.OnMouseUp(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Parent == null ? SetupTheme.Paper : Parent.BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            Color fill = Primary ? SetupTheme.Accent : SetupTheme.Paper;
            if (!Enabled) fill = SetupTheme.Panel;
            else if (pressed) fill = Primary ? Color.FromArgb(186, 91, 48) : Color.FromArgb(52, 48, 43);
            else if (hovered) fill = Primary ? Color.FromArgb(229, 133, 84) : SetupTheme.Panel;
            using (GraphicsPath path = SetupTheme.Round(new RectangleF(0.5F, 0.5F, Width - 1, Height - 1), 9 * e.Graphics.DpiX / 96))
            using (Brush brush = new SolidBrush(fill))
            using (Pen pen = new Pen(Primary && Enabled ? fill : SetupTheme.Line))
            { e.Graphics.FillPath(brush, path); e.Graphics.DrawPath(pen, path); }
            Color text = !Enabled ? Color.FromArgb(112, 106, 98) : Primary ? Color.FromArgb(28, 22, 18) : SetupTheme.Ink;
            TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, text, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -6, -6), text, fill);
        }
    }

    internal sealed class SetupProgress : Control
    {
        private int value;
        private ProgressBarStyle style;
        internal double Phase;
        internal bool Failed;
        internal int Value { get { return value; } set { this.value = value; Invalidate(); } }
        internal ProgressBarStyle Style { get { return style; } set { style = value; Invalidate(); } }
        internal SetupProgress()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            AccessibleName = "Operation progress";
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
                float left = 0, width = Width * value / 100F;
                if (style == ProgressBarStyle.Marquee)
                {
                    width = Width * 0.30F;
                    left = SetupTheme.Motion ? (float)((Math.Sin(Phase * 1.45 - Math.PI / 2) + 1) / 2 * (Width - width)) : (Width - width) / 2;
                }
                if (width > 0)
                    using (GraphicsPath bar = SetupTheme.Round(new RectangleF(left, 0, Math.Max(1, width), Height), Height / 2F))
                    using (Brush accent = new SolidBrush(Failed ? Color.FromArgb(173, 69, 59) : SetupTheme.Accent))
                        e.Graphics.FillPath(accent, bar);
                e.Graphics.ResetClip();
            }
        }
    }

    internal sealed class SetupCheckBox : CheckBox
    {
        internal SetupCheckBox()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            Cursor = Cursors.Hand;
            UseVisualStyleBackColor = false;
        }
        public override Size GetPreferredSize(Size proposedSize)
        {
            Size text = TextRenderer.MeasureText(Text, Font);
            return new Size(text.Width + text.Height + (int)Math.Ceiling(text.Height * 0.55), text.Height + 6);
        }
        protected override void OnCheckedChanged(EventArgs e) { Invalidate(); base.OnCheckedChanged(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Parent == null ? SetupTheme.Panel : Parent.BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            float scale = e.Graphics.DpiX / 96;
            float size = Math.Min(16 * scale, Height - 4);
            RectangleF box = new RectangleF(0.5F, (Height - size) / 2, size, size);
            using (GraphicsPath path = SetupTheme.Round(box, 4 * scale))
            using (Brush fill = new SolidBrush(Checked && Enabled ? SetupTheme.Accent : SetupTheme.Paper))
            using (Pen border = new Pen(Checked && Enabled ? SetupTheme.Accent : SetupTheme.Line))
            {
                e.Graphics.FillPath(fill, path);
                e.Graphics.DrawPath(border, path);
            }
            if (Checked)
            {
                using (Pen tick = new Pen(Enabled ? SetupTheme.Paper : SetupTheme.Muted, 1.8F * scale))
                {
                    tick.StartCap = tick.EndCap = LineCap.Round;
                    e.Graphics.DrawLines(tick, new PointF[] { new PointF(box.X + size * 0.24F, box.Y + size * 0.52F), new PointF(box.X + size * 0.44F, box.Y + size * 0.71F), new PointF(box.X + size * 0.78F, box.Y + size * 0.3F) });
                }
            }
            Rectangle text = new Rectangle((int)(size + 8 * scale), 0, Math.Max(0, Width - (int)(size + 8 * scale)), Height);
            TextRenderer.DrawText(e.Graphics, Text, Font, text, Enabled ? SetupTheme.Ink : SetupTheme.Muted, TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, text);
        }
    }

    internal sealed class SetupHero : Control
    {
        internal double Phase;
        internal SetupHero()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            AccessibleName = "DeepSteam · Keep curiosity growing.";
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
                TextRenderer.DrawText(g, "Keep curiosity growing.", tagline, new Point(0, (int)(89 * scale)), SetupTheme.Muted);
            }
            if (Width < 530 * scale) return;
            float cx = Width - 85 * scale, cy = 63 * scale;
            g.TranslateTransform(cx, cy);
            using (Brush halo = new SolidBrush(Color.FromArgb(45, 35, 29))) g.FillEllipse(halo, -58 * scale, -58 * scale, 116 * scale, 116 * scale);
            for (int i = 0; i < 3; i++)
            {
                GraphicsState transform = g.Save();
                g.RotateTransform((float)(-34 + i * 62 + Math.Sin(Phase * 0.3) * 5));
                using (Pen ring = new Pen(i == 1 ? Color.FromArgb(119, 80, 57) : Color.FromArgb(69, 58, 46), 1.2F * scale))
                    g.DrawEllipse(ring, -69 * scale, -26 * scale, 138 * scale, 52 * scale);
                g.Restore(transform);
            }
            using (Pen steam = new Pen(SetupTheme.Accent, 3.1F * scale))
            {
                steam.StartCap = steam.EndCap = LineCap.Round;
                for (int i = -1; i <= 1; i++)
                {
                    float x = i * 13 * scale, sway = (float)Math.Sin(Phase * 0.65 + i * 0.8) * 2 * scale;
                    g.DrawBezier(steam, x, 23 * scale, x - 18 * scale + sway, 4 * scale, x + 18 * scale + sway, -7 * scale, x, -25 * scale);
                }
            }
            double angle = Phase * 0.24 - 0.8;
            using (Brush dot = new SolidBrush(SetupTheme.Accent)) g.FillEllipse(dot, (float)Math.Cos(angle) * 64 * scale - 3 * scale, (float)Math.Sin(angle) * 44 * scale - 3 * scale, 6 * scale, 6 * scale);
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
        private readonly string[] tips = { "Connect your chosen model and turn questions into understanding.", "Open a folder and make your materials the starting point for learning.", "Continue conversations, practice, and review in one workspace.", "Expand operation details whenever you need diagnostics." };
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
            startupAction = action;
            Text = "DeepSteam · Install and launch";
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
            Label directoryLabel = MakeLabel("Your learning space starts here", 12F, true);
            directoryLabel.Margin = new Padding(0, 0, 0, 7);
            settings.Controls.Add(directoryLabel, 0, 0);
            Label directoryHint = MakeLabel("Installation directory · Choose a dedicated folder on a fixed local drive", 9F, false);
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
            directory.AccessibleName = "DeepSteam installation directory";
            directory.Text = DefaultRoot();
            directory.TextChanged += delegate { UpdateButtons(); };
            input.Controls.Add(directory);
            ConfigureButton(browse, "Choose folder", 108);
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
            shortcuts.Text = "Create desktop shortcuts";
            shortcuts.Checked = true;
            shortcuts.AutoSize = true;
            shortcuts.Margin = new Padding(0, 0, 24, 0);
            openAfter.Text = "Open DeepSteam after installation";
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
            ConfigureButton(install, "Install DeepSteam", 152);
            ((SetupButton)install).Primary = true;
            ConfigureButton(start, "Open app", 106);
            ConfigureButton(stop, "Stop services", 106);
            ConfigureButton(cancel, "Cancel installation", 106);
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
            phaseLabel.Text = "Ready";
            phaseLabel.Font = new Font(Font, FontStyle.Bold);
            phaseLabel.AutoSize = true;
            phaseLabel.Margin = new Padding(0, 0, 0, 7);
            progressValue.AutoSize = true;
            progressValue.ForeColor = SetupTheme.Muted;
            progressValue.Margin = Padding.Empty;
            statusLayout.Controls.Add(phaseLabel, 0, 0);
            statusLayout.Controls.Add(progressValue, 1, 0);
            state.Text = "Choose an installation directory to begin. The runtime and document tools are included.";
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
            details.Text = "Show operation details +";
            details.AutoSize = true;
            details.LinkColor = details.ActiveLinkColor = SetupTheme.Muted;
            details.LinkBehavior = LinkBehavior.HoverUnderline;
            details.Margin = new Padding(0, 2, 0, 8);
            details.LinkClicked += delegate { SetDetails(!detailsPanel.Visible); };
            copyLog.Text = "Copy details";
            copyLog.AutoSize = true;
            copyLog.Visible = false;
            copyLog.LinkColor = copyLog.ActiveLinkColor = SetupTheme.Muted;
            copyLog.LinkBehavior = LinkBehavior.HoverUnderline;
            copyLog.LinkClicked += delegate { try { if (output.TextLength > 0) Clipboard.SetText(output.Text); } catch (ExternalException) { state.Text = "Copy failed. Try again or select the text in the details panel."; } };
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
            output.AccessibleName = "Operation details for diagnostics";
            detailsPanel.Controls.Add(output);
            diagnostics.Controls.Add(detailsPanel, 0, 1);
            diagnostics.SetColumnSpan(detailsPanel, 2);
            layout.Controls.Add(diagnostics, 0, 4);
            Label version = MakeLabel("WINDOWS  ·  " + Program.Version, 8F, false);
            version.ForeColor = SetupTheme.Muted;
            version.Margin = new Padding(0, 16, 0, 0);
            layout.Controls.Add(version, 0, 5);

            animation.Interval = 40;
            animation.Tick += delegate
            {
                if (!Visible || WindowState == FormWindowState.Minimized) return;
                double elapsed = motionClock.Elapsed.TotalSeconds;
                if (SetupTheme.Motion)
                {
                    hero.Phase = progress.Phase = elapsed;
                    hero.Invalidate();
                    if (progress.Style == ProgressBarStyle.Marquee) progress.Invalidate();
                    int next = (int)(elapsed / 4.2) % tips.Length;
                    if (busy && next != tipIndex) { tipIndex = next; tip.Text = tips[next]; }
                }
                if (!busy && elapsed > 2.4) animation.Stop();
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
                if (IsComplete(directory.Text)) { phaseLabel.Text = "Ready when you are"; state.Text = "DeepSteam is installed. Open the app and continue learning."; }
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
            details.Text = visible ? "Hide operation details -" : "Show operation details +";
        }

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

        private void ApplyDarkTitleBar()
        {
            // Older Windows versions simply retain the system title bar.
            try
            {
                int enabled = 1;
                if (DwmSetWindowAttribute(Handle, 20, ref enabled, sizeof(int)) != 0)
                    DwmSetWindowAttribute(Handle, 19, ref enabled, sizeof(int));
                int caption = ColorTranslator.ToWin32(SetupTheme.Paper);
                DwmSetWindowAttribute(Handle, 35, ref caption, sizeof(int));
                int text = ColorTranslator.ToWin32(SetupTheme.Ink);
                DwmSetWindowAttribute(Handle, 36, ref text, sizeof(int));
            }
            catch (DllNotFoundException) { }
            catch (EntryPointNotFoundException) { }
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
                picker.Description = "Choose a dedicated DeepSteam installation folder. Existing personal files will not be overwritten.";
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
            install.Text = resumable ? "Resume installation" : "Install DeepSteam";
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
                throw new IOException("Choose a dedicated folder on a local drive, not a drive root or network share.");
            if (root.Length > 100) throw new IOException("The installation path is too long. Choose a shorter dedicated directory.");
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
                    throw new IOException("This folder already contains files. Choose a new dedicated DeepSteam directory; existing content will not be overwritten.");
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
                    throw new IOException("Installation is unfinished at this location. Click Install or Resume installation first.");
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
            progressValue.Text = "In progress";
            phaseLabel.ForeColor = SetupTheme.Ink;
            phaseLabel.Text = isInstall ? "Checking installer" : action == "stop" ? "Stopping" : "Preparing to launch";
            state.Text = isInstall ? "Verifying installer integrity before extraction." : action == "stop" ? "Stopping local services safely. Please wait." : "Checking the local runtime and opening the desktop window.";
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
                SetStatus("Extracting the application, runtime, and document tools into the selected folder.", false);
                Package.Extract(op.Root, Log, SetProgress, delegate { return cancelled; });
                if (cancelled) throw new OperationCanceledException();
                CopyLauncher(op.Root);
                SetStatus("Verifying and configuring the runtime. The first installation may take a few minutes.", true);
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
            if (!File.Exists(script)) throw new FileNotFoundException("A launch file is missing. Check the installation package.", scriptName);
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
                    if (process.ExitCode != 0) throw new IOException("Operation failed (exit code " + process.ExitCode + "). Expand operation details. Completed files are preserved so installation can resume.");
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
            state.Text = "Stopping installation. Completed files are preserved so you can resume later.";
            phaseLabel.Text = "Canceling";
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
                state.Text = "Installation canceled. Select the same folder to resume. Existing files were not deleted.";
                phaseLabel.Text = "Installation paused";
                progressValue.Text = "Canceled";
                tip.Text = "Completed files are preserved. You can resume later.";
                Log(state.Text);
            }
            else if (e.Error != null) ShowError(e.Error.Message);
            else
            {
                progress.Value = 100;
                string action = e.Result as string;
                state.Text = action == "install" ? "DeepSteam is installed. Open the app to start learning." : action == "stop" ? "Local services are stopped. Reopen DeepSteam from the desktop when ready." : "The DeepSteam desktop window is open. Service startup progress will continue there.";
                phaseLabel.Text = action == "install" ? "Installation complete" : action == "stop" ? "Safely stopped" : "Desktop window opened";
                progressValue.Text = "Complete";
                tip.Text = action == "stop" ? "Your learning records stay in place for your next session." : "Keep curiosity growing.";
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
            if (installing && MessageBox.Show(this, "Installation is still running. Cancel and close? Completed files will be preserved.", "DeepSteam", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            {
                closeAfterCancel = true;
                CancelInstall();
            }
            else if (!installing) state.Text = "Wait for the current launch or stop operation to finish.";
        }

        private void SetProgress(int value)
        {
            UI(delegate { progress.Style = ProgressBarStyle.Continuous; progress.Value = Math.Max(0, Math.Min(100, value)); progressValue.Text = progress.Value + "%"; phaseLabel.Text = "Extracting"; });
        }

        private void SetStatus(string message, bool indeterminate)
        {
            UI(delegate { state.Text = message; phaseLabel.Text = indeterminate ? "Configuring runtime" : "Extracting"; progressValue.Text = indeterminate ? "In progress" : "0%"; progress.Style = indeterminate ? ProgressBarStyle.Marquee : ProgressBarStyle.Continuous; });
        }

        private void ShowError(string message)
        {
            state.Text = "Incomplete: " + message;
            phaseLabel.Text = "Action required";
            phaseLabel.ForeColor = Color.FromArgb(231, 140, 124);
            progress.Failed = true;
            progressValue.Text = "Incomplete";
            tip.Text = "See the details below. Existing files and learning records are preserved.";
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
                MakeShortcut(shell, Path.Combine(desktop, "DeepSteam.lnk"), root, "--launch", "Launch the DeepSteam learning agent");
                MakeShortcut(shell, Path.Combine(desktop, "Stop DeepSteam.lnk"), root, "--stop", "Stop DeepSteam local services");
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
                type.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { Path.Combine(root, "DeepSteam.exe") + ",0" });
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
            foreach (string prefix in new string[] { "data", "logs", "cache", "reports", "runtime/temp", "runtime/deeptutor-home", "runtime/harness-state", "runtime/openmaic-standalone/data", "upstream/openmaic/data" })
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
            File.Copy(Application.ExecutablePath, executable, false);
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
        internal static void Write(UninstallContext context)
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
            File.WriteAllText(context.Manifest, data.ToString(), new UTF8Encoding(false));
            File.WriteAllText(Path.Combine(context.Root, IdName), context.Id, new UTF8Encoding(false));
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(RegistryName(context.Id)))
            {
                key.SetValue("DisplayName", "DeepSteam Learning Agent"); key.SetValue("Publisher", "DeepSteam");
                key.SetValue("DisplayVersion", context.Version); key.SetValue("InstallLocation", context.Root);
                key.SetValue("DisplayIcon", Path.Combine(context.Root, "DeepSteam.exe"));
                key.SetValue("UninstallString", InstallerForm.Quote(Path.Combine(context.Root, "Uninstall-DeepSteam.exe")));
                key.SetValue("InstallationId", context.Id); key.SetValue("ManifestSha256", Sha(context.Manifest));
                key.SetValue("NoModify", 1, RegistryValueKind.DWord); key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }
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
                type.InvokeMember("IconLocation", BindingFlags.SetProperty, null, link, new object[] { Path.Combine(root, "Uninstall-DeepSteam.exe") + ",0" });
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
            foreach (string file in new string[] { "main.cjs", "preload.cjs", "policy.cjs", "transport.cjs", "storage-migration.cjs", "oauth-placeholder.cjs", "starting.html", "package.json" })
                if (value == "desktop/" + file) return true;
            foreach (string prefix in new string[] { "portal/", "integration/", "scripts/", "installer/", "licenses/", "upstream/",
                "runtime/python/", "runtime/deeptutor-packages/", "runtime/native-frontends/", "runtime/openmaic-standalone/",
                "runtime/desktop/", "runtime/harness/", "runtime/node/", "runtime/mineru/" })
                if (value.StartsWith(prefix, StringComparison.Ordinal)) return true;
            return value == "runtime/native-frontend.json" || value == "runtime/openmaic-frontend.json" ||
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
        internal static void Refresh(string root, string receiptPath, string receiptHash, string report, bool dryRun)
        {
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
            try
            {
                foreach (string relative in ownNames)
                {
                    string file = UninstallRegistration.Child(root, relative);
                    if (relative == Program.InstalledMarker)
                        File.WriteAllText(file, "DeepSteam " + next.Version + "\r\n" + DateTime.UtcNow.ToString("o"), new UTF8Encoding(false));
                    else File.Copy(Application.ExecutablePath, file, true);
                    next.Files.RemoveAll(delegate(UninstallFile row) { return String.Equals(row.Path, relative, StringComparison.OrdinalIgnoreCase); });
                    next.Files.Add(new UninstallFile { Path = relative, Hash = UninstallRegistration.Sha(file), Bytes = new FileInfo(file).Length });
                }
                UninstallRegistration.Write(next);
                UninstallRegistration.CreateUninstallShortcut(root);
                Check(root, report);
            }
            catch
            {
                foreach (KeyValuePair<string, byte[]> item in originals)
                    File.WriteAllBytes(UninstallRegistration.Child(root, item.Key), item.Value);
                UninstallRegistration.Write(previous);
                throw;
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
                    UninstallFile record = context.Files.Find(delegate(UninstallFile row) { return row.Path == "Uninstall-DeepSteam.exe"; });
                    if (new FileInfo(source).Length > 4 * 1024 * 1024 || UninstallRegistration.Sha(source) != record.Hash)
                        throw new IOException("The uninstaller was modified. Download the installation package again.");
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
            catch (Exception ex) { MessageBox.Show(ex.Message, "DeepSteam uninstall incomplete", MessageBoxButtons.OK, MessageBoxIcon.Warning); return 1; }
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
        private string phase = "verify", message = "Verifying uninstall registration...";
        private long completed, attempted, total = -1, pending, retained, bytes;
        internal UninstallProgressReporter(Action<UninstallProgress> sink, int run) : this(sink, run, ProductionClock()) { }
        internal UninstallProgressReporter(Action<UninstallProgress> sink, int run, Func<long> now)
        { publish = sink; runId = run; clock = now; started = clock(); lastRateTime = lastAdvance = started; }
        private static Func<long> ProductionClock() { Stopwatch watch = Stopwatch.StartNew(); return delegate { return watch.ElapsedMilliseconds; }; }
        internal void Phase(string value, string text, long count)
        { phase = value; message = text; total = count; completed = attempted = 0; rates.Clear(); lastRateTime = lastAdvance = clock(); lastRateCompleted = 0; Emit(true); }
        internal void Finalizing()
        { phase = "finalize"; message = "Finalizing uninstall entries and registration..."; rates.Clear(); Emit(true); }
        internal void Counts(long done, long tried, long blocked, long kept)
        { if (done != completed) lastAdvance = clock(); completed = done; attempted = tried; pending = blocked; retained = kept; Emit(false); }
        internal void ReadBytes(int count) { bytes += count; Emit(false); }
        internal void Discovered(long count) { attempted = count; Emit(false); }
        internal void Waiting(string text) { message = text; rates.Clear(); lastRateTime = clock(); lastRateCompleted = completed; Emit(true); }
        internal void Complete()
        { if (pending != 0 || total < 1) throw new InvalidOperationException("Pending items remain. Uninstallation cannot be reported as complete."); completed = attempted = total; phase = "complete"; message = "Uninstall complete"; Emit(true); }
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
        private readonly CheckBox removeData = new CheckBox();
        private readonly SetupButton start = new SetupButton { Primary = true };
        private readonly SetupButton cancel = new SetupButton();
        private readonly SetupProgress progress = new SetupProgress();
        private readonly System.Windows.Forms.Timer progressAnimation = new System.Windows.Forms.Timer { Interval = 30 };
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
            testNoDialog = testNoDialogValue; context = value; Text = "Uninstall DeepSteam";
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
            Label title = TextBlock("Uninstall DeepSteam", SetupTheme.Ink, 0, 18);
            title.Font = new Font(Font.FontFamily, 19, FontStyle.Bold);
            Label description = TextBlock("Remove the app and preserve your learning content.\r\nLearning records, model settings, imported files, and workspaces are kept by default.", SetupTheme.Ink, 0, 22);
            Label path = TextBlock("Version: " + context.Version + "\r\nInstallation directory: " + context.Root, SetupTheme.Muted, 0, 22);
            TableLayoutPanel choice = new TableLayoutPanel { AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Dock = DockStyle.Top,
                ColumnCount = 2, Margin = new Padding(0, 0, 0, 20), Padding = new Padding(16), BackColor = SetupTheme.Panel };
            choice.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize)); choice.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            removeData.Text = ""; removeData.AutoSize = true; removeData.Checked = false; removeData.Margin = new Padding(0, 4, 12, 0);
            removeData.AccessibleName = "Also remove application records, settings, and cache";
            Label choiceText = TextBlock("Also remove application records, settings, and cache", SetupTheme.Ink, 0, 4);
            Label choiceHint = TextBlock("Imported files and workspaces will still be preserved.", SetupTheme.Muted, 0, 0);
            choiceText.Cursor = Cursors.Hand; choiceText.Click += delegate { if (removeData.Enabled) removeData.Checked = !removeData.Checked; };
            choice.Controls.Add(removeData, 0, 0); choice.Controls.Add(choiceText, 1, 0); choice.Controls.Add(choiceHint, 1, 1);
            status.Text = "Confirm to close DeepSteam and remove the application."; status.ForeColor = SetupTheme.Muted;
            status.AutoSize = true; status.Dock = DockStyle.Top; status.Margin = new Padding(0, 0, 0, 12);
            body.Controls.Add(title, 0, 0); body.Controls.Add(description, 0, 1); body.Controls.Add(path, 0, 2); body.Controls.Add(choice, 0, 3); body.Controls.Add(status, 0, 4);
            viewport.Controls.Add(body); outer.Controls.Add(viewport, 0, 0);
            TableLayoutPanel footer = new TableLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
                ColumnCount = 1, Margin = new Padding(0, 16, 0, 0), Padding = Padding.Empty };
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            progress.Dock = DockStyle.Top; progress.Height = 6; progress.Margin = new Padding(0, 0, 0, 12); progress.Style = ProgressBarStyle.Marquee;
            progress.Visible = false;
            progressAnimation.Tick += delegate { if (progress.Style == ProgressBarStyle.Marquee) { progress.Phase += 0.03; progress.Invalidate(); } };
            progressDetails.AutoSize = true; progressDetails.Dock = DockStyle.Top; progressDetails.ForeColor = SetupTheme.Muted;
            progressDetails.Margin = new Padding(0, 0, 0, 12); progressDetails.UseMnemonic = false;
            progressRefresh.Tick += delegate { FlushLatestProgress(); };
            FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
                FlowDirection = FlowDirection.RightToLeft, WrapContents = true, Margin = Padding.Empty, Padding = Padding.Empty, Name = "uninstall-actions" };
            cancel.Text = "Cancel"; cancel.MinimumSize = new Size(100, 44); cancel.Margin = new Padding(0, 0, 12, 0); cancel.Click += delegate { if (!busy) Close(); };
            start.Text = "Uninstall DeepSteam"; start.MinimumSize = new Size(160, 44); start.Margin = Padding.Empty;
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
        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr handle, int attribute, ref int value, int size);
        private void ApplyDarkTitleBar()
        {
            try
            {
                int enabled = 1;
                if (DwmSetWindowAttribute(Handle, 20, ref enabled, sizeof(int)) != 0) DwmSetWindowAttribute(Handle, 19, ref enabled, sizeof(int));
                int caption = ColorTranslator.ToWin32(SetupTheme.Paper), ink = ColorTranslator.ToWin32(SetupTheme.Ink);
                DwmSetWindowAttribute(Handle, 35, ref caption, sizeof(int)); DwmSetWindowAttribute(Handle, 36, ref ink, sizeof(int));
            }
            catch (DllNotFoundException) { }
            catch (EntryPointNotFoundException) { }
        }
        private void Begin()
        {
            if (busy) return;
            if (start.Text == "Close") { Close(); return; }
            busy = true; Failure = null; TestFailureStack = null; start.Enabled = false; cancel.Enabled = false; removeData.Enabled = false; bool deleteData = removeData.Checked;
            ResetProgress(progressRun + 1); progress.Visible = true; if (SetupTheme.Motion) progressAnimation.Start(); progressRefresh.Start();
            UninstallProgressReporter reporter = new UninstallProgressReporter(QueueProgress, progressRun);
            BackgroundWorker worker = new BackgroundWorker();
            worker.DoWork += delegate(object sender, DoWorkEventArgs e)
            {
                reporter.Phase("verify", "Verifying uninstall registration...", -1);
                UninstallContext fresh = UninstallRegistration.Verify(context.Root);
                e.Result = UninstallCore.RemoveWithProgress(fresh, deleteData, delegate(UninstallContext item) { UninstallCore.Stop(item, reporter); }, reporter, true);
            };
            worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs e)
            {
                FlushLatestProgress(); progressRefresh.Stop(); progressAnimation.Stop();
                busy = false; start.Enabled = true; cancel.Enabled = true;
                if (e.Error != null) { status.Text = e.Error is UninstallPendingException ? "Removable items were processed and remaining items were preserved. Close programs using those files, then retry." : "Uninstallation is incomplete. Registration was preserved for retry."; start.Text = "Retry uninstall"; removeData.Enabled = true; Failure = e.Error.Message;
                    UninstallPendingException remaining = e.Error as UninstallPendingException;
                    FinishProgress(false, status.Text, remaining == null ? (long?)null : remaining.PendingCount);
                    if (testNoDialog) TestFailureStack = e.Error.StackTrace;
                    if (!testNoDialog) MessageBox.Show(e.Error.Message, "DeepSteam uninstall incomplete", MessageBoxButtons.OK, MessageBoxIcon.Warning); return; }
                status.Text = (string)e.Result; start.Text = "Close"; FinishProgress(true, status.Text);
            };
            worker.RunWorkerAsync();
        }
        internal void ResetProgress(int run)
        {
            lock (progressGate) { progressRun = run; progressFinished = false; latestProgress = null; lastAppliedProgress = null; }
            progress.Value = 0; progress.Style = ProgressBarStyle.Marquee; progressDetails.Text = "Preparing uninstall · Total not yet known";
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
                    progressDetails.Text = Regex.Replace(progressDetails.Text, "Estimated remaining in this phase: [^\\r\\n]*seconds", "Waiting · Remaining time is not yet available");
                    progressDetails.Text = Regex.Replace(progressDetails.Text, "Elapsed: [0-9]+ seconds", "Elapsed: " + ((lastAppliedProgress.ElapsedMilliseconds + silent) / 1000) + " seconds");
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
            string label = value.Phase == "check" ? "Checking manifest" : value.Phase == "finalize" ? "Finalizing registration" : "Verified items";
            string detail = fixedTotal ? label + " " + value.Percent + "% · Completed " + value.Completed + " / " + value.Total + " items" :
                "Total not yet known" + (value.Phase == "discover" || value.Phase == "workspaces" ? " · Discovered " + value.Attempted + " items" : "");
            if (value.Phase == "remove" || value.Phase == "finalize") detail += " · Attempted " + value.Attempted + " items (including directories and registration)";
            if (value.Pending > 0) detail += " · Pending " + value.Pending + " items";
            if (value.Retained > 0) detail += " · Protected " + value.Retained + " items";
            if (value.Phase == "check") detail += " · Read " + (value.BytesRead / (1024.0 * 1024.0)).ToString("0.0") + " MB";
            detail += "\r\nElapsed: " + (value.ElapsedMilliseconds / 1000) + " seconds · " +
                (value.EtaMinimumSeconds.HasValue ? "Estimated remaining in this phase: " + value.EtaMinimumSeconds.Value.ToString("0") + "–" + value.EtaMaximumSeconds.Value.ToString("0") + " seconds" : "Remaining time is not yet available");
            progressDetails.Text = detail;
        }
        internal void FinishProgress(bool success, string message)
        { FinishProgress(success, message, null); }
        private void FinishProgress(bool success, string message, long? pendingCount)
        {
            lock (progressGate) { progressFinished = true; latestProgress = null; }
            progress.Style = ProgressBarStyle.Continuous; status.Text = message;
            if (success) { progress.Value = 100; progressDetails.Text = "100% · Uninstall complete"; }
            else
            {
                progress.Value = 0; progress.Visible = false;
                string counts = lastAppliedProgress != null && (lastAppliedProgress.Phase == "remove" || lastAppliedProgress.Phase == "finalize") ?
                    " · Completed " + lastAppliedProgress.Completed + " / " + lastAppliedProgress.Total + " items" : "";
                long blocked = pendingCount ?? (lastAppliedProgress == null ? 0 : lastAppliedProgress.Pending);
                if (blocked > 0) counts += " · Pending " + blocked + " items";
                progressDetails.Text = "Incomplete" + counts + " · Remaining items and the retry entry were preserved; remaining time is not yet available";
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
            foreach (Item item in waiting) pending[item.Path] = "File is still in use. It was preserved; close the program using it and retry.";
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
                    if (new FileInfo(file).Length > 4 * 1024 * 1024) throw new IOException("The workspace registration is too large. Data was preserved and uninstallation stopped.");
                    Dictionary<string, object> value = (Dictionary<string, object>)UninstallRegistration.Json(file);
                    if (Convert.ToInt32(value["schema"]) != 1) throw new IOException("The workspace registration format is unknown. Uninstallation stopped.");
                    foreach (object raw in (object[])value["folders"])
                    {
                        string folder = raw as string;
                        if (String.IsNullOrEmpty(folder) || !Path.IsPathRooted(folder)) throw new IOException("The workspace location is invalid. Uninstallation stopped.");
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
                    if (progress != null) progress.Waiting("Reading existing workspace registrations. Imported files and workspaces will be preserved...");
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
                    throw new IOException("An existing learning directory contains links, preventing full workspace verification. All files were preserved.");
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
                throw new IOException("A trusted local reader could not verify existing workspaces. All files were preserved.");
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
                if (!WaitForExit(helper, 30000, progress, "Reading existing workspace registrations. No files have been deleted...")) { helper.Kill(); throw new IOException("Reading existing workspace registrations timed out. File deletion has not started."); }
                helper.WaitForExit();
                if (helper.ExitCode != 0 || characters >= 4 * 1024 * 1024) throw new IOException("Existing workspace registrations could not be read completely. File deletion has not started.");
            }
            List<string> result = new List<string>();
            foreach (string encoded in output)
            {
                string path = UninstallRegistration.UnB64(encoded);
                if (!Path.IsPathRooted(path)) throw new IOException("An existing workspace path is invalid. File deletion has not started.");
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
                            throw new IOException("The desktop program was modified, preventing an automatic quit request. Exit DeepSteam manually, then retry.");
                        using (Process request = Process.Start(new ProcessStartInfo { FileName = desktop,
                            Arguments = "--quit --install-root=" + InstallerForm.Quote(context.Root), WorkingDirectory = context.Root,
                            UseShellExecute = false, CreateNoWindow = true })) { }
                        quitRequested = true;
                    }
                    if (quitRequested && WaitForExit(process, 2000, progress, "Requesting DeepSteam to exit, including hidden tray windows...")) continue;
                    if (process.StartTime != created || !String.Equals(process.MainModule.FileName, desktop, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("The desktop process identity changed. Uninstallation stopped.");
                    // Old versions do not handle --quit. Keep their graceful
                    // window-close fallback; never kill a busy or hidden process.
                    if (process.MainWindowHandle != IntPtr.Zero) process.CloseMainWindow();
                    if (!WaitForExit(process, quitRequested ? 88000 : 90000, progress, "Waiting for DeepSteam to save its state and exit...")) throw new IOException("DeepSteam is closing. Retry shortly. Other programs were not terminated.");
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
                if (!File.Exists(script) || UninstallRegistration.Sha(script) != record.Hash) throw new IOException("The service-stop script was modified. Stop DeepSteam manually, then retry.");
                ProcessStartInfo info = new ProcessStartInfo { FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe"),
                    Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + InstallerForm.Quote(script) + " -InstallRoot " + InstallerForm.Quote(context.Root),
                    WorkingDirectory = context.Root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
                using (Process helper = new Process())
                {
                    helper.StartInfo = info; helper.OutputDataReceived += delegate { }; helper.ErrorDataReceived += delegate { };
                    helper.Start(); helper.BeginOutputReadLine(); helper.BeginErrorReadLine();
                    if (!WaitForExit(helper, 180000, progress, "Stopping background services owned by this installation. No files have been deleted...")) throw new IOException("Services owned by this installation are still exiting. Deletion has not started. Wait, then retry.");
                    if (helper.ExitCode != 0) throw new IOException("Services owned by this installation did not stop completely. Deletion has not started. Close DeepSteam, then retry.");
                }
            }
            foreach (Process process in Process.GetProcesses())
            {
                try
                {
                    if (process.Id != Process.GetCurrentProcess().Id && UninstallRegistration.Under(process.MainModule.FileName, context.Root))
                        throw new IOException("Programs owned by this installation are still running. Deletion has not started. Close them, then retry.");
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
                    throw new IOException("The desktop quit capability registration was modified. Exit DeepSteam manually, then retry.");
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
            if (required < 16 || required > 128 * 1024) throw new IOException("The legacy launcher state could not be verified. Close that window manually, then retry.");
            IntPtr buffer = Marshal.AllocHGlobal(required);
            try
            {
                if (NtQueryInformationProcess(process.Handle, 60, buffer, required, out required) != 0)
                    throw new IOException("The legacy launcher state could not be verified. Close that window manually, then retry.");
                int length = (ushort)Marshal.ReadInt16(buffer);
                IntPtr text = Marshal.ReadIntPtr(buffer, IntPtr.Size == 8 ? 8 : 4);
                long offset = text.ToInt64() - buffer.ToInt64();
                if (length % 2 != 0 || offset < 0 || offset + length > required) throw new IOException("The launcher process parameters are incomplete.");
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
                        throw new IOException("An installer or unknown launcher is still running. Complete or cancel that window, then retry. No program was terminated.");
                    if (process.StartTime != created || !String.Equals(process.MainModule.FileName, expected, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("The launcher identity changed. Uninstallation stopped.");
                    // Graceful close only: the launcher's busy handler refuses
                    // to close during startup/installation. Never force-kill it.
                    if (process.MainWindowHandle == IntPtr.Zero || !process.CloseMainWindow() || !WaitForExit(process, 10000, progress, "Waiting for the launch window owned by this installation to close..."))
                        throw new IOException("The launcher is busy or has no closable window. Close it manually, then retry. No program was terminated.");
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
            progress.Phase("stop", "Stopping DeepSteam services owned by this installation...", -1); stop(context);
            progress.Phase("workspaces", "Verifying workspace protection boundaries. No files have been deleted...", -1);
            List<string> protectedFolders = WorkspaceFolders(context, progress);
            UninstallProtectionIndex protection = new UninstallProtectionIndex(protectedFolders);
            List<string> files = new List<string>(); List<string> retained = new List<string>();
            Dictionary<string, string> pending = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            UninstallRetryQueue retry = new UninstallRetryQueue(pending);
            HashSet<string> directories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            progress.Phase("check", "Checking the program manifest. User files and modified files will be preserved...", context.Files.Count);
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
                progress.Phase("discover", "Counting selected application records, settings, and cache...", -1);
                long discovered = 0;
                foreach (string dataRoot in context.DataRoots)
                {
                    if (!String.Equals(dataRoot, context.Root, StringComparison.OrdinalIgnoreCase))
                    {
                        string owner = Path.Combine(dataRoot, ".deepsteam-data-owner"); UninstallRegistration.PlainPath(owner);
                        if (!File.Exists(owner) || File.ReadAllText(owner).Trim() != context.Id)
                            throw new IOException("The external data directory is not bound to this installation. Uninstallation stopped and no data was deleted.");
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
            progress.Phase("locks", "Completing deletion checks. Temporary file locks will receive bounded retries...", -1);
            retry.Drain(delegate(int count) { progress.Waiting("Waiting for " + count + " temporary file locks to clear. Permission-restricted items were preserved..."); });
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
            progress.Phase("remove", "Removing verified application files and selected data...", (long)links.Count + files.Count + dataFiles.Count + ordered.Count + pending.Count + 1);
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
            removals.Drain(delegate(int count) { progress.Waiting("Waiting for " + count + " temporary file locks to clear. Other removable items have been processed..."); });
            progress.Counts(completed, attempted, pending.Count, retained.Count);
            progress.Waiting("Removing empty directories. Directories containing user files will be preserved...");
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
                pending[finalizingPath] = "Uninstall registration or final entry cleanup is incomplete. The retry entry was restored.";
                throw Pending(context, pending);
            }
            TryEmpty(Path.Combine(context.Root, "installer"));
            TryEmpty(context.Root);
            progress.Complete();
            return "The application was uninstalled." + (deleteData ? "Application records, settings, and cache that could be safely removed were cleared. Imported attachments, libraries, workspaces, and shared data directories were preserved." : "Learning records, settings, imported files, and workspaces were preserved.") +
                (retained.Count > 0 ? "Additionally preserved " + retained.Count + " modified application files or directories." : "");
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
                { if (key == null) throw new IOException("Uninstall registration is not writable. File removal has not started."); key.SetValue("ManifestSha256", hash); }
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
                    catch { keepBackup = true; throw new IOException("Workspace protection snapshot registration failed. Program removal has not started. The original manifest backup remains at: " + backup); }
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
