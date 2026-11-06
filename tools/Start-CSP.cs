// CutShortPlus - inicializador Windows, sem dependencias extras alem do .NET Framework.
// Requer o script Iniciar-CutShortPlus.ps1 ao lado do EXE e nao eleva privilegios.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("CutShortPlus")]
[assembly: AssemblyDescription("Inicializador do estudio local CutShortPlus")]
[assembly: AssemblyProduct("CutShortPlus")]
[assembly: AssemblyCompany("Erick I Gaudêncio B.")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Erick I Gaudêncio B.")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class StartCsp
{
    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string folder = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string script = Path.Combine(folder, "Iniciar-CutShortPlus.ps1");
        if (!File.Exists(script))
        {
            MessageBox.Show("O arquivo Iniciar-CutShortPlus.ps1 nao foi encontrado.\r\n\r\n" +
                "Mantenha o Start-CSP.exe na pasta original do CutShortPlus.",
                "CutShortPlus - Instalacao incompleta", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        using (Form window = new Form())
        using (System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer())
        {
            window.Text = "CutShortPlus - Iniciando";
            window.BackColor = Color.FromArgb(15, 19, 30);
            window.ForeColor = Color.White;
            window.ClientSize = new Size(435, 158);
            window.FormBorderStyle = FormBorderStyle.FixedDialog;
            window.StartPosition = FormStartPosition.CenterScreen;
            window.MaximizeBox = false;
            window.MinimizeBox = false;
            try { window.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
            catch (Exception) { }

            PictureBox logo = new PictureBox();
            logo.Size = new Size(60, 60);
            logo.Location = new Point(20, 22);
            logo.SizeMode = PictureBoxSizeMode.StretchImage;
            try
            {
                if (window.Icon != null) logo.Image = window.Icon.ToBitmap();
            }
            catch (Exception) { }
            window.Controls.Add(logo);

            Label title = new Label();
            title.Text = "CutShortPlus";
            title.Font = new Font("Segoe UI", 17f, FontStyle.Bold);
            title.ForeColor = Color.White;
            title.AutoSize = true;
            title.Location = new Point(93, 23);
            window.Controls.Add(title);

            Label subtitle = new Label();
            subtitle.Text = "Inicializando o estudio local...";
            subtitle.Font = new Font("Segoe UI", 10f);
            subtitle.ForeColor = Color.FromArgb(195, 200, 210);
            subtitle.AutoSize = true;
            subtitle.Location = new Point(95, 59);
            window.Controls.Add(subtitle);

            ProgressBar progress = new ProgressBar();
            progress.Location = new Point(23, 108);
            progress.Size = new Size(388, 10);
            progress.Style = ProgressBarStyle.Marquee;
            progress.MarqueeAnimationSpeed = 25;
            window.Controls.Add(progress);

            Label footer = new Label();
            footer.Text = "O navegador sera aberto quando estiver pronto.";
            footer.ForeColor = Color.FromArgb(150, 160, 174);
            footer.Font = new Font("Segoe UI", 8f);
            footer.AutoSize = true;
            footer.Location = new Point(23, 128);
            window.Controls.Add(footer);

            Process process = null;
            timer.Interval = 250;
            timer.Tick += delegate(object sender, EventArgs args)
            {
                try
                {
                    if (process != null && process.HasExited)
                    {
                        timer.Stop();
                        int exit = process.ExitCode;
                        process.Dispose();
                        process = null;
                        window.Close();
                        if (exit != 0)
                        {
                            MessageBox.Show(
                                "Nao foi possivel iniciar o CutShortPlus (codigo " + exit.ToString() + ").\r\n\r\n" +
                                "Para visualizar o motivo, execute Iniciar-CutShortPlus.cmd na pasta do projeto.",
                                "CutShortPlus - Erro de inicializacao",
                                MessageBoxButtons.OK, MessageBoxIcon.Error);
                        }
                    }
                }
                catch (Exception ex)
                {
                    timer.Stop();
                    window.Close();
                    MessageBox.Show("Falha na inicializacao: " + ex.Message,
                        "CutShortPlus", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            };

            window.Shown += delegate(object sender, EventArgs args)
            {
                try
                {
                    string powershell = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.Windows),
                        "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
                    ProcessStartInfo info = new ProcessStartInfo();
                    info.FileName = powershell;
                    info.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\"";
                    info.WorkingDirectory = folder;
                    info.UseShellExecute = false;
                    info.CreateNoWindow = true;
                    info.WindowStyle = ProcessWindowStyle.Hidden;
                    process = Process.Start(info);
                    if (process == null) throw new InvalidOperationException("Nao foi possivel iniciar PowerShell.");
                    timer.Start();
                }
                catch (Exception ex)
                {
                    window.Close();
                    MessageBox.Show(ex.Message, "CutShortPlus - Erro",
                        MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            };
            Application.Run(window);
            if (process != null) process.Dispose();
        }
    }
}
