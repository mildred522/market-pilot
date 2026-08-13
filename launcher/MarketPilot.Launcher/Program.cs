using System.Diagnostics;
using System.Net;
using System.Net.Sockets;

namespace MarketPilot.Launcher;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        var projectRoot = ProjectLocator.FindProjectRoot(AppContext.BaseDirectory);

        if (args.Contains("--check", StringComparer.OrdinalIgnoreCase))
        {
            Environment.ExitCode = StartupCheck.Run(projectRoot);
            return;
        }

        ApplicationConfiguration.Initialize();
        Application.Run(new LauncherForm(projectRoot));
    }
}

internal static class ProjectLocator
{
    public static string? FindProjectRoot(string startDirectory)
    {
        var overridePath = Environment.GetEnvironmentVariable("MARKET_PILOT_ROOT");
        if (IsProjectRoot(overridePath))
        {
            return Path.GetFullPath(overridePath!);
        }

        var current = new DirectoryInfo(startDirectory);
        while (current is not null)
        {
            if (IsProjectRoot(current.FullName))
            {
                return current.FullName;
            }

            current = current.Parent;
        }

        return null;
    }

    public static bool IsProjectRoot(string? path) =>
        !string.IsNullOrWhiteSpace(path) &&
        File.Exists(Path.Combine(path, "backend", "app", "main.py")) &&
        File.Exists(Path.Combine(path, "frontend", "package.json"));
}

internal static class StartupCheck
{
    public static int Run(string? projectRoot)
    {
        if (projectRoot is null)
        {
            Console.Error.WriteLine("找不到项目目录。请将启动器放在项目的 dist 目录，或设置 MARKET_PILOT_ROOT。");
            return 2;
        }

        Console.WriteLine($"项目目录: {projectRoot}");
        var python = CommandFinder.Find("python.exe");
        var npm = CommandFinder.Find("npm.cmd");
        Console.WriteLine($"Python: {python ?? "未找到"}");
        Console.WriteLine($"Node/npm: {npm ?? "未找到"}");
        return python is not null && npm is not null ? 0 : 1;
    }
}

internal static class CommandFinder
{
    public static string? Find(string fileName)
    {
        var path = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        foreach (var directory in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(directory.Trim(), fileName);
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
            catch
            {
                // Ignore invalid PATH entries and continue checking the rest.
            }
        }

        return null;
    }
}

internal sealed class LauncherForm : Form
{
    private const string FrontendUrl = "http://127.0.0.1:3000";
    private const string BackendHealthUrl = "http://127.0.0.1:8000/health";

    private readonly string? _projectRoot;
    private readonly HttpClient _httpClient = new() { Timeout = TimeSpan.FromSeconds(2) };
    private readonly Label _statusLabel = new();
    private readonly Label _detailLabel = new();
    private readonly Button _startButton = new();
    private readonly Button _openButton = new();
    private readonly Button _stopButton = new();
    private readonly TextBox _logBox = new();
    private Process? _backendProcess;
    private Process? _frontendProcess;
    private bool _isBusy;

    public LauncherForm(string? projectRoot)
    {
        _projectRoot = projectRoot;
        ConfigureWindow();
        BuildLayout();
        Shown += async (_, _) => await RefreshStatusAsync();
        FormClosing += OnFormClosing;
    }

    private void ConfigureWindow()
    {
        Text = "Market Pilot 启动器";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(680, 500);
        Size = new Size(760, 560);
        BackColor = Color.FromArgb(245, 247, 248);
        Font = new Font("Microsoft YaHei UI", 10F);
    }

    private void BuildLayout()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(28),
            ColumnCount = 1,
            RowCount = 5,
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var title = new Label
        {
            AutoSize = true,
            Text = "Market Pilot",
            Font = new Font("Microsoft YaHei UI", 22F, FontStyle.Bold),
            ForeColor = Color.FromArgb(30, 42, 48),
            Margin = new Padding(0, 0, 0, 6),
        };
        root.Controls.Add(title);

        var subtitle = new Label
        {
            AutoSize = true,
            Text = "餐饮经营分析工作台",
            ForeColor = Color.FromArgb(93, 106, 113),
            Margin = new Padding(2, 0, 0, 22),
        };
        root.Controls.Add(subtitle);

        var statusPanel = new Panel
        {
            Dock = DockStyle.Top,
            Height = 112,
            BackColor = Color.White,
            Padding = new Padding(20, 16, 20, 16),
            Margin = new Padding(0, 0, 0, 16),
        };
        _statusLabel.AutoSize = true;
        _statusLabel.Font = new Font("Microsoft YaHei UI", 13F, FontStyle.Bold);
        _statusLabel.ForeColor = Color.FromArgb(65, 78, 84);
        _statusLabel.Location = new Point(20, 17);
        _statusLabel.Text = "正在检查服务...";
        _detailLabel.AutoSize = false;
        _detailLabel.Size = new Size(640, 48);
        _detailLabel.Location = new Point(20, 49);
        _detailLabel.ForeColor = Color.FromArgb(93, 106, 113);
        _detailLabel.Text = _projectRoot ?? "未找到项目目录";
        statusPanel.Controls.Add(_statusLabel);
        statusPanel.Controls.Add(_detailLabel);
        root.Controls.Add(statusPanel);

        _logBox.Dock = DockStyle.Fill;
        _logBox.Multiline = true;
        _logBox.ReadOnly = true;
        _logBox.ScrollBars = ScrollBars.Vertical;
        _logBox.BackColor = Color.FromArgb(28, 35, 39);
        _logBox.ForeColor = Color.FromArgb(218, 226, 230);
        _logBox.BorderStyle = BorderStyle.None;
        _logBox.Font = new Font("Consolas", 9F);
        _logBox.Margin = new Padding(0, 0, 0, 16);
        root.Controls.Add(_logBox);

        var buttons = new FlowLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Margin = new Padding(0),
        };
        ConfigureButton(_startButton, "启动并打开", Color.FromArgb(22, 112, 82), Color.White);
        ConfigureButton(_openButton, "打开工作台", Color.White, Color.FromArgb(30, 75, 62));
        ConfigureButton(_stopButton, "停止服务", Color.White, Color.FromArgb(159, 52, 52));
        _startButton.Click += async (_, _) => await StartServicesAsync();
        _openButton.Click += (_, _) => OpenBrowser();
        _stopButton.Click += async (_, _) => await StopServicesAsync();
        buttons.Controls.AddRange([_startButton, _openButton, _stopButton]);
        root.Controls.Add(buttons);

        Controls.Add(root);
        UpdateControls(false, false);
    }

    private static void ConfigureButton(Button button, string text, Color background, Color foreground)
    {
        button.Text = text;
        button.AutoSize = false;
        button.Size = new Size(142, 42);
        button.Margin = new Padding(0, 0, 12, 0);
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderColor = Color.FromArgb(195, 204, 208);
        button.BackColor = background;
        button.ForeColor = foreground;
        button.Cursor = Cursors.Hand;
    }

    private async Task StartServicesAsync()
    {
        if (_isBusy || _projectRoot is null)
        {
            return;
        }

        _isBusy = true;
        UpdateControls(false, false);
        SetStatus("正在启动...", "正在检查运行环境并启动前后端服务。", Color.FromArgb(171, 104, 21));

        try
        {
            var python = CommandFinder.Find("python.exe") ?? throw new InvalidOperationException("未找到 Python。请安装 Python 并加入 PATH。");
            var npm = CommandFinder.Find("npm.cmd") ?? throw new InvalidOperationException("未找到 Node.js/npm。请安装 Node.js 并加入 PATH。");

            if (!Directory.Exists(Path.Combine(_projectRoot, "frontend", "node_modules")))
            {
                throw new InvalidOperationException("前端依赖尚未安装。请先在 frontend 目录运行 npm install。");
            }

            if (!await IsBackendReadyAsync())
            {
                EnsurePortAvailable(8000, "后端");
                _backendProcess = StartProcess(
                    python,
                    "-m uvicorn app.main:app --host 127.0.0.1 --port 8000",
                    Path.Combine(_projectRoot, "backend"),
                    "后端");
            }
            else
            {
                AppendLog("后端已在运行，直接连接现有服务。");
            }

            if (!await IsFrontendReadyAsync())
            {
                EnsurePortAvailable(3000, "前端");
                _frontendProcess = StartProcess(
                    npm,
                    "run dev",
                    Path.Combine(_projectRoot, "frontend"),
                    "前端");
            }
            else
            {
                AppendLog("前端已在运行，直接连接现有服务。");
            }

            var ready = await WaitUntilReadyAsync(TimeSpan.FromSeconds(45));
            if (!ready)
            {
                throw new TimeoutException("服务启动超时。请查看下方日志定位原因。");
            }

            SetStatus("服务运行中", "前端与后端均已就绪，可以打开工作台。", Color.FromArgb(22, 112, 82));
            UpdateControls(true, OwnsAnyProcess());
            OpenBrowser();
        }
        catch (Exception exception)
        {
            AppendLog($"启动失败: {exception.Message}");
            SetStatus("启动失败", exception.Message, Color.FromArgb(159, 52, 52));
            UpdateControls(false, OwnsAnyProcess());
        }
        finally
        {
            _isBusy = false;
        }
    }

    private Process StartProcess(string fileName, string arguments, string workingDirectory, string label)
    {
        var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                WorkingDirectory = workingDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            },
            EnableRaisingEvents = true,
        };
        process.OutputDataReceived += (_, args) => AppendProcessLine(label, args.Data);
        process.ErrorDataReceived += (_, args) => AppendProcessLine(label, args.Data);
        process.Exited += (_, _) => AppendLog($"{label}进程已退出（代码 {process.ExitCode}）。");

        if (!process.Start())
        {
            throw new InvalidOperationException($"无法启动{label}进程。");
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        AppendLog($"{label}已启动（PID {process.Id}）。");
        return process;
    }

    private async Task<bool> WaitUntilReadyAsync(TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (await IsBackendReadyAsync() && await IsFrontendReadyAsync())
            {
                return true;
            }

            await Task.Delay(700);
        }

        return false;
    }

    private async Task RefreshStatusAsync()
    {
        if (_projectRoot is null)
        {
            SetStatus("未找到项目", "请把 EXE 放在项目 dist 目录中，或设置 MARKET_PILOT_ROOT。", Color.FromArgb(159, 52, 52));
            UpdateControls(false, false);
            return;
        }

        var backendReady = await IsBackendReadyAsync();
        var frontendReady = await IsFrontendReadyAsync();
        if (backendReady && frontendReady)
        {
            SetStatus("服务运行中", "检测到前端与后端均已就绪。", Color.FromArgb(22, 112, 82));
            UpdateControls(true, OwnsAnyProcess());
        }
        else
        {
            SetStatus("尚未启动", $"项目目录：{_projectRoot}", Color.FromArgb(65, 78, 84));
            UpdateControls(false, OwnsAnyProcess());
        }
    }

    private async Task StopServicesAsync()
    {
        if (_isBusy || !OwnsAnyProcess())
        {
            return;
        }

        _isBusy = true;
        SetStatus("正在停止...", "正在关闭由本启动器创建的服务。", Color.FromArgb(171, 104, 21));
        UpdateControls(false, false);

        await Task.Run(() =>
        {
            StopProcess(_frontendProcess, "前端");
            StopProcess(_backendProcess, "后端");
        });
        _frontendProcess = null;
        _backendProcess = null;
        _isBusy = false;
        SetStatus("服务已停止", "可以随时重新启动。", Color.FromArgb(65, 78, 84));
        UpdateControls(false, false);
    }

    private void StopProcess(Process? process, string label)
    {
        if (process is null || process.HasExited)
        {
            return;
        }

        try
        {
            process.Kill(entireProcessTree: true);
            process.WaitForExit(5000);
            AppendLog($"{label}已停止。");
        }
        catch (Exception exception)
        {
            AppendLog($"停止{label}失败: {exception.Message}");
        }
    }

    private async Task<bool> IsBackendReadyAsync() => await IsUrlReadyAsync(BackendHealthUrl);

    private async Task<bool> IsFrontendReadyAsync() => await IsUrlReadyAsync(FrontendUrl);

    private async Task<bool> IsUrlReadyAsync(string url)
    {
        try
        {
            using var response = await _httpClient.GetAsync(url);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private static void EnsurePortAvailable(int port, string label)
    {
        try
        {
            using var listener = new TcpListener(IPAddress.Loopback, port);
            listener.Start();
            listener.Stop();
        }
        catch (SocketException)
        {
            throw new InvalidOperationException($"{label}端口 {port} 已被其他程序占用。");
        }
    }

    private static void OpenBrowser()
    {
        Process.Start(new ProcessStartInfo(FrontendUrl) { UseShellExecute = true });
    }

    private void SetStatus(string status, string detail, Color color)
    {
        if (InvokeRequired)
        {
            BeginInvoke(() => SetStatus(status, detail, color));
            return;
        }

        _statusLabel.Text = status;
        _statusLabel.ForeColor = color;
        _detailLabel.Text = detail;
    }

    private void UpdateControls(bool servicesReady, bool canStop)
    {
        _startButton.Enabled = !_isBusy && !servicesReady && _projectRoot is not null;
        _openButton.Enabled = servicesReady;
        _stopButton.Enabled = !_isBusy && canStop;
    }

    private bool OwnsAnyProcess() =>
        (_backendProcess is { HasExited: false }) || (_frontendProcess is { HasExited: false });

    private void AppendProcessLine(string label, string? line)
    {
        if (!string.IsNullOrWhiteSpace(line))
        {
            AppendLog($"[{label}] {line}");
        }
    }

    private void AppendLog(string message)
    {
        if (InvokeRequired)
        {
            BeginInvoke(() => AppendLog(message));
            return;
        }

        _logBox.AppendText($"{DateTime.Now:HH:mm:ss}  {message}{Environment.NewLine}");
    }

    private void OnFormClosing(object? sender, FormClosingEventArgs args)
    {
        if (!OwnsAnyProcess())
        {
            return;
        }

        var answer = MessageBox.Show(
            "关闭启动器时是否同时停止 Market Pilot 服务？",
            "Market Pilot",
            MessageBoxButtons.YesNoCancel,
            MessageBoxIcon.Question);

        if (answer == DialogResult.Cancel)
        {
            args.Cancel = true;
            return;
        }

        if (answer == DialogResult.Yes)
        {
            StopProcess(_frontendProcess, "前端");
            StopProcess(_backendProcess, "后端");
        }
    }
}
