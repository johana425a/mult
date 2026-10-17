// Render actual WinForms controls without displaying or activating a window.
// Build with DeepSteamSetup.cs and /main:DeepSteamInstaller.SetupPreview.
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

namespace DeepSteamInstaller
{
    internal static class SetupPreview
    {
        private static object Field(object instance, string name)
        { return instance.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(instance); }

        private static void CreateHandles(Control parent)
        {
            IntPtr ignored = parent.Handle;
            foreach (Control child in parent.Controls) CreateHandles(child);
            parent.PerformLayout();
        }

        private static void Render(Form form, string target, float scale)
        {
            using (form)
            {
                Size original = form.ClientSize;
                form.FormBorderStyle = FormBorderStyle.None;
                form.ShowInTaskbar = false; form.Opacity = 1;
                form.AutoScaleMode = AutoScaleMode.None;
                form.ClientSize = original;
                if (scale != 1) form.Scale(new SizeF(scale, scale));
                form.ClientSize = new Size((int)Math.Ceiling(original.Width * scale), (int)Math.Ceiling(original.Height * scale));
                CreateHandles(form);
                if (form.Visible) throw new InvalidOperationException("Preview must remain hidden");
                using (Bitmap image = new Bitmap(form.ClientSize.Width, form.ClientSize.Height))
                {
                    form.DrawToBitmap(image, new Rectangle(Point.Empty, form.ClientSize));
                    image.Save(target, ImageFormat.Png);
                }
                if (form.Visible) throw new InvalidOperationException("Preview unexpectedly displayed a window");
            }
        }

        private static InstallerForm Installer(bool failed)
        {
            InstallerForm form = new InstallerForm("--install");
            ((SetupHero)Field(form, "hero")).Phase = 2.4;
            ((TextBox)Field(form, "directory")).Text = @"D:\DeepSteam";
            if (failed)
            {
                ((Label)Field(form, "phaseLabel")).Text = "安装尚未完成";
                ((Label)Field(form, "phaseLabel")).ForeColor = SetupTheme.Destructive;
                ((Label)Field(form, "state")).Text = "已完成的文件会保留，可以稍后重试。";
                SetupProgress bar = (SetupProgress)Field(form, "progress");
                bar.Failed = true; bar.Style = ProgressBarStyle.Marquee; bar.Phase = 1;
            }
            return form;
        }

        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                if (args.Length != 1) throw new ArgumentException("Specify a preview output directory");
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                Directory.CreateDirectory(args[0]);
                Render(Installer(false), Path.Combine(args[0], "install.png"), 1);
                Render(Installer(false), Path.Combine(args[0], "install-150.png"), 1.5F);
                Render(Installer(true), Path.Combine(args[0], "install-error.png"), 1);
                var context = new UninstallContext { Root = @"D:\DeepSteam", Version = Program.Version, Id = "preview-only" };
                using (var form = new UninstallForm(context, true))
                {
                    CheckBox removeData = (CheckBox)Field(form, "removeData");
                    if (removeData.Checked) throw new Exception("Uninstall must preserve data by default");
                    Size boxSize = removeData.GetPreferredSize(Size.Empty);
                    if (boxSize.Width < 16 || boxSize.Height < 20)
                        throw new Exception("An empty caption must not hide the uninstall checkbox");
                }
                Render(new UninstallForm(context, true), Path.Combine(args[0], "uninstall.png"), 1);
                Render(new UninstallForm(context, true), Path.Combine(args[0], "uninstall-150.png"), 1.5F);
                using (var question = new SetupDialog("安装仍在进行，是否取消并关闭？已完成的文件将保留。", "DeepSteam", true))
                {
                    if (((Button)question.AcceptButton).DialogResult != DialogResult.No ||
                        ((Button)question.CancelButton).DialogResult != DialogResult.No)
                        throw new Exception("Enter/Escape must keep installation running");
                }
                Render(new SetupDialog("安装仍在进行，是否取消并关闭？已完成的文件将保留。", "DeepSteam", true), Path.Combine(args[0], "confirmation.png"), 1);
                Render(new SetupDialog("卸载尚未完成，已保留卸载入口。请关闭占用文件的程序后重试。", "DeepSteam 卸载尚未完成", false), Path.Combine(args[0], "uninstall-warning.png"), 1);
                string result = "{\"passed\":true,\"rendered_forms\":7,\"foreground_windows_shown\":0,\"install_or_uninstall_actions_run\":0,\"preserve_data_default\":true,\"confirmation_defaults_to_continue\":true}";
                File.WriteAllText(Path.Combine(args[0], "preview-result.json"), result, new UTF8Encoding(false));
                Console.WriteLine(result); return 0;
            }
            catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        }
    }
}
