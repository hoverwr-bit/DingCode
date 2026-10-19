// DingAIWin — 系统级批注 Windows 版 v0.1
// 交互与 JSON 契约(dingai-desktop-v1)对齐 macOS 版:
//   Ctrl+Alt+A → 冻结截屏 → 单击落钉(XY辅助线+坐标气泡+信息签+备注输入)/拖拽箭头/框选
//   → Esc/完成 = JSON+剪贴板+落盘(%USERPROFILE%\DingAI\notes|shots)
// 托盘常驻(自绘图钉图标);--auto-test 自动模式(无人工交互,落样例后退出)

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using Windows.Graphics.Imaging;
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

namespace DingAIWin;

#region Win32

internal static class Win32
{
    [DllImport("user32.dll")] public static extern bool RegisterHotKey(IntPtr hWnd, int id, uint mods, uint vk);
    [DllImport("user32.dll")] public static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);

    public const int WM_HOTKEY = 0x0312;
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
}
record ArrowRec(int Id, int FromX, int FromY, int ToX, int ToY, string Color, int Width);
record BoxRec(int Id, int X, int Y, int W, int H, string Color, int Width);
abstract record Item { public int Id = 0; }
record PinItem(PinRec Pin) : Item;
record ArrowItem(ArrowRec A) : Item;
record BoxItem(BoxRec B) : Item;
record OcrText(string Text, double Cx, double Cy);
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
    public volatile bool OcrDone;
    public List<WinCand> WinCands = new();
    public int ScreenW, ScreenH;   // 物理像素
    public double Scale = 1;       // 物理/DIP
    public DateTime T0;

    public void Run(string[] args)
    {
        Directory.CreateDirectory(Path.Combine(OutRoot, "notes"));
        Directory.CreateDirectory(Path.Combine(OutRoot, "shots"));

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

        // 2) 冻结截屏(先截后显,画面必不含自己)
        var bounds = WF.Screen.PrimaryScreen.Bounds;
        ScreenW = bounds.Width; ScreenH = bounds.Height;
        Shot = new System.Drawing.Bitmap(ScreenW, ScreenH);
        using (var g = System.Drawing.Graphics.FromImage(Shot))
            g.CopyFromScreen(bounds.Left, bounds.Top, 0, 0, Shot.Size);

        ShotFile = Path.Combine(OutRoot, "shots", $"anno-{Stamp()}.png");
        Shot.Save(ShotFile, System.Drawing.Imaging.ImageFormat.Png);

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

        // 4) 后台 OCR 全图
        Task.Run(async () =>
        {
            var items = await RunOcr(Shot);
            Ocr = items; OcrDone = true;
            await Application.Current.Dispatcher.InvokeAsync(() => Canvas?.RefreshPinSigns());
        });
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
                        outList.Add(new OcrText(t, b.X + b.Width / 2, b.Y + b.Height / 2));
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

    public void Finish(bool clipboard)
    {
        var view = Overlay?.Canvas; if (view == null) return;
        view.CommitNoteField();
        var json = BuildJson(view.Items);
        var path = Path.Combine(OutRoot, "notes", $"anno-{Stamp()}.json");
        File.WriteAllText(path, json);
        if (clipboard)
        {
            try { System.Windows.Clipboard.SetText(HandoffPrompt(json)); } catch { }
        }
        Overlay.Close(); Overlay = null; Shot?.Dispose(); Shot = null;
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
                var o = new JsonObject { ["id"] = p.Id, ["x_px"] = p.X, ["y_px"] = p.Y, ["ocr_nearby"] = near };
                if (!string.IsNullOrEmpty(p.Note)) o["note"] = p.Note;
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
                    ["color"] = bi.B.Color, ["width"] = bi.B.Width });
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
            ["screen_capture_ok"] = true,
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
        Background = Brushes.Black;

        Canvas = new AnnoCanvas(c) { Background = Brushes.Black };
        Content = Canvas;
        // 前台主窗 frame(物理像素)
        var fg = Win32.GetForegroundWindow();
        if (fg != IntPtr.Zero && Win32.GetWindowRect(fg, out var r))
            C.SessWinFrame = new[] { r.Left, r.Top, r.Right - r.Left, r.Bottom - r.Top };
        Loaded += (s, e) =>
        {
            var m = PresentationSource.FromVisual(this).CompositionTarget.TransformToDevice.M11;
            C.Scale = m;
            Canvas.Init();
        };
    }
}

internal class AnnoCanvas : Canvas
{
    readonly Controller C;
    public Image Bg;
    public List<Item> Items = new();
    int _nextId = 1;
    Point? _draftFrom, _draftTo;
    public string CurColor = "red"; public int CurWidth = 4; public int DrawMode = 1;   // 1=箭头 2=方框
    UIElement _draftPreview;
    TextBox _noteField; int _noteIdx;
    List<UIElement> _markers = new();   // 当前会话的钉/箭/框元素(撤销时移除)
    UIElement _toolbar;

    public AnnoCanvas(Controller c) { C = c; }

    public void Init()
    {
        // 背景=冻结截图铺满(物理→DIP 由 WPF 自动映射)
        Bg = new Image
        {
            Source = ToWpfBitmap(C.Shot),
            Width = ActualWidth > 0 ? ActualWidth : SystemParameters.PrimaryScreenWidth,
            Height = ActualHeight > 0 ? ActualHeight : SystemParameters.PrimaryScreenHeight,
            Stretch = Stretch.Fill,
        };
        SetLeft(Bg, 0); SetTop(Bg, 0);
        Children.Add(Bg);
        Focusable = true;
        MouseLeftButtonDown += OnDown;
        MouseMove += OnMove;
        MouseLeftButtonUp += OnUp;
        KeyDown += OnKey;
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
        };
        Items.Add(new PinItem(pin));
        DrawPin(pin);
        BeginNote(Items.Count - 1, p);
    }
    public void AddArrow(Point f, Point t)
    {
        var (fx, fy) = ToPx(f); var (tx, ty) = ToPx(t);
        var a = new ArrowRec(_nextId++, fx, fy, tx, ty, CurColor, CurWidth);
        Items.Add(new ArrowItem(a)); DrawArrow(a);
    }
    public void AddBox(Point f, Point t)
    {
        var (fx, fy) = ToPx(f); var (tx, ty) = ToPx(t);
        var b = new BoxRec(_nextId++, Math.Min(fx, tx), Math.Min(fy, ty),
            Math.Abs(tx - fx), Math.Abs(ty - fy), CurColor, CurWidth);
        Items.Add(new BoxItem(b)); DrawBox(b);
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
        foreach (var it in Items)
        {
            if (it is PinItem pi) DrawPin(pi.Pin);
            else if (it is ArrowItem ai) DrawArrow(ai.A);
            else if (it is BoxItem bi) DrawBox(bi.B);
        }
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
            ToolTip = "回车确认,Esc 跳过",
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

    void DrawPin(PinRec p)
    {
        var pt = ToDip(p.X, p.Y);
        // XY 辅助线
        var gx = new Line { X1 = 0, Y1 = pt.Y, X2 = ActualWidth, Y2 = pt.Y, StrokeThickness = 1,
            Stroke = new SolidColorBrush(Color.FromArgb(190, 255, 80, 80)), StrokeDashArray = new DoubleCollection { 6, 5 } };
        var gy = new Line { X1 = pt.X, Y1 = 0, X2 = pt.X, Y2 = ActualHeight, StrokeThickness = 1,
            Stroke = new SolidColorBrush(Color.FromArgb(190, 255, 80, 80)), StrokeDashArray = new DoubleCollection { 6, 5 } };
        Track(gx); Track(gy);
        // 钉体(白圈红心)
        var dot = new Ellipse { Width = 14, Height = 14, Fill = Brushes.White };
        var inner = new Ellipse { Width = 10, Height = 10, Fill = Brushes.Red };
        SetLeft(dot, pt.X - 7); SetTop(dot, pt.Y - 7);
        SetLeft(inner, pt.X - 5); SetTop(inner, pt.Y - 5);
        Track(dot); Track(inner);
        // 坐标气泡
        var bub = Bubble($"⌗{p.Id}  {p.X},{p.Y}", pt.X + 12, pt.Y + 10);
        Track(bub);
        // 信息签
        var lines = new List<string>();
        if (!string.IsNullOrEmpty(p.Note)) lines.Add("✎ " + Trunc(p.Note, 34));
        if (!string.IsNullOrEmpty(p.WinOwner)) lines.Add("win: " + p.WinOwner + (string.IsNullOrEmpty(p.WinTitle) ? "" : " · " + Trunc(p.WinTitle, 24)));
        if (C.AppName != null && C.AppName != p.WinOwner) lines.Add("app: " + C.AppName);
        var near = p.OcrNearby == "OCR…" ? C.OcrNear(p.X, p.Y) : p.OcrNearby;
        if (!string.IsNullOrEmpty(near)) lines.Add("ocr: " + Trunc(near.Split(" | ")[0], 34));
        if (lines.Count > 0)
        {
            var h = 18.0 * lines.Count + 8;
            var sign = Sign(lines, pt.X + 12, pt.Y - 8 - h);
            Track(sign);
        }
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
        var rect = new Rectangle
        {
            Width = b.W / C.Scale, Height = b.H / C.Scale,
            Stroke = ColorOf(b.Color), StrokeThickness = b.Width / C.Scale,
            Fill = new SolidColorBrush(Color.FromArgb(40, 255, 60, 60)),
            RadiusX = 4, RadiusY = 4,
        };
        SetLeft(rect, tl.X); SetTop(rect, tl.Y);
        Track(rect);
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
            e = new Rectangle
            {
                Width = Math.Abs(t.X - f.X), Height = Math.Abs(t.Y - f.Y),
                Stroke = ColorOf(CurColor), StrokeThickness = CurWidth / C.Scale,
                Fill = new SolidColorBrush(Color.FromArgb(40, 255, 60, 60)),
            };
            SetLeft(e, Math.Min(f.X, t.X)); SetTop(e, Math.Min(f.Y, t.Y));
        }
        Children.Add(e); _draftPreview = e;
    }
    void ClearPreview() { if (_draftPreview != null) { Children.Remove(_draftPreview); _draftPreview = null; } }

    #endregion

    #region 工具条(可拖动;白底黑字按钮)

    void InstallToolbar()
    {
        var bar = new Canvas { Width = 690, Height = 44, Background = new SolidColorBrush(Color.FromArgb(225, 0, 0, 0)) };
        var rd = new Rectangle { Width = 690, Height = 44, RadiusX = 10, RadiusY = 10,
            Stroke = new SolidColorBrush(Color.FromArgb(90, 255, 255, 255)), StrokeThickness = 1 };
        bar.Children.Add(rd);
        double x = 12;
        var arrowBtn = Btn(bar, ref x, "➜ 箭头", 70); arrowBtn.Tag = 21; arrowBtn.Click += (s, e) => { DrawMode = 1; HiMode(); };
        var boxBtn = Btn(bar, ref x, "▭ 方框", 70); boxBtn.Tag = 22; boxBtn.Click += (s, e) => { DrawMode = 2; HiMode(); };
        _modeBtns = (arrowBtn, boxBtn); HiMode();
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

    (Button, Button) _modeBtns;
    void HiMode()
    {
        var (a, b) = _modeBtns;
        a.BorderThickness = DrawMode == 1 ? new Thickness(2) : new Thickness(0);
        b.BorderThickness = DrawMode == 2 ? new Thickness(2) : new Thickness(0);
        a.BorderBrush = Brushes.DodgerBlue; b.BorderBrush = Brushes.DodgerBlue;
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
