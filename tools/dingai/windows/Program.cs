// DingAIWin — 系统级批注 Windows 版
// 交互与 JSON 契约(dingai-desktop-v1)对齐 macOS 版:
//   Ctrl+Alt+A → 默认实时批注(DINGAI_LIVE=0 才冻结截屏) → 单击落钉 / 拖拽箭头或框
//   按住 Alt 把点击交给下层。Esc/完成 = 此时截图 + JSON + 剪贴板 + 落盘
// 托盘常驻(自绘图钉图标);--auto-test 自动模式(无人工交互,落样例后退出)

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using Windows.Graphics.Imaging;
using Windows.Media.FaceAnalysis;
using Windows.Media.Ocr;
using Windows.Storage.Streams;
using WF = System.Windows.Forms;
using System.Windows.Interop;
using Point = System.Windows.Point;
using Brush = System.Windows.Media.Brush;
using Button = System.Windows.Controls.Button;
using Image = System.Windows.Controls.Image;
using TextBox = System.Windows.Controls.TextBox;
using MouseEventArgs = System.Windows.Input.MouseEventArgs;
using KeyEventArgs = System.Windows.Input.KeyEventArgs;
using Brushes = System.Windows.Media.Brushes;
using Color = System.Windows.Media.Color;
using Rectangle = System.Windows.Shapes.Rectangle;
using Path = System.IO.Path;
using Application = System.Windows.Application;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Windows.Automation;

namespace DingAIWin;

#region Win32

internal static class Win32
{
    [DllImport("winmm.dll", CharSet = CharSet.Unicode)] public static extern int mciSendString(string command, StringBuilder ret, int retLen, IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool RegisterHotKey(IntPtr hWnd, int id, uint mods, uint vk);
    [DllImport("user32.dll")] public static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr hWnd, int nIndex);
    [DllImport("user32.dll")] public static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);
    [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int vKey);

    public const int WM_HOTKEY = 0x0312;
    public const int GWL_EXSTYLE = -20;
    public const int WS_EX_TRANSPARENT = 0x20;
    public const int VK_MENU = 0x12;
    public const uint MOD_ALT = 0x1, MOD_CONTROL = 0x2;
    public const uint VK_A = 0x41;

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}

#endregion

#region 数据模型(截图像素坐标,左上原点——与 macOS 版同契约)

record PinRec(int Id, int X, int Y)
{
    public string OcrNearby { get; set; } = "";
    public string Note { get; set; } = null;
    public string WinOwner { get; set; } = null;
    public string WinTitle { get; set; } = null;
    public int[] WinFrame { get; set; } = null;   // 钉所在窗(物理像素,屏内)
    public string PinType { get; set; } = "bug";
    public string Status { get; set; } = "open";
    public string AnchorKind { get; set; } = "viewport";
    public string AnchorNote { get; set; } = null;
}
record ArrowRec(int Id, int FromX, int FromY, int ToX, int ToY, string Color, int Width);
record BoxRec(int Id, int X, int Y, int W, int H, string Color, int Width)
{
    public string Shape { get; set; } = "rect";
}
record SyncCfg(string Mode, string Share, string[] Hosts, string Token, string Project, bool Redact);

static class UiText
{
    public static string T(string key)
    {
        var lang = Environment.GetEnvironmentVariable("DINGAI_LANG") ?? "zh";
        if (lang != "en" && lang != "vi") lang = "zh";
        try
        {
            var path = Path.Combine(AppContext.BaseDirectory, "strings.json");
            var row = (JsonNode.Parse(File.ReadAllText(path)) as JsonObject)?[key] as JsonObject;
            return row?[lang]?.ToString() ?? row?["zh"]?.ToString() ?? key;
        }
        catch { return key; }
    }
}
abstract record Item { public int Id = 0; }
record PinItem(PinRec Pin) : Item;
record ArrowItem(ArrowRec A) : Item;
record BoxItem(BoxRec B) : Item;
record OcrText(string Text, double Cx, double Cy)
{
    public double W { get; set; }
    public double H { get; set; }
}
record WinCand(string Owner, string Title, int[] FramePhys);   // 物理像素

#endregion

internal class Controller
{
    public static Controller Inst = new();
    public string OutRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), Environment.GetEnvironmentVariable("DINGAI_OUTPUT_DIR") ?? Environment.GetEnvironmentVariable("ANNO_OUTPUT_DIR") ?? "DingAI");
    public AnnotationWindow Overlay;
    public AnnoCanvas Canvas;
    public WF.NotifyIcon Tray;
    public HotkeySink Sink;

    // 会话数据
    public string AppName, AppPath, AppTitle;
    public int AppPid;
    public int[] SessWinFrame;      // 前台主窗(物理像素)
    public System.Drawing.Bitmap Shot;
    public string ShotFile;
    public List<OcrText> Ocr = new();
    string VoiceWav = "";
    public volatile bool OcrDone;
    public List<WinCand> WinCands = new();
    public int ScreenW, ScreenH;   // 物理像素
    public double Scale = 1;       // 物理/DIP
    public bool Live = true;       // DINGAI_LIVE=0 才冻结截图
    public DateTime T0;

    public void Run(string[] args)
    {
        Directory.CreateDirectory(Path.Combine(OutRoot, "notes"));
        Directory.CreateDirectory(Path.Combine(OutRoot, "shots"));
        Live = Environment.GetEnvironmentVariable("DINGAI_LIVE") != "0";

        var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        Sink = new HotkeySink(() => Toggle());
        MakeTray();
        if (args.Contains("--auto-test"))
        {
            var t = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1.2) };
            t.Tick += (s, e) => { t.Stop(); AutoTest(); };
            t.Start();
        }
        app.Run();
    }

    void MakeTray()
    {
        using var bmp = new System.Drawing.Bitmap(16, 16);
        using (var g = System.Drawing.Graphics.FromImage(bmp))
        {
            g.Clear(System.Drawing.Color.Transparent);
            using var b = new System.Drawing.SolidBrush(System.Drawing.Color.Black);
            g.FillEllipse(b, 4, 1, 8, 8);                       // 钉头
            using var p = new System.Drawing.Pen(System.Drawing.Color.Black, 2f);
            g.DrawLine(p, 8, 9, 8, 15);                          // 针杆
        }
        var icon = System.Drawing.Icon.FromHandle(bmp.GetHicon());
        var menu = new WF.ContextMenuStrip();
        menu.Items.Add("DingAI 开始批注  Ctrl+Alt+A", null, (s, e) => Toggle());
        menu.Items.Add("检查本次改动", null, (s, e) => CheckScope());
        menu.Items.Add(new WF.ToolStripSeparator());
        menu.Items.Add("退出", null, (s, e) => { Tray.Visible = false; Application.Current.Shutdown(); });
        Tray = new WF.NotifyIcon { Icon = icon, Text = "DingAI", Visible = true, ContextMenuStrip = menu };
        Tray.DoubleClick += (s, e) => Toggle();
    }

    public void Toggle() { if (Overlay == null) Begin(); else Finish(true); }

    void AutoTest()
    {
        Begin();
        var t = new DispatcherTimer { Interval = TimeSpan.FromSeconds(6) };
        t.Tick += (s, e) =>
        {
            t.Stop();
            var v = Overlay?.Canvas; if (v == null) { Environment.Exit(3); return; }
            double w = ScreenW, h = ScreenH;
            v.DebugAddPin(w * 0.40, h * 0.35);
            v.DebugAddPin(w * 0.62, h * 0.52);
            v.DebugAddArrow(w * 0.30, h * 0.68, w * 0.52, h * 0.74);
            v.DebugAddBox(w * 0.55, h * 0.30, w * 0.75, h * 0.40);
            var t2 = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1.5) };
            t2.Tick += (s2, e2) => { t2.Stop(); Finish(false); Environment.Exit(0); };
            t2.Start();
        };
        t.Start();
    }

    public void Begin()
    {
        if (Overlay != null) return;

        // 1) 批注对象 = 当前前台(我们无可见窗口,热键瞬间前台即目标)
        var fg = Win32.GetForegroundWindow();
        AppPid = 0; AppName = AppPath = AppTitle = null;
        var sb = new StringBuilder(256);
        if (fg != IntPtr.Zero)
        {
            Win32.GetWindowThreadProcessId(fg, out uint pid);
            AppPid = (int)pid;
            Win32.GetWindowText(fg, sb, 256); AppTitle = sb.ToString();
            try
            {
                var pr = Process.GetProcessById((int)pid);
                AppName = pr.ProcessName;
                AppPath = pr.MainModule?.FileName;
            }
            catch { }
        }

        // 2) 实时模式先盖透明层,截图留到完成,这样下层还能滚动。DINGAI_LIVE=0 仍是先冻截图。
        var bounds = WF.Screen.PrimaryScreen.Bounds;
        ScreenW = bounds.Width; ScreenH = bounds.Height;
        if (!Live) CaptureShot();

        // 3) 窗口候选(落钉按坐标定位窗口用;EnumWindows 从顶到底,后者覆盖前者→倒序=小窗在上)
        WinCands.Clear();
        var list = new List<WinCand>();
        Win32.EnumWindows((h, _) =>
        {
            if (!Win32.IsWindowVisible(h)) return true;
            if (!Win32.GetWindowRect(h, out var r)) return true;
            int w = r.Right - r.Left, hgt = r.Bottom - r.Top;
            if (w < 60 || hgt < 60) return true;
            if (r.Right <= 0 || r.Bottom <= 0 || r.Left >= ScreenW || r.Top >= ScreenH) return true;
            Win32.GetWindowThreadProcessId(h, out uint pid);
            string owner = null;
            try { owner = Process.GetProcessById((int)pid)?.ProcessName; } catch { }
            var t = new StringBuilder(256); Win32.GetWindowText(h, t, 256);
            list.Add(new WinCand(owner ?? "?", t.ToString(), new[] { r.Left, r.Top, w, hgt }));
            return true;
        }, IntPtr.Zero);
        WinCands = list.AsEnumerable().Reverse().ToList();   // 后枚举的是上层窗,放前面

        T0 = DateTime.Now; Ocr.Clear(); OcrDone = false;

        Overlay = new AnnotationWindow(this);
        Canvas = Overlay.Canvas;
        Overlay.Show();
        Overlay.Activate();

        // 4) 冻结模式后台 OCR;实时模式等导出时的截图
        if (!Live && Shot != null)
        {
            Task.Run(async () =>
            {
                var items = await RunOcr(Shot);
                Ocr = items; OcrDone = true;
                await Application.Current.Dispatcher.InvokeAsync(() => Canvas?.RefreshPinSigns());
            });
        }
    }

    public void CaptureShot()
    {
        var bounds = WF.Screen.PrimaryScreen.Bounds;
        ScreenW = bounds.Width; ScreenH = bounds.Height;
        Shot?.Dispose();
        Shot = new System.Drawing.Bitmap(ScreenW, ScreenH);
        using (var g = System.Drawing.Graphics.FromImage(Shot))
            g.CopyFromScreen(bounds.Left, bounds.Top, 0, 0, Shot.Size);
        ShotFile = Path.Combine(OutRoot, "shots", $"anno-{Stamp()}.png");
        Shot.Save(ShotFile, System.Drawing.Imaging.ImageFormat.Png);
    }

    public string UiaAt(int x, int y)
    {
        try
        {
            var el = AutomationElement.FromPoint(new Point(x, y));
            if (el == null) return null;
            var type = el.Current.ControlType?.ProgrammaticName ?? "";
            var id = el.Current.AutomationId ?? "";
            var name = el.Current.Name ?? "";
            var text = (type + " " + id + " " + name).Trim();
            return text.Length == 0 ? null : text;
        }
        catch { return null; }
    }

    async Task<List<OcrText>> RunOcr(System.Drawing.Bitmap bmp)
    {
        var outList = new List<OcrText>();
        try
        {
            var engine = OcrEngine.TryCreateFromUserProfileLanguages();
            if (engine == null) return outList;
            var software = await SoftwareBitmapFromBmp(bmp);
            if (software == null) return outList;
            var res = await engine.RecognizeAsync(software);
            foreach (var line in res.Lines)
                foreach (var word in line.Words)
                {
                    var b = word.BoundingRect;   // 物理像素
                    var t = word.Text?.Trim();
                    if (!string.IsNullOrEmpty(t))
                        outList.Add(new OcrText(t, b.X + b.Width / 2, b.Y + b.Height / 2) { W = b.Width, H = b.Height });
                }
        }
        catch { }
        return outList;
    }

    async Task<SoftwareBitmap> SoftwareBitmapFromBmp(System.Drawing.Bitmap bmp)
    {
        var data = bmp.LockBits(new System.Drawing.Rectangle(0, 0, bmp.Width, bmp.Height),
            System.Drawing.Imaging.ImageLockMode.ReadOnly, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        int size = Math.Abs(data.Stride) * data.Height;
        byte[] bytes = new byte[size];
        Marshal.Copy(data.Scan0, bytes, 0, size);
        bmp.UnlockBits(data);
        // WinRT SoftwareBitmap 需要 WinRT IBuffer;用 AsBuffer 扩展(CsWinRT 提供)
        var buffer = bytes.AsBuffer();
        return SoftwareBitmap.CreateCopyFromBuffer(buffer, BitmapPixelFormat.Bgra8, bmp.Width, bmp.Height);
    }

    public string OcrNear(int x, int y, double radius = 220, int limit = 8)
    {
        if (Ocr.Count == 0) return OcrDone ? "" : "OCR…";
        var hits = Ocr.Select(o => (o.Text, D: Math.Sqrt((o.Cx - x) * (o.Cx - x) + (o.Cy - y) * (o.Cy - y))))
            .Where(t => t.D <= radius).OrderBy(t => t.D).Take(limit);
        return string.Join(" | ", hits.Select(h => h.Text.Length > 42 ? h.Text[..42] + "…" : h.Text));
    }

    /// 钉所在窗:WinCands 已按从前到后排列,取第一个包含该点的窗(被盖住的小窗不再抢记录)。
    public WinCand WindowAt(int x, int y)
    {
        foreach (var c in WinCands)
        {
            var f = c.FramePhys;
            if (x >= f[0] && x <= f[0] + f[2] && y >= f[1] && y <= f[1] + f[3])
                return c;
        }
        return null;
    }

    public void StartVoice()
    {
        try
        {
            VoiceWav = Path.Combine(Path.GetTempPath(), "dingai-hold.wav");
            var sink = new StringBuilder(8);
            Native.mciSendString("close dingai", sink, sink.Capacity, IntPtr.Zero);
            Native.mciSendString("open new type waveaudio alias dingai", sink, sink.Capacity, IntPtr.Zero);
            Native.mciSendString("record dingai", sink, sink.Capacity, IntPtr.Zero);
        }
        catch { }
    }

    public string StopVoice()
    {
        try
        {
            var sink = new StringBuilder(8);
            Native.mciSendString("stop dingai", sink, sink.Capacity, IntPtr.Zero);
            Native.mciSendString("save dingai \"" + VoiceWav + "\"", sink, sink.Capacity, IntPtr.Zero);
            Native.mciSendString("close dingai", sink, sink.Capacity, IntPtr.Zero);
        }
        catch { return ""; }
        return TranscribeWav(VoiceWav);
    }

    static string TranscribeWav(string wav)
    {
        var bin = Environment.GetEnvironmentVariable("DINGAI_WHISPER");
        var model = Environment.GetEnvironmentVariable("DINGAI_WHISPER_MODEL");
        var lang = Environment.GetEnvironmentVariable("DINGAI_WHISPER_LANG") ?? "zh";
        if (lang != "zh" && lang != "en" && lang != "vi") lang = "zh";
        if (string.IsNullOrEmpty(bin) || string.IsNullOrEmpty(model) || !File.Exists(wav)) return "";
        try
        {
            var info = new ProcessStartInfo(bin, "-m \"" + model + "\" -f \"" + wav + "\" -l " + lang + " -nt")
            {
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using var proc = Process.Start(info);
            if (proc == null) return "";
            var text = proc.StandardOutput.ReadToEnd();
            proc.WaitForExit(20000);
            return proc.ExitCode == 0 ? text.Trim() : "";
        }
        catch { return ""; }
    }

    public void Finish(bool clipboard)
    {
        var view = Overlay?.Canvas; if (view == null) return;
        view.CommitNoteField();
        if (Live)
        {
            Overlay.Opacity = 0;
            Overlay.Hide();
            try { CaptureShot(); } catch { Shot = null; }
            try
            {
                if (Shot != null)
                {
                    var work = Task.Run(async () => await RunOcr(Shot));
                    if (work.Wait(TimeSpan.FromMilliseconds(1200)))
                    {
                        Ocr = work.Result;
                        OcrDone = true;
                    }
                }
            }
            catch { OcrDone = true; }
        }
        if (LoadSync().Redact) RedactSession(view);
        var json = BuildJson(view.Items);
        WriteSteps(view);
        var path = Path.Combine(OutRoot, "notes", $"anno-{Stamp()}.json");
        File.WriteAllText(path, json);
        RecordHandoffBaseline();
        if (clipboard)
        {
            try { System.Windows.Clipboard.SetText(HandoffPrompt(json)); } catch { }
        }
        Publish(json, path, ShotFile);
        Overlay.Close(); Overlay = null; Shot?.Dispose(); Shot = null;
    }

    void WriteSteps(AnnoCanvas view)
    {
        if (view.Steps.Count == 0) return;
        var dir = Path.Combine(OutRoot, "notes");
        Directory.CreateDirectory(dir);
        var lines = new List<string> { "# DingAI steps", "" };
        var clean = new JsonArray();
        for (int i = 0; i < view.Steps.Count; i++)
        {
            var step = view.Steps[i];
            var name = "step-" + (i + 1) + ".png";
            lines.Add((i + 1) + ". " + step.Note);
            lines.Add("");
            lines.Add("![](" + name + ")");
            lines.Add("");
            if (Shot != null)
            {
                var rect = new System.Drawing.Rectangle(Math.Max(0, step.X - 240), Math.Max(0, step.Y - 160), 480, 320);
                rect.Intersect(new System.Drawing.Rectangle(0, 0, Shot.Width, Shot.Height));
                if (rect.Width > 2 && rect.Height > 2)
                {
                    try { using var crop = Shot.Clone(rect, Shot.PixelFormat); crop.Save(Path.Combine(dir, name), System.Drawing.Imaging.ImageFormat.Png); } catch { }
                }
            }
            clean.Add(new JsonObject { ["n"] = i + 1, ["x_px"] = step.X, ["y_px"] = step.Y, ["note"] = step.Note, ["shot"] = name });
        }
        File.WriteAllText(Path.Combine(dir, "sop.md"), string.Join("\n", lines) + "\n");
        File.WriteAllText(Path.Combine(dir, "repro.json"), new JsonObject { ["schema"] = "dingai-steps-v1", ["steps"] = clean }.ToJsonString());
    }

    static string RedactString(string text, List<Regex> regs)
    {
        if (string.IsNullOrEmpty(text)) return text;
        foreach (var reg in regs) text = reg.Replace(text, "[redacted]");
        return text;
    }

    List<Regex> RedactPatterns()
    {
        var regs = new List<Regex>();
        string[] builtin =
        {
            "[A-Z0-9._%+\\-]+@[A-Z0-9.\\-]+\\.[A-Z]{2,}",
            "(?:\\+?86[-\\s]?)?1[3-9]\\d{9}",
            "(?:\\+?84|0)(?:3|5|7|8|9)\\d{8}",
            "\\(?\\d{3}\\)?[-.\\s]\\d{3}[-.\\s]\\d{4}",
            "\\b(?:PO|P\\.O\\.|SO|订单号|订单|订货单)\\s*[#:：\\-]?\\s*[A-Z0-9][A-Z0-9\\-]{2,}",
            "(?:[$€£₫]|¥|USD|CNY|VND)\\s?\\d[\\d,]*(?:\\.\\d{1,2})?",
        };
        foreach (var pattern in builtin)
        {
            try { regs.Add(new Regex(pattern, RegexOptions.IgnoreCase)); } catch { }
        }
        var home = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "DingAI");
        void Read(string name, bool literal)
        {
            try
            {
                foreach (var line in File.ReadAllLines(Path.Combine(home, name)))
                {
                    var text = line.Trim();
                    if (text.Length == 0 || text.StartsWith("#")) continue;
                    try { regs.Add(new Regex(literal ? Regex.Escape(text) : text, RegexOptions.IgnoreCase)); } catch { }
                }
            }
            catch { }
        }
        Read("redact-names.txt", true);
        Read("redact-patterns.txt", false);
        return regs;
    }

    void Pixelate(System.Drawing.Bitmap bmp, System.Drawing.Rectangle rect)
    {
        rect.Intersect(new System.Drawing.Rectangle(0, 0, bmp.Width, bmp.Height));
        if (rect.Width < 2 || rect.Height < 2) return;
        int sw = Math.Max(1, rect.Width / 14), sh = Math.Max(1, rect.Height / 14);
        using var small = new System.Drawing.Bitmap(sw, sh);
        using (var g = System.Drawing.Graphics.FromImage(small))
        {
            g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.NearestNeighbor;
            g.DrawImage(bmp, new System.Drawing.Rectangle(0, 0, sw, sh), rect, System.Drawing.GraphicsUnit.Pixel);
        }
        using (var g = System.Drawing.Graphics.FromImage(bmp))
        {
            g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.NearestNeighbor;
            g.DrawImage(small, rect);
        }
    }

    void RedactSession(AnnoCanvas view)
    {
        var regs = RedactPatterns();
        if (Shot != null)
        {
            foreach (var item in Ocr)
            {
                if (RedactString(item.Text, regs) == item.Text) continue;
                int w = item.W > 4 ? (int)item.W : 80;
                int h = item.H > 4 ? (int)item.H : 22;
                Pixelate(Shot, new System.Drawing.Rectangle((int)item.Cx - w / 2, (int)item.Cy - h / 2, w, h));
            }
            try
            {
                var software = Task.Run(async () => await SoftwareBitmapFromBmp(Shot)).GetAwaiter().GetResult();
                var gray = SoftwareBitmap.Convert(software, BitmapPixelFormat.Gray8);
                var detector = FaceDetector.CreateAsync().AsTask().GetAwaiter().GetResult();
                foreach (var face in detector.DetectFacesAsync(gray).AsTask().GetAwaiter().GetResult())
                {
                    var box = face.FaceBox;
                    Pixelate(Shot, new System.Drawing.Rectangle(box.X, box.Y, box.Width, box.Height));
                }
            }
            catch { }
            try { if (!string.IsNullOrEmpty(ShotFile)) Shot.Save(ShotFile, System.Drawing.Imaging.ImageFormat.Png); } catch { }
        }
        foreach (var it in view.Items)
        {
            if (it is PinItem pi)
            {
                pi.Pin.OcrNearby = RedactString(pi.Pin.OcrNearby, regs);
                pi.Pin.Note = RedactString(pi.Pin.Note, regs);
            }
        }
    }

    public SyncCfg LoadSync()
    {
        string mode = "local", share = "", server = "", token = "", project = "inbox";
        bool fileRedact = false;
        var file = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "DingAI", "settings.json");
        try
        {
            var obj = JsonNode.Parse(File.ReadAllText(file)) as JsonObject;
            if (obj != null)
            {
                mode = obj["mode"]?.ToString() ?? mode;
                share = obj["share_dir"]?.ToString() ?? "";
                server = obj["server_url"]?.ToString() ?? "";
                token = obj["token"]?.ToString() ?? "";
                var named = obj["project"]?.ToString();
                if (!string.IsNullOrEmpty(named)) project = named;
                fileRedact = obj["redact"]?.ToString() == "true";
            }
        }
        catch { }
        string Env(string name) => Environment.GetEnvironmentVariable(name);
        if (!string.IsNullOrEmpty(Env("DINGAI_MODE"))) mode = Env("DINGAI_MODE");
        if (!string.IsNullOrEmpty(Env("DINGAI_SHARE_DIR"))) share = Env("DINGAI_SHARE_DIR");
        var urls = Env("DINGAI_TEAM_URLS") ?? Env("ANNO_TEAM_URLS");
        if (!string.IsNullOrEmpty(urls)) server = urls;
        if (!string.IsNullOrEmpty(Env("DINGAI_TEAM_TOKEN"))) token = Env("DINGAI_TEAM_TOKEN");
        if (!string.IsNullOrEmpty(Env("DINGAI_PROJECT_NAME"))) project = Env("DINGAI_PROJECT_NAME");
        if (mode == "local" && !string.IsNullOrEmpty(share)) mode = "folder";
        if (mode == "local" && !string.IsNullOrEmpty(server)) mode = "server";
        if (mode != "folder" && mode != "server") mode = "local";
        project = project.Replace("/", "-").Replace("\\", "-");
        if (string.IsNullOrEmpty(project)) project = "inbox";
        var redactEnv = Env("DINGAI_REDACT");
        bool redact = redactEnv == "1" ? true : redactEnv == "0" ? false : fileRedact;
        var hosts = server.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        return new SyncCfg(mode, share, hosts, token ?? "", project, redact);
    }

    public void Publish(string json, string noteFile, string shotFile)
    {
        var cfg = LoadSync();
        if (cfg.Mode == "local") return;
        try
        {
            if (cfg.Mode == "folder" && !string.IsNullOrEmpty(cfg.Share)) WriteFolder(cfg, json, noteFile, shotFile);
            if (cfg.Mode == "server")
            {
                foreach (var host in cfg.Hosts)
                    if (PostNote(host, cfg.Token, json, shotFile)) break;
            }
        }
        catch { }
    }

    static void AtomicBytes(string path, byte[] data)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        var tmp = path + ".tmp";
        File.WriteAllBytes(tmp, data);
        File.Move(tmp, path, true);
    }

    void WriteFolder(SyncCfg cfg, string json, string noteFile, string shotFile)
    {
        var noteId = Path.GetFileNameWithoutExtension(noteFile);
        var root = Path.Combine(cfg.Share, "projects", cfg.Project);
        AtomicBytes(Path.Combine(root, "notes", noteId + ".json"), Encoding.UTF8.GetBytes(json));
        var shotName = string.IsNullOrEmpty(shotFile) ? "" : Path.GetFileName(shotFile);
        if (!string.IsNullOrEmpty(shotName) && File.Exists(shotFile))
            AtomicBytes(Path.Combine(root, "shots", shotName), File.ReadAllBytes(shotFile));
        var pins = (JsonNode.Parse(json) as JsonObject)?["pins"] as JsonArray;
        if (pins == null) return;
        foreach (var pin in pins)
        {
            if (pin is not JsonObject row) continue;
            var copy = (JsonObject)row.DeepClone();
            copy["note_id"] = noteId;
            copy["project"] = cfg.Project;
            copy["screenshot"] = shotName;
            var pinId = copy["id"]?.ToString() ?? "0";
            AtomicBytes(Path.Combine(root, "pins", noteId + "--" + pinId + ".json"),
                Encoding.UTF8.GetBytes(copy.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true })));
        }
    }

    bool PostNote(string host, string token, string json, string shotFile)
    {
        try
        {
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
            var req = new HttpRequestMessage(HttpMethod.Post, host.TrimEnd('/') + "/api/note");
            req.Content = new StringContent(json, Encoding.UTF8, "application/json");
            if (!string.IsNullOrEmpty(token)) req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            var resp = http.Send(req);
            if (!resp.IsSuccessStatusCode) return false;
            var body = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            var name = (JsonNode.Parse(body) as JsonObject)?["shot_name"]?.ToString();
            if (string.IsNullOrEmpty(name) || string.IsNullOrEmpty(shotFile) || !File.Exists(shotFile)) return true;
            var shotReq = new HttpRequestMessage(HttpMethod.Post, host.TrimEnd('/') + "/api/shot/" + Uri.EscapeDataString(name));
            shotReq.Content = new ByteArrayContent(File.ReadAllBytes(shotFile));
            shotReq.Content.Headers.ContentType = new MediaTypeHeaderValue("image/png");
            if (!string.IsNullOrEmpty(token)) shotReq.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            http.Send(shotReq);
            return true;
        }
        catch { return false; }
    }

    public string BuildJson(List<Item> items)
    {
        var pins = new JsonArray(); var arrows = new JsonArray(); var boxes = new JsonArray();
        int np = 0, na = 0, nb = 0;
        foreach (var it in items)
        {
            if (it is PinItem pi)
            {
                var p = pi.Pin;
                var near = p.OcrNearby == "OCR…" ? OcrNear(p.X, p.Y) : p.OcrNearby;
                var o = new JsonObject { ["id"] = p.Id, ["x_px"] = p.X, ["y_px"] = p.Y, ["ocr_nearby"] = near,
                    ["pin_type"] = string.IsNullOrEmpty(p.PinType) ? "bug" : p.PinType,
                    ["status"] = string.IsNullOrEmpty(p.Status) ? "open" : p.Status };
                if (!string.IsNullOrEmpty(p.Note)) o["note"] = p.Note;
                o["anchor"] = new JsonObject { ["kind"] = p.AnchorKind ?? "viewport" };
                if (!string.IsNullOrEmpty(p.AnchorNote)) o["anchor"]["note"] = p.AnchorNote;
                if (p.WinOwner != null) o["window"] = new JsonObject { ["owner"] = p.WinOwner, ["title"] = p.WinTitle ?? "" };
                var f = p.WinFrame ?? SessWinFrame;
                if (f != null)
                {
                    double nx = (p.X - f[0]) / (double)f[2], ny = (p.Y - f[1]) / (double)f[3];
                    o["window_nx"] = Math.Round(nx, 3); o["window_ny"] = Math.Round(ny, 3);
                }
                pins.Add(o); np++;
            }
            else if (it is ArrowItem ai)
            {
                arrows.Add(new JsonObject { ["id"] = ai.A.Id, ["from_px"] = new JsonArray(ai.A.FromX, ai.A.FromY),
                    ["to_px"] = new JsonArray(ai.A.ToX, ai.A.ToY), ["color"] = ai.A.Color, ["width"] = ai.A.Width });
                na++;
            }
            else if (it is BoxItem bi)
            {
                boxes.Add(new JsonObject { ["id"] = bi.B.Id, ["rect_px"] = new JsonArray(bi.B.X, bi.B.Y, bi.B.W, bi.B.H),
                    ["color"] = bi.B.Color, ["width"] = bi.B.Width, ["shape"] = string.IsNullOrEmpty(bi.B.Shape) ? "rect" : bi.B.Shape });
                nb++;
            }
        }
        var root = new JsonObject
        {
            ["schema"] = "dingai-desktop-v1",
            ["tool"] = "dingai",
            ["schema_compat"] = "anno-desktop-v1",
            ["platform"] = "windows",
            ["ts"] = DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss.fffK"),
            ["duration_s"] = Math.Round((DateTime.Now - T0).TotalSeconds, 1),
            ["machine"] = Environment.MachineName,
            ["user"] = Environment.UserName,
            ["app"] = new JsonObject { ["pid"] = AppPid, ["name"] = AppName, ["path"] = AppPath },
            ["screen"] = new JsonObject { ["width_px"] = ScreenW, ["height_px"] = ScreenH, ["scale"] = Scale },
            ["window"] = new JsonObject { ["title"] = AppTitle, ["frame_px"] = SessWinFrame != null ? new JsonArray(SessWinFrame[0], SessWinFrame[1], SessWinFrame[2], SessWinFrame[3]) : null },
            ["pins"] = pins, ["arrows"] = arrows, ["boxes"] = boxes,
            ["pin_count"] = np, ["arrow_count"] = na, ["box_count"] = nb,
            ["screenshot"] = Path.GetFileName(ShotFile),
            ["screen_capture_ok"] = Shot != null,
            ["live"] = Live,
            ["project"] = LoadSync().Project,
            ["redacted"] = LoadSync().Redact,
            ["handoff_rules"] = HandoffRules(),
        };
        return root.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
    }

    public const string DefaultHandoffRules =
        "- Make the smallest change that fixes the pinned issue. Do not refactor or rewrite surrounding code.\n" +
        "- Follow the project's ARCHITECTURE or conventions file before adding code.\n" +
        "- Touch only code related to the pinned element.\n" +
        "- Do not add dependencies or files unless you state why.\n" +
        "- Explain the diff and how it was verified.";

    public string ProjectDir()
    {
        var env = Environment.GetEnvironmentVariable("DINGAI_PROJECT");
        if (!string.IsNullOrWhiteSpace(env)) return env;
        var pointer = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "DingAI", "project.txt");
        try
        {
            var t = File.ReadAllText(pointer).Trim();
            if (t.Length > 0) return t;
        }
        catch { }
        return null;
    }

    public string HandoffRules()
    {
        var paths = new List<string>();
        var project = ProjectDir();
        if (!string.IsNullOrEmpty(project)) paths.Add(Path.Combine(project, ".dingai", "handoff-rules.md"));
        paths.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "DingAI", "handoff-rules.md"));
        foreach (var path in paths)
        {
            try
            {
                var t = File.ReadAllText(path).Trim();
                if (t.Length > 0) return t;
            }
            catch { }
        }
        return DefaultHandoffRules;
    }

    public string HandoffPrompt(string json) =>
        HandoffRules() + "\n\nApply the rules above to this DingAI note. The pinned element is the only scope.\n\n" + json;

    string Git(string dir, params string[] args)
    {
        try
        {
            var p = new Process();
            p.StartInfo.FileName = "git";
            p.StartInfo.WorkingDirectory = dir;
            p.StartInfo.RedirectStandardOutput = true;
            p.StartInfo.RedirectStandardError = true;
            p.StartInfo.CreateNoWindow = true;
            foreach (var a in args) p.StartInfo.ArgumentList.Add(a);
            p.Start();
            var text = p.StandardOutput.ReadToEnd();
            p.WaitForExit();
            return p.ExitCode == 0 ? text : null;
        }
        catch { return null; }
    }

    public void RecordHandoffBaseline()
    {
        var project = ProjectDir();
        if (string.IsNullOrEmpty(project) || !Directory.Exists(project)) return;
        var head = Git(project, "rev-parse", "HEAD");
        if (string.IsNullOrEmpty(head)) return;
        var names = Directory.GetFileSystemEntries(project).Select(Path.GetFileName).Where(n => n != ".git").OrderBy(n => n);
        var topsArr = new JsonArray();
        foreach (var n in names) topsArr.Add(JsonValue.Create(n));
        var obj = new JsonObject
        {
            ["head"] = head.Trim(),
            ["project"] = project,
            ["top_dirs"] = topsArr,
            ["at"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
        };
        var dir = Path.Combine(project, ".dingai");
        try
        {
            Directory.CreateDirectory(dir);
            File.WriteAllText(Path.Combine(dir, "last-handoff.json"), obj.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
        }
        catch { }
    }

    public void CheckScope()
    {
        var project = ProjectDir();
        if (string.IsNullOrEmpty(project))
        {
            WF.MessageBox.Show("没有项目目录。设置 DINGAI_PROJECT，或把路径写进用户目录下的 DingAI/project.txt。", "改动范围");
            return;
        }
        JsonObject baseObj = null;
        try
        {
            baseObj = JsonNode.Parse(File.ReadAllText(Path.Combine(project, ".dingai", "last-handoff.json"))) as JsonObject;
        }
        catch { }
        string baseHead = null;
        try { baseHead = baseObj?["head"]?.GetValue<string>(); } catch { }
        if (string.IsNullOrEmpty(baseHead))
        {
            WF.MessageBox.Show("还没有交接记录。完成一次批注后再检查。", "改动范围");
            return;
        }
        var head = (Git(project, "rev-parse", "HEAD") ?? "").Trim();
        var files = new List<(string path, int lines)>();
        var diff = Git(project, "diff", "--numstat", "--no-renames", baseHead) ?? "";
        var total = 0;
        foreach (var line in diff.Split('\n'))
        {
            var parts = line.Split('\t');
            if (parts.Length < 3 || parts[2] == ".dingai/last-handoff.json") continue;
            int add = int.TryParse(parts[0], out var a) ? a : 0;
            int del = int.TryParse(parts[1], out var d) ? d : 0;
            files.Add((parts[2], add + del));
            total += add + del;
        }
        var seen = new HashSet<string>(files.Select(f => f.path));
        foreach (var line in (Git(project, "ls-files", "--others", "--exclude-standard") ?? "").Split('\n'))
        {
            var path = line.Trim();
            if (path.Length == 0 || path == ".dingai/last-handoff.json" || seen.Contains(path)) continue;
            files.Add((path, 0));
            seen.Add(path);
        }
        string[] prefixes = null;
        try
        {
            prefixes = File.ReadAllLines(Path.Combine(project, ".dingai", "scope.txt"))
                .Select(l => l.Split('#')[0].Trim()).Where(l => l.Length > 0).ToArray();
        }
        catch { }
        var tops = new HashSet<string>();
        if (baseObj?["top_dirs"] is JsonArray arr)
            foreach (var n in arr)
            {
                try { tops.Add(n.GetValue<string>()); } catch { }
            }
        var depNames = new HashSet<string> { "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "packages.lock.json", "Package.swift", "Package.resolved", "go.mod", "go.sum", "requirements.txt", "poetry.lock", "Pipfile", "Pipfile.lock", "Cargo.toml", "Cargo.lock", "composer.json", "composer.lock", "Gemfile", "Gemfile.lock", "Podfile", "Podfile.lock" };
        var outside = new List<string>(); var deps = new List<string>(); var modules = new List<string>();
        foreach (var f in files)
        {
            if (prefixes != null && !prefixes.Any(p => f.path == p || f.path.StartsWith(p))) outside.Add(f.path);
            var name = Path.GetFileName(f.path);
            if (depNames.Contains(name) || name.EndsWith(".csproj")) deps.Add(f.path);
            var first = f.path.Split('/')[0];
            if (!tops.Contains(first)) modules.Add(f.path);
        }
        var lines = new List<string> { files.Count + " 个文件，" + total + " 行，相对 " + baseHead.Substring(0, Math.Min(12, baseHead.Length)) };
        var moved = head != baseHead;
        if (moved) lines.Add("HEAD 已经前进。退回不会重置提交历史。");
        var paths = new List<string>();
        void Add(string title, List<string> list)
        {
            if (list.Count == 0) return;
            lines.Add(title);
            foreach (var p in list.Take(30)) lines.Add("  " + p);
            foreach (var p in list) if (!paths.Contains(p)) paths.Add(p);
        }
        Add("范围外（.dingai/scope.txt）：", outside);
        Add("新的依赖或锁文件：", deps);
        Add("新的顶层文件或目录：", modules);
        if (total > 400 || files.Count > 8)
        {
            lines.Add("改动偏大：" + files.Count + " 个文件，" + total + " 行。");
            foreach (var f in files) if (!paths.Contains(f.path)) paths.Add(f.path);
        }
        if (paths.Count == 0) lines.Add("没有超出范围的改动。");
        var text = string.Join("\n", lines);
        if (paths.Count == 0 || moved)
        {
            WF.MessageBox.Show(text, "改动范围");
            return;
        }
        if (WF.MessageBox.Show(text + "\n\n退回上面列出的改动？", "改动范围", WF.MessageBoxButtons.YesNo) != WF.DialogResult.Yes) return;
        var tracked = new HashSet<string>((Git(project, new[] { "ls-files", "--" }.Concat(paths).ToArray()) ?? "").Split('\n').Select(s => s.Trim()).Where(s => s.Length > 0));
        var restore = paths.Where(tracked.Contains).ToList();
        if (restore.Count > 0) Git(project, new[] { "restore", "--source", head, "--worktree", "--staged", "--" }.Concat(restore).ToArray());
        foreach (var path in paths)
        {
            if (tracked.Contains(path) || path.Contains("..") || Path.IsPathRooted(path)) continue;
            var full = Path.Combine(project, path);
            if (File.Exists(full)) try { File.Delete(full); } catch { }
        }
    }

    public string Stamp() => DateTime.Now.ToString("yyyyMMdd-HHmmss");
}

#region 热键消息窗

internal class HotkeySink
{
    public HwndSource Src;
    public HotkeySink(Action onHotkey)
    {
        Src = new HwndSource(new HwndSourceParameters("AnnoHotkey") { ParentWindow = new IntPtr(-3) }); // HWND_MESSAGE
        Src.AddHook((IntPtr hwnd, int msg, IntPtr w, IntPtr l, ref bool r) =>
        {
            if (msg == Win32.WM_HOTKEY && w.ToInt32() == 1) onHotkey();
            return IntPtr.Zero;
        });
        Win32.RegisterHotKey(Src.Handle, 1, Win32.MOD_CONTROL | Win32.MOD_ALT, Win32.VK_A);
    }
}

#endregion

#region 批注窗口(WPF 代码构建,无 XAML)

internal class AnnotationWindow : Window
{
    public readonly Controller C;
    public new AnnoCanvas Canvas;

    public AnnotationWindow(Controller c)
    {
        C = c;
        WindowStyle = WindowStyle.None; ResizeMode = ResizeMode.NoResize;
        Topmost = true; ShowInTaskbar = false; ShowActivated = true;
        WindowState = WindowState.Maximized;
        if (c.Live) { AllowsTransparency = true; Background = Brushes.Transparent; }
        else Background = Brushes.Black;

        Canvas = new AnnoCanvas(c) { Background = c.Live ? Brushes.Transparent : Brushes.Black };
        Content = Canvas;
        // 前台主窗 frame(物理像素)
        var fg = Win32.GetForegroundWindow();
        if (fg != IntPtr.Zero && Win32.GetWindowRect(fg, out var r))
            C.SessWinFrame = new[] { r.Left, r.Top, r.Right - r.Left, r.Bottom - r.Top };
        DispatcherTimer pass = null;
        Loaded += (s, e) =>
        {
            var m = PresentationSource.FromVisual(this).CompositionTarget.TransformToDevice.M11;
            C.Scale = m;
            Canvas.Init();
            if (!C.Live) return;
            pass = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(40) };
            pass.Tick += (_, _) => ApplyPass();
            pass.Start();
        };
        Closed += (s, e) => pass?.Stop();
    }

    void ApplyPass()
    {
        var hwnd = new WindowInteropHelper(this).Handle;
        if (hwnd == IntPtr.Zero) return;
        bool alt = (Win32.GetAsyncKeyState(Win32.VK_MENU) & 0x8000) != 0;
        int ex = Win32.GetWindowLong(hwnd, Win32.GWL_EXSTYLE);
        int next = alt ? (ex | Win32.WS_EX_TRANSPARENT) : (ex & ~Win32.WS_EX_TRANSPARENT);
        if (next != ex) Win32.SetWindowLong(hwnd, Win32.GWL_EXSTYLE, next);
    }
}

internal class AnnoCanvas : Canvas
{
    readonly Controller C;
    public Image Bg;
    public List<Item> Items = new();
    int _nextId = 1;
    Point? _draftFrom, _draftTo;
    public string CurColor = "red"; public int CurWidth = 4; public int DrawMode = 1;   // 1箭头 2方框 3椭圆 4聚光
    public string NextPinType = "bug";
    public bool StepMode;
    public List<(int X, int Y, string Note)> Steps = new();
    bool _spotDim;
    UIElement _draftPreview;
    TextBox _noteField; int _noteIdx;
    List<UIElement> _markers = new();   // 当前会话的钉/箭/框元素(撤销时移除)
    UIElement _toolbar;

    public AnnoCanvas(Controller c) { C = c; }

    public void Init()
    {
        // 冻结模式才铺截图。实时模式保持透明,导出时再截。
        if (C.Shot != null)
        {
            Bg = new Image
            {
                Source = ToWpfBitmap(C.Shot),
                Width = ActualWidth > 0 ? ActualWidth : SystemParameters.PrimaryScreenWidth,
                Height = ActualHeight > 0 ? ActualHeight : SystemParameters.PrimaryScreenHeight,
                Stretch = Stretch.Fill,
            };
            SetLeft(Bg, 0); SetTop(Bg, 0);
            Children.Add(Bg);
        }
        Focusable = true;
        MouseLeftButtonDown += OnDown;
        MouseMove += OnMove;
        MouseLeftButtonUp += OnUp;
        KeyDown += OnKey;
        KeyUp += OnKeyUp;
        MouseEnter += (s, e) => Keyboard.Focus(this);
        Loaded += (s, e) => { InstallToolbar(); Keyboard.Focus(this); };
        SizeChanged += (s, e) => { if (Bg != null) { Bg.Width = e.NewSize.Width; Bg.Height = e.NewSize.Height; } };
    }

    static BitmapSource ToWpfBitmap(System.Drawing.Bitmap bmp)
    {
        var data = bmp.LockBits(new System.Drawing.Rectangle(0, 0, bmp.Width, bmp.Height),
            System.Drawing.Imaging.ImageLockMode.ReadOnly, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        var bs = BitmapSource.Create(bmp.Width, bmp.Height, 96, 96, PixelFormats.Bgra32, null,
            data.Scan0, Math.Abs(data.Stride) * bmp.Height, data.Stride);
        bmp.UnlockBits(data);
        return bs;
    }

    // DIP(鼠标) ↔ 截图像素(物理)
    (int, int) ToPx(Point p) => ((int)(p.X * C.Scale), (int)(p.Y * C.Scale));
    Point ToDip(int x, int y) => new(x / C.Scale, y / C.Scale);

    #region 交互

    void OnDown(object s, MouseButtonEventArgs e)
    {
        CommitNoteField();
        Keyboard.Focus(this);
        _draftFrom = e.GetPosition(this); _draftTo = _draftFrom;
        ClearPreview();
    }
    void OnMove(object s, MouseEventArgs e)
    {
        if (_draftFrom == null) return;
        _draftTo = e.GetPosition(this);
        RedrawPreview();
    }
    void OnUp(object s, MouseButtonEventArgs e)
    {
        var from = _draftFrom; var to = _draftTo;
        _draftFrom = _draftTo = null; ClearPreview();
        if (from == null || to == null) return;
        var dist = Math.Sqrt((to.Value.X - from.Value.X) * (to.Value.X - from.Value.X) + (to.Value.Y - from.Value.Y) * (to.Value.Y - from.Value.Y)) * C.Scale;
        if (dist < 7) AddPin(from.Value);
        else if (DrawMode == 1) AddArrow(from.Value, to.Value);
        else AddBox(from.Value, to.Value);
    }
    void OnKey(object s, KeyEventArgs e)
    {
        if (e.Key == Key.Escape) C.Finish(true);
        else if (e.Key == Key.Z && (Keyboard.Modifiers & ModifierKeys.Control) != 0) Undo();
        else if (e.Key == Key.B) NextPinType = "bug";
        else if (e.Key == Key.C) NextPinType = "change";
        else if (e.Key == Key.Q) NextPinType = "question";
        else if (e.Key == Key.V && !e.IsRepeat) C.StartVoice();
        else if (e.Key == Key.G) StepMode = !StepMode;
    }

    void OnKeyUp(object s, KeyEventArgs e)
    {
        if (e.Key != Key.V) return;
        var text = C.StopVoice();
        if (string.IsNullOrEmpty(text)) return;
        var pin = Items.LastOrDefault(it => it is PinItem) as PinItem;
        if (pin == null) return;
        pin.Pin.Note = string.IsNullOrEmpty(pin.Pin.Note) ? text : pin.Pin.Note + " " + text;
    }

    public void AddPin(Point p)
    {
        var (x, y) = ToPx(p);
        var w = C.WindowAt(x, y);
        var pin = new PinRec(_nextId++, x, y)
        {
            OcrNearby = C.OcrNear(x, y),
            WinOwner = w?.Owner, WinTitle = w?.Title,
            WinFrame = w != null ? (int[])w.FramePhys.Clone() : null,
            PinType = NextPinType,
        };
        var uia = C.UiaAt(x, y);
        if (!string.IsNullOrEmpty(uia)) { pin.AnchorKind = "uia"; pin.AnchorNote = uia; }
        Items.Add(new PinItem(pin));
        if (StepMode) Steps.Add((x, y, string.IsNullOrEmpty(pin.Note) ? "Pin at " + x + "," + y : pin.Note));
        RerenderAll();
        BeginNote(Items.Count - 1, p);
    }
    public void AddArrow(Point f, Point t)
    {
        var (fx, fy) = ToPx(f); var (tx, ty) = ToPx(t);
        var a = new ArrowRec(_nextId++, fx, fy, tx, ty, CurColor, CurWidth);
        Items.Add(new ArrowItem(a)); RerenderAll();
    }
    public void AddBox(Point f, Point t)
    {
        var (fx, fy) = ToPx(f); var (tx, ty) = ToPx(t);
        var shape = DrawMode == 3 ? "ellipse" : (DrawMode == 4 ? "spotlight" : "rect");
        var b = new BoxRec(_nextId++, Math.Min(fx, tx), Math.Min(fy, ty),
            Math.Abs(tx - fx), Math.Abs(ty - fy), CurColor, CurWidth) { Shape = shape };
        Items.Add(new BoxItem(b)); RerenderAll();
    }
    public void DebugAddPin(double px, double py) => AddPin(ToDip((int)px, (int)py));
    public void DebugAddArrow(double fx, double fy, double tx, double ty) => AddArrow(ToDip((int)fx, (int)fy), ToDip((int)tx, (int)ty));
    public void DebugAddBox(double fx, double fy, double tx, double ty) => AddBox(ToDip((int)fx, (int)fy), ToDip((int)tx, (int)ty));

    public void Undo()
    {
        CommitNoteField();
        if (Items.Count > 0) Items.RemoveAt(Items.Count - 1);
        RerenderAll();
    }
    public void ClearAll() { CommitNoteField(); Items.Clear(); RerenderAll(); }
    public void RerenderAll()
    {
        foreach (var m in _markers) Children.Remove(m);
        _markers.Clear();
        _spotDim = false;
        var pins = new List<PinRec>();
        foreach (var it in Items)
        {
            if (it is PinItem pi) { DrawPin(pi.Pin); pins.Add(pi.Pin); }
            else if (it is ArrowItem ai) DrawArrow(ai.A);
            else if (it is BoxItem bi) DrawBox(bi.B);
        }
        DrawPinLabels(pins);
    }
    public void RefreshPinSigns() => RerenderAll();   // OCR 到账重绘

    #endregion

    #region 备注(单字段输入框:回车确认/Esc 或点空白跳过)

    public void BeginNote(int idx, Point p)
    {
        CommitNoteField();
        var tb = new TextBox
        {
            Width = 226, FontSize = 13,
            ToolTip = UiText.T("note"),
        };
        double fx = Math.Min(p.X + 14, ActualWidth - 240);
        double fy = Math.Min(Math.Max(p.Y - 30, 8), ActualHeight - 36);
        SetLeft(tb, fx); SetTop(tb, fy);
        tb.KeyDown += (s, e) =>
        {
            if (e.Key == Key.Enter) { CommitNoteField(); Keyboard.Focus(this); e.Handled = true; }
            else if (e.Key == Key.Escape) { tb.Text = ""; CommitNoteField(); Keyboard.Focus(this); e.Handled = true; }
        };
        tb.LostFocus += (s, e) => CommitNoteField();
        Children.Add(tb); _noteField = tb; _noteIdx = idx;
        tb.Focus();
    }

    public void CommitNoteField()
    {
        if (_noteField == null) return;
        var tb = _noteField; _noteField = null;
        var txt = tb.Text?.Trim();
        if (_noteIdx >= 0 && _noteIdx < Items.Count && Items[_noteIdx] is PinItem pi && !string.IsNullOrEmpty(txt))
            pi.Pin.Note = txt;
        Children.Remove(tb);
        RerenderAll();
    }

    #endregion

    #region 绘制(视觉语言对齐 macOS 版:红钉+XY虚线+黑底白字气泡)

    static Brush ColorOf(string n) => n switch
    {
        "yellow" => Brushes.Gold, "cyan" => Brushes.Cyan, _ => Brushes.Red,
    };

    void Track(UIElement e) { Children.Add(e); _markers.Add(e); }

    int PinNumber(PinRec p)
    {
        int n = 0;
        foreach (var it in Items)
        {
            if (it is PinItem pi)
            {
                n++;
                if (pi.Pin.Id == p.Id) return n;
            }
        }
        return p.Id;
    }

    void DrawPin(PinRec p)
    {
        var pt = ToDip(p.X, p.Y);
        var dot = new Ellipse { Width = 14, Height = 14, Fill = Brushes.White };
        var inner = new Ellipse { Width = 10, Height = 10, Fill = Brushes.Red };
        SetLeft(dot, pt.X - 7); SetTop(dot, pt.Y - 7);
        SetLeft(inner, pt.X - 5); SetTop(inner, pt.Y - 5);
        Track(dot); Track(inner);
        Track(Bubble("#" + PinNumber(p) + "  " + p.X + "," + p.Y, pt.X + 12, pt.Y + 10));
    }

    List<string> LabelLines(PinRec p)
    {
        var lines = new List<string> { p.PinType ?? "bug" };
        if (!string.IsNullOrEmpty(p.Note)) lines.Add("✎ " + Trunc(p.Note, 34));
        if (!string.IsNullOrEmpty(p.WinOwner)) lines.Add("win: " + p.WinOwner + (string.IsNullOrEmpty(p.WinTitle) ? "" : " · " + Trunc(p.WinTitle, 24)));
        if (C.AppName != null && C.AppName != p.WinOwner) lines.Add("app: " + C.AppName);
        var near = p.OcrNearby == "OCR…" ? C.OcrNear(p.X, p.Y) : p.OcrNearby;
        if (!string.IsNullOrEmpty(near)) lines.Add("ocr: " + Trunc(near.Split(" | ")[0], 34));
        return lines;
    }

    void DrawPinLabels(List<PinRec> pins)
    {
        var callouts = new List<(double ax, double ay, double w, double h, List<string> lines)>();
        var obstacles = new List<(double x, double y, double w, double h)>();
        foreach (var p in pins)
        {
            var pt = ToDip(p.X, p.Y);
            obstacles.Add((pt.X - 8, pt.Y - 8, 16, 16));
            var lines = LabelLines(p);
            callouts.Add((pt.X, pt.Y, 200, 18.0 * lines.Count + 8, lines));
        }
        double bw = ActualWidth > 1 ? ActualWidth : SystemParameters.PrimaryScreenWidth;
        double bh = ActualHeight > 1 ? ActualHeight : SystemParameters.PrimaryScreenHeight;
        var placed = LayoutCallouts(callouts, obstacles, (0, 0, bw, bh));
        foreach (var box in placed)
        {
            if (box.leader)
            {
                Track(new Line { X1 = box.ax, Y1 = box.ay, X2 = box.x, Y2 = box.y + 8,
                    Stroke = Brushes.White, StrokeThickness = 1 });
            }
            Track(Sign(box.lines, box.x, box.y));
        }
    }

    // Same placement rule as core/layout.py.
    static List<(double x, double y, double ax, double ay, bool leader, List<string> lines)> LayoutCallouts(
        List<(double ax, double ay, double w, double h, List<string> lines)> callouts,
        List<(double x, double y, double w, double h)> obstacles,
        (double x, double y, double w, double h) bounds)
    {
        (int dx, int dy, int prefer)[] dirs = { (1, 0, 0), (1, -1, 6), (0, -1, 6), (-1, -1, 6), (-1, 0, 6), (-1, 1, 6), (0, 1, 6), (1, 1, 6) };
        int[] dists = { 18, 32, 48, 68, 96, 132, 176 };
        const double gap = 4;
        var placed = obstacles.Select(o => (o.x, o.y, o.w, o.h)).ToList();
        double Overlap((double x, double y, double w, double h) a, (double x, double y, double w, double h) b)
        {
            double x1 = Math.Max(a.x, b.x - gap), y1 = Math.Max(a.y, b.y - gap);
            double x2 = Math.Min(a.x + a.w, b.x + b.w + gap), y2 = Math.Min(a.y + a.h, b.y + b.h + gap);
            return x2 > x1 && y2 > y1 ? (x2 - x1) * (y2 - y1) : 0;
        }
        double PointDist(double px, double py, (double x, double y, double w, double h) rect)
        {
            double cx = Math.Min(Math.Max(px, rect.x), rect.x + rect.w);
            double cy = Math.Min(Math.Max(py, rect.y), rect.y + rect.h);
            return Math.Sqrt((px - cx) * (px - cx) + (py - cy) * (py - cy));
        }
        var output = new List<(double x, double y, double ax, double ay, bool leader, List<string> lines)>();
        for (int k = 0; k < callouts.Count; k++)
        {
            var c = callouts[k];
            double bestCost = double.MaxValue, bestX = c.ax, bestY = c.ay;
            bool bestLeader = false;
            foreach (var dir in dirs)
            {
                double length = Math.Sqrt(dir.dx * dir.dx + dir.dy * dir.dy);
                if (length == 0) length = 1;
                foreach (var dist in dists)
                {
                    double ox = dir.dx / length * dist, oy = dir.dy / length * dist;
                    double x = c.ax + ox + (dir.dx < 0 ? -c.w : (dir.dx == 0 ? -c.w / 2 : 0));
                    double y = c.ay + oy + (dir.dy < 0 ? -c.h : (dir.dy == 0 ? -c.h / 2 : 0));
                    x = Math.Max(bounds.x, Math.Min(x, bounds.x + bounds.w - c.w));
                    y = Math.Max(bounds.y, Math.Min(y, bounds.y + bounds.h - c.h));
                    var rect = (x, y, c.w, c.h);
                    double hit = placed.Sum(p => Overlap(rect, p));
                    double cost = hit * 10000 + dist + dir.prefer + k * 0.01;
                    if (cost < bestCost)
                    {
                        bestCost = cost; bestX = x; bestY = y;
                        bestLeader = PointDist(c.ax, c.ay, rect) > 14;
                    }
                }
            }
            placed.Add((bestX, bestY, c.w, c.h));
            output.Add((bestX, bestY, c.ax, c.ay, bestLeader, c.lines));
        }
        return output;
    }

    void DrawArrow(ArrowRec a)
    {
        var f = ToDip(a.FromX, a.FromY); var t = ToDip(a.ToX, a.ToY);
        var color = ColorOf(a.Color);
        var line = new Line { X1 = f.X, Y1 = f.Y, X2 = t.X, Y2 = t.Y,
            Stroke = color, StrokeThickness = a.Width / C.Scale,
            StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round };
        Track(line);
        var head = 3.5 * a.Width + 8;
        double ang = Math.Atan2(t.Y - f.Y, t.X - f.X);
        var p1 = new Point(t.X - head * Math.Cos(ang - 0.42), t.Y - head * Math.Sin(ang - 0.42));
        var p2 = new Point(t.X - head * Math.Cos(ang + 0.42), t.Y - head * Math.Sin(ang + 0.42));
        var tri = new Polygon { Points = { t, p1, p2 }, Fill = color };
        Track(tri);
    }

    void DrawBox(BoxRec b)
    {
        var tl = ToDip(b.X, b.Y);
        double w = b.W / C.Scale, h = b.H / C.Scale;
        var stroke = ColorOf(b.Color);
        if (b.Shape == "spotlight")
        {
            if (!_spotDim)
            {
                _spotDim = true;
                double bw = ActualWidth > 1 ? ActualWidth : SystemParameters.PrimaryScreenWidth;
                double bh = ActualHeight > 1 ? ActualHeight : SystemParameters.PrimaryScreenHeight;
                var full = new RectangleGeometry(new Rect(0, 0, bw, bh));
                var hole = new RectangleGeometry(new Rect(tl.X, tl.Y, Math.Max(w, 1), Math.Max(h, 1)));
                Track(new System.Windows.Shapes.Path
                {
                    Data = new CombinedGeometry(GeometryCombineMode.Exclude, full, hole),
                    Fill = new SolidColorBrush(Color.FromArgb(148, 3, 7, 18)),
                });
            }
            var edge = new Rectangle { Width = w, Height = h, Stroke = stroke, StrokeThickness = Math.Max(2, b.Width / C.Scale) };
            SetLeft(edge, tl.X); SetTop(edge, tl.Y);
            Track(edge);
            return;
        }
        Shape shape = b.Shape == "ellipse"
            ? new Ellipse { Width = w, Height = h }
            : new Rectangle { Width = w, Height = h, RadiusX = 4, RadiusY = 4 };
        shape.Stroke = stroke;
        shape.StrokeThickness = b.Width / C.Scale;
        shape.Fill = new SolidColorBrush(Color.FromArgb(40, 255, 60, 60));
        SetLeft(shape, tl.X); SetTop(shape, tl.Y);
        Track(shape);
    }

    UIElement Bubble(string text, double x, double y)
    {
        var b = new Border { Background = new SolidColorBrush(Color.FromArgb(210, 0, 0, 0)),
            CornerRadius = new CornerRadius(6), Padding = new Thickness(6, 2, 6, 2) };
        b.Child = new TextBlock { Text = text, Foreground = Brushes.White, FontSize = 12 };
        SetLeft(b, x); SetTop(b, y);
        return b;
    }
    UIElement Sign(List<string> lines, double x, double y)
    {
        var sp = new StackPanel();
        foreach (var l in lines) sp.Children.Add(new TextBlock { Text = l, Foreground = Brushes.White, FontSize = 12 });
        var b = new Border { Background = new SolidColorBrush(Color.FromArgb(185, 0, 0, 0)),
            BorderBrush = new SolidColorBrush(Color.FromArgb(64, 255, 255, 255)), BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8), Padding = new Thickness(8, 4, 8, 4) };
        b.Child = sp;
        SetLeft(b, x); SetTop(b, y);
        return b;
    }
    static string Trunc(string s, int n) => s.Length > n ? s[..n] + "…" : s;

    void RedrawPreview()
    {
        ClearPreview();
        if (_draftFrom == null || _draftTo == null || _draftFrom == _draftTo) return;
        var f = _draftFrom.Value; var t = _draftTo.Value;
        UIElement e;
        if (DrawMode == 1)
        {
            var head = 3.5 * CurWidth + 8;
            double ang = Math.Atan2(t.Y - f.Y, t.X - f.X);
            e = new Canvas
            {
                Children =
                {
                    new Line { X1 = f.X, Y1 = f.Y, X2 = t.X, Y2 = t.Y, Stroke = ColorOf(CurColor), StrokeThickness = CurWidth / C.Scale },
                    new Polygon { Points = { t,
                        new Point(t.X - head * Math.Cos(ang - 0.42), t.Y - head * Math.Sin(ang - 0.42)),
                        new Point(t.X - head * Math.Cos(ang + 0.42), t.Y - head * Math.Sin(ang + 0.42)) },
                        Fill = ColorOf(CurColor) },
                }
            };
        }
        else
        {
            Shape shape = DrawMode == 3
                ? new Ellipse { Width = Math.Abs(t.X - f.X), Height = Math.Abs(t.Y - f.Y) }
                : new Rectangle { Width = Math.Abs(t.X - f.X), Height = Math.Abs(t.Y - f.Y) };
            shape.Stroke = ColorOf(CurColor);
            shape.StrokeThickness = CurWidth / C.Scale;
            if (DrawMode != 4) shape.Fill = new SolidColorBrush(Color.FromArgb(40, 255, 60, 60));
            SetLeft(shape, Math.Min(f.X, t.X)); SetTop(shape, Math.Min(f.Y, t.Y));
            e = shape;
        }
        Children.Add(e); _draftPreview = e;
    }
    void ClearPreview() { if (_draftPreview != null) { Children.Remove(_draftPreview); _draftPreview = null; } }

    #endregion

    #region 工具条(可拖动;白底黑字按钮)

    void InstallToolbar()
    {
        var bar = new Canvas { Width = 980, Height = 44, Background = new SolidColorBrush(Color.FromArgb(225, 0, 0, 0)) };
        var rd = new Rectangle { Width = 980, Height = 44, RadiusX = 10, RadiusY = 10,
            Stroke = new SolidColorBrush(Color.FromArgb(90, 255, 255, 255)), StrokeThickness = 1 };
        bar.Children.Add(rd);
        double x = 12;
        _modes.Clear();
        void Mode(string title, double w, int mode)
        {
            var b = Btn(bar, ref x, title, w);
            b.Tag = mode;
            b.Click += (s, e) => { DrawMode = mode; HiMode(); };
            _modes.Add((b, mode));
        }
        Mode("➜ 箭头", 70, 1);
        Mode("▭ 方框", 70, 2);
        Mode("◯ 椭圆", 70, 3);
        Mode("◉ 聚光", 70, 4);
        HiMode();
        Btn(bar, ref x, "bug", 46).Click += (s, e) => NextPinType = "bug";
        Btn(bar, ref x, "change", 64).Click += (s, e) => NextPinType = "change";
        Btn(bar, ref x, "question", 72).Click += (s, e) => NextPinType = "question";
        x += 6;
        foreach (var (c, tag) in new[] { ("red", 1), ("yellow", 2), ("cyan", 3) })
        {
            var d = new Border { Width = 20, Height = 20, CornerRadius = new CornerRadius(10),
                Background = ColorOf(c), BorderBrush = Brushes.White, BorderThickness = new Thickness(1.5) };
            d.MouseLeftButtonUp += (s, e) => CurColor = c;
            Canvas.SetLeft(d, x); Canvas.SetTop(d, 12); bar.Children.Add(d); x += 26;
        }
        x += 8;
        foreach (var (w, tag) in new[] { (2, 11), (4, 12), (6, 13) })
        {
            var b = Btn(bar, ref x, "—", 34); b.Tag = tag;
            b.Click += (s, e) => CurWidth = (int)b.Tag - 10;
        }
        x += 10;
        Btn(bar, ref x, "⌘Z撤销", 76).Click += (s, e) => Undo();
        Btn(bar, ref x, "清空", 56).Click += (s, e) => ClearAll();
        Btn(bar, ref x, "复制JSON", 76).Click += (s, e) =>
        {
            CommitNoteField();
            var json = C.BuildJson(Items);
            try { System.Windows.Clipboard.SetText(C.HandoffPrompt(json)); } catch { }
        };
        Btn(bar, ref x, "完成 ✓", 70).Click += (s, e) => C.Finish(true);

        SetLeft(bar, (ActualWidth - bar.Width) / 2); SetTop(bar, 16);
        // 空白处按下拖动整条
        Point? dragOrigin = null; Point? barOrigin = null;
        bar.MouseLeftButtonDown += (s, e) =>
        {
            if (e.OriginalSource is Border || e.OriginalSource is System.Windows.Shapes.Rectangle) return;
            dragOrigin = e.GetPosition(this);
            barOrigin = new Point(GetLeft(bar), GetTop(bar));
            bar.CaptureMouse();
        };
        bar.MouseMove += (s, e) =>
        {
            if (dragOrigin == null) return;
            var cur = e.GetPosition(this);
            SetLeft(bar, Math.Max(4, Math.Min(ActualWidth - bar.Width - 4, barOrigin.Value.X + cur.X - dragOrigin.Value.X)));
            SetTop(bar, Math.Max(4, Math.Min(ActualHeight - bar.Height - 4, barOrigin.Value.Y + cur.Y - dragOrigin.Value.Y)));
        };
        bar.MouseLeftButtonUp += (s, e) => { dragOrigin = null; bar.ReleaseMouseCapture(); };

        Children.Add(bar); _toolbar = bar;
    }

    readonly List<(Button btn, int mode)> _modes = new();
    void HiMode()
    {
        foreach (var (btn, mode) in _modes)
        {
            btn.BorderThickness = DrawMode == mode ? new Thickness(2) : new Thickness(0);
            btn.BorderBrush = Brushes.DodgerBlue;
        }
    }

    Button Btn(Canvas bar, ref double x, string text, double w)
    {
        var b = new Button
        {
            Content = text, Width = w, Height = 28, FontSize = 12, FontWeight = FontWeights.Medium,
            Background = Brushes.White, Foreground = Brushes.Black,
            BorderBrush = Brushes.Transparent, BorderThickness = new Thickness(0),
            Padding = new Thickness(2, 0, 2, 0),
        };
        var rd = new CornerRadius(6);
        b.Resources.Add("Button.CornerRadius", rd);
        SetLeft(b, x); SetTop(b, 8);
        bar.Children.Add(b); x += w + 6;
        return b;
    }

    #endregion
}

#endregion

internal static class Program
{
    [STAThread]
    static void Main(string[] args) => Controller.Inst.Run(args);
}
