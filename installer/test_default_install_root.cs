// Compile beside the real installer source with /main:DeepSteamInstaller.DefaultRootTests.
// No installer, service, account, model or file operation is performed.
using System;
using System.IO;

namespace DeepSteamInstaller
{
    internal static class DefaultRootTests
    {
        private static int checks;
        private static void Check(bool passed, string name)
        {
            if (!passed) throw new Exception("FAIL " + name);
            checks++;
        }

        private static string ActualDecision(string executable, string action, bool noArguments,
            bool completed, bool installing, bool preferredD)
        {
            string initial = InstallLocation.InitialAction(executable, action, noArguments, completed);
            return InstallLocation.SelectDefault(Path.GetDirectoryName(executable),
                InstallLocation.UseOwnSelection(initial, completed || installing),
                @"C:\Users\Test\AppData\Local", preferredD);
        }

        private static int Main()
        {
            string fallback = Path.Combine(@"C:\Users\Test\AppData\Local", "Programs", "DeepSteam");
            Check(InstallLocation.SelectDefault(@"F:\Existing", true, @"C:\Users\Test\AppData\Local", true) == @"F:\Existing", "existing explicit install retained");
            Check(InstallLocation.SelectDefault(@"E:\Existing", true, @"C:\Users\Test\AppData\Local", false) == @"E:\Existing", "existing removable choice retained");
            Check(InstallLocation.SelectDefault(@"E:\Download", false, @"C:\Users\Test\AppData\Local", true) == @"D:\DeepSteam", "fixed D preferred, download drive ignored");
            Check(InstallLocation.SelectDefault(@"E:\Download", false, @"C:\Users\Test\AppData\Local", false) == fallback, "no usable D uses current user's normal directory");
            Check(!InstallLocation.IsInstalledLauncher(@"E:\DeepSteam\DeepSteam-Setup-2026.10.11-r5-startupfix-preview-x64.exe"), "new setup beside old marker is not an installed launcher");
            Check(InstallLocation.IsInstalledLauncher(@"E:\DeepSteam\DeepSteam.exe"), "explicit installed launcher is recognized");
            Check(InstallLocation.IsLocalFixedStorage(DriveType.Fixed, true, "NTFS", false, 17), "fixed NVMe accepted");
            Check(InstallLocation.IsLocalFixedStorage(DriveType.Fixed, true, "NTFS", false, 11), "fixed SATA accepted");
            Check(!InstallLocation.IsLocalFixedStorage(DriveType.Removable, true, "NTFS", false, 17), "removable drive rejected");
            Check(!InstallLocation.IsLocalFixedStorage(DriveType.Fixed, true, "NTFS", false, 7), "USB fixed-drive presentation rejected");
            Check(!InstallLocation.IsLocalFixedStorage(DriveType.Fixed, true, "NTFS", true, 11), "removable media flag rejected");
            Check(!InstallLocation.IsLocalFixedStorage(DriveType.Fixed, false, "NTFS", false, 17), "unready drive rejected");
            Check(!InstallLocation.IsLocalFixedStorage(DriveType.Fixed, true, "NTFS", false, 0), "unknown bus rejected");
            Check(!InstallLocation.IsLocalFixedStorage(DriveType.Fixed, true, "NTFS", false, 9), "network storage rejected");
            Check(!InstallLocation.IsLocalFixedStorage(DriveType.Fixed, true, "NTFS", false, 12), "SD storage rejected");
            Check(!InstallLocation.IsLocalFixedStorage(DriveType.Fixed, true, "exFAT", false, 17), "local fixed exFAT rejected");
            Check(!InstallLocation.IsLocalFixedStorage(DriveType.Fixed, true, "ReFS", false, 17), "local fixed ReFS rejected");
            Check(ActualDecision(@"E:\Old\DeepSteam-Setup-new.exe", "", true, true, false, true) == @"D:\DeepSteam", "setup with completed E marker chooses local D");
            Check(ActualDecision(@"E:\Old\DeepSteam-Setup-new.exe", "", true, false, true, false) == fallback, "setup with interrupted E marker uses normal fallback");
            Check(ActualDecision(@"E:\Old\DeepSteam.exe", "", true, true, false, true) == @"E:\Old", "explicit installed launcher preserves own root");
            Check(ActualDecision(@"E:\Old\DeepSteam-Setup-new.exe", "--launch", false, true, false, true) == @"E:\Old", "explicit launch preserves chosen own root");
            Check(ActualDecision(@"E:\Old\DeepSteam.exe", "--stop", false, true, false, true) == @"E:\Old", "explicit stop preserves chosen own root");
            Check(ActualDecision(@"E:\Old\DeepSteam.exe", "", true, false, true, true) == @"D:\DeepSteam", "incomplete launcher does not silently resume external root");
            bool actualPreferredD = InstallLocation.PreferredDUsable();
            string actualDefault = InstallLocation.SelectDefault(Path.GetDirectoryName(typeof(DefaultRootTests).Assembly.Location),
                false, Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), actualPreferredD);
            Console.WriteLine("PASS default install policy; checks=" + checks + "; actualDLocalFixed=" + actualPreferredD + "; actualDefault=" + actualDefault);
            return 0;
        }
    }
}
