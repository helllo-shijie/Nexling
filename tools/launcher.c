/* NexLing 原生启动器（MinGW，无运行时依赖）
 * 职责：立即画一个品牌启动窗（通常 <150ms），后台拉起 PyInstaller 应用，
 *       检测到工作台窗口出现后自动退出。
 * 编译：gcc -O2 -municode -mwindows -o NexLing.exe tools\launcher.c -lgdi32 -luser32
 */
#include <windows.h>

#define ID_TIMER_POLL 1
#define ID_TIMER_ANIM 2

static int g_phase = 0;
static int g_step = 0;
static HINSTANCE g_hinst;
static DWORD g_start_tick;
static volatile HANDLE g_app_proc = NULL;

static unsigned long long epoch_ms(void) {
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    ULARGE_INTEGER u;
    u.LowPart = ft.dwLowDateTime;
    u.HighPart = ft.dwHighDateTime;
    return (u.QuadPart - 116444736000000000ULL) / 10000ULL;
}

/* 数据目录：与应用保持一致 —— NEXLING_HOME 覆盖 > 旧 <安装目录>\.laa 沿用 > %LOCALAPPDATA%\NexLing */
static void data_dir_path(wchar_t *out) {
    wchar_t *home = _wgetenv(L"NEXLING_HOME");
    if (home && *home) {
        wsprintfW(out, L"%s\\.laa", home);
        return;
    }
    wchar_t *local = _wgetenv(L"LOCALAPPDATA");
    if (local && *local) {
        wsprintfW(out, L"%s\\NexLing", local);
        return;
    }
    wchar_t self[MAX_PATH];
    GetModuleFileNameW(NULL, self, MAX_PATH);
    wchar_t *slash = wcsrchr(self, L'\\');
    if (slash) *slash = 0;
    wsprintfW(out, L"%s\\.laa", self);
}

/* 启动分段计时：写入 <数据目录>\launcher.log */
static void log_line(const char *msg) {
    wchar_t dir[MAX_PATH];
    data_dir_path(dir);
    CreateDirectoryW(dir, NULL);
    wchar_t path[MAX_PATH];
    wsprintfW(path, L"%s\\launcher.log", dir);
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    char buf[256];
    int n = wsprintfA(buf, "%I64u %s\r\n", epoch_ms(), msg);
    if (n <= 0) return;
    DWORD written;
    WriteFile(h, buf, (DWORD)n, &written, NULL);
    CloseHandle(h);
}

/* 就绪标记：应用在「主窗骨架可见」时创建 <数据目录>\.shown，
 * 「工作台可输入」时再创建 <数据目录>\.ready。启动器见到任一标记即可收窗。 */
static void ready_flag_path(wchar_t *out) {
    wchar_t dir[MAX_PATH];
    data_dir_path(dir);
    wsprintfW(out, L"%s\\.shown", dir);
}

static int file_exists(const wchar_t *path) {
    return GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES;
}

static int window_ready(void) {
    wchar_t path[MAX_PATH];
    ready_flag_path(path);
    if (file_exists(path)) return 1;
    /* 兼容：仅有「可输入」标记（旧逻辑）时同样收窗 */
    {
        wchar_t dir[MAX_PATH];
        data_dir_path(dir);
        wsprintfW(path, L"%s\\.ready", dir);
        if (file_exists(path)) return 1;
    }
    if (!_wgetenv(L"NEXLING_HOME")) {
        wchar_t self[MAX_PATH];
        GetModuleFileNameW(NULL, self, MAX_PATH);
        wchar_t *slash = wcsrchr(self, L'\\');
        if (slash) *slash = 0;
        wsprintfW(path, L"%s\\.laa\\.shown", self);
        if (file_exists(path)) return 1;
        wsprintfW(path, L"%s\\.laa\\.ready", self);
        if (file_exists(path)) return 1;
    }
    return 0;
}

static const wchar_t *TITLE_SPLASH =
    L"NexLing \u542F\u52A8\u4E2D"; /* NexLing 启动中 */

static void fill(HDC dc, int x, int y, int w, int h, COLORREF c) {
    HBRUSH b = CreateSolidBrush(c);
    RECT r = {x, y, x + w, y + h};
    FillRect(dc, &r, b);
    DeleteObject(b);
}

static void round_fill(HDC dc, int x, int y, int w, int h, int rad, COLORREF c) {
    HBRUSH b = CreateSolidBrush(c);
    HPEN p = CreatePen(PS_SOLID, 1, c);
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, p);
    RoundRect(dc, x, y, x + w, y + h, rad, rad);
    SelectObject(dc, ob);
    SelectObject(dc, op);
    DeleteObject(b);
    DeleteObject(p);
}

static void text(HDC dc, const wchar_t *s, int x, int y, int w, int h,
                 int size, int weight, COLORREF color) {
    HFONT f = CreateFontW(-size, 0, 0, 0, weight, 0, 0, 0, DEFAULT_CHARSET,
                          OUT_TT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                          DEFAULT_PITCH | FF_DONTCARE, L"Microsoft YaHei UI");
    HGDIOBJ old = SelectObject(dc, f);
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, color);
    RECT r = {x, y, x + w, y + h};
    DrawTextW(dc, s, -1, &r, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
    SelectObject(dc, old);
    DeleteObject(f);
}

static void paint(HWND hwnd) {
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(hwnd, &ps);
    RECT rc;
    GetClientRect(hwnd, &rc);
    int w = rc.right, h = rc.bottom;

    fill(dc, 0, 0, w, h, RGB(247, 248, 250));

    /* 品牌标记：三条渐次右移的横条 */
    int mw = 26, mx = (w - mw) / 2;
    round_fill(dc, mx - 6, 44, mw, 4, 2, RGB(206, 216, 232));
    round_fill(dc, mx - 2, 53, mw, 4, 2, RGB(128, 154, 190));
    round_fill(dc, mx + 2, 62, mw, 4, 2, RGB(59, 92, 143));

    text(dc, L"NexLing", 0, 82, w, 34, 26, FW_SEMIBOLD, RGB(27, 36, 48));
    text(dc, L"\u6280\u672F\u7FFB\u8BD1\u5DE5\u4F5C\u53F0", 0, 116, w, 20, 13,
         FW_NORMAL, RGB(122, 134, 153));

    /* 进度条 */
    int bw = 168, bx = (w - bw) / 2, by = 148;
    fill(dc, bx, by, bw, 3, RGB(227, 231, 238));
    int seg = 52;
    int offset = (g_phase * 9) % (bw + seg) - seg;
    int x0 = bx + (offset < 0 ? 0 : offset);
    int x1 = bx + (offset + seg > bw ? bw : offset + seg);
    if (x1 > x0) fill(dc, x0, by, x1 - x0, 3, RGB(59, 92, 143));

    text(dc, L"\u6B63\u5728\u542F\u52A8\u672C\u5730\u5F15\u64CE\u2026", 0, 166, w, 18, 12,
         FW_NORMAL, RGB(154, 164, 179));

    EndPaint(hwnd, &ps);
}

static DWORD WINAPI spawn_app(LPVOID param) {
    (void)param;
    log_line("spawn begin");
    wchar_t self[MAX_PATH];
    GetModuleFileNameW(NULL, self, MAX_PATH);
    wchar_t *slash = wcsrchr(self, L'\\');
    if (slash) *slash = 0;

    wchar_t exe[MAX_PATH];
    wsprintfW(exe, L"%s\\app\\NexLingApp.exe", self);
    if (GetFileAttributesW(exe) == INVALID_FILE_ATTRIBUTES) {
        /* 找不到主程序就明确报错，而不是静默失败让用户以为双击没反应 */
        log_line("app exe MISSING");
        MessageBoxW(NULL,
                    L"\u627E\u4E0D\u5230 app\\NexLingApp.exe\u3002\n"
                    L"\u8BF7\u786E\u8BA4 NexLing \u5B89\u88C5\u76EE\u5F55\u5B8C\u6574\u540E\u91CD\u8BD5\u3002",
                    L"NexLing", MB_ICONERROR | MB_OK);
        return 0;
    }

    SetEnvironmentVariableW(L"NEXLING_LAUNCHED", L"1");

    STARTUPINFOW si = {0};
    PROCESS_INFORMATION pi = {0};
    si.cb = sizeof(si);
    wchar_t cmd[MAX_PATH * 2];
    wsprintfW(cmd, L"\"%s\"", exe);
    if (CreateProcessW(exe, cmd, NULL, NULL, FALSE, 0,
                       NULL, NULL, &si, &pi)) {
        log_line("app spawned");
        CloseHandle(pi.hThread);
        g_app_proc = pi.hProcess; /* 保留句柄：应用退出时启动窗跟着退出 */
    } else {
        log_line("app spawn FAILED");
        MessageBoxW(NULL,
                    L"\u65E0\u6CD5\u542F\u52A8 NexLing \u4E3B\u7A0B\u5E8F\uFF08CreateProcess \u5931\u8D25\uFF09\u3002",
                    L"NexLing", MB_ICONERROR | MB_OK);
    }
    return 0;
}

static LRESULT CALLBACK wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE:
        g_start_tick = GetTickCount();
        SetTimer(hwnd, ID_TIMER_ANIM, 30, NULL);
        SetTimer(hwnd, ID_TIMER_POLL, 60, NULL);
        CloseHandle(CreateThread(NULL, 0, spawn_app, NULL, 0, NULL));
        return 0;
    case WM_TIMER:
        if (wp == ID_TIMER_ANIM) {
            g_phase++;
            InvalidateRect(hwnd, NULL, FALSE);
        } else if (wp == ID_TIMER_POLL) {
            if (window_ready()) {
                /* 主窗骨架已显示：收起启动窗，不等到「可输入」 */
                log_line("window shown flag detected");
                DestroyWindow(hwnd);
            } else if (g_app_proc && WaitForSingleObject(g_app_proc, 0) == WAIT_OBJECT_0) {
                /* 应用进程已退出：启动窗立刻跟着退出，不再空转到 90 秒 */
                log_line("app exited");
                DestroyWindow(hwnd);
            } else if (GetTickCount() - g_start_tick > 90000) {
                log_line("timeout");
                DestroyWindow(hwnd);
            }
        }
        return 0;
    case WM_LBUTTONDOWN:
        SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0);
        return 0;
    case WM_DESTROY:
        KillTimer(hwnd, ID_TIMER_ANIM);
        KillTimer(hwnd, ID_TIMER_POLL);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int WINAPI wWinMain(HINSTANCE hinst, HINSTANCE prev, PWSTR cmdline, int show) {
    (void)prev;
    (void)cmdline;
    (void)show;
    g_hinst = hinst;
    log_line("launcher start");

    /* 清掉上一次运行留下的就绪标记，否则启动窗会立刻消失 */
    {
        wchar_t ready[MAX_PATH];
        ready_flag_path(ready); /* .shown */
        DeleteFileW(ready);
        {
            wchar_t dir[MAX_PATH];
            data_dir_path(dir);
            wsprintfW(ready, L"%s\\.ready", dir);
            DeleteFileW(ready);
        }
    }

    WNDCLASSW wc = {0};
    wc.lpfnWndProc = wndproc;
    wc.hInstance = hinst;
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = NULL;
    wc.lpszClassName = L"NexLingSplashWnd";
    RegisterClassW(&wc);

    int w = 380, h = 200;
    int sw = GetSystemMetrics(SM_CXSCREEN);
    int sh = GetSystemMetrics(SM_CYSCREEN);
    HWND hwnd = CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW, wc.lpszClassName, TITLE_SPLASH,
        WS_POPUP, (sw - w) / 2, (sh - h) / 2 - 40, w, h,
        NULL, NULL, hinst, NULL);
    if (!hwnd) {
        log_line("window creation FAILED");
        MessageBoxW(NULL, L"NexLing \u542F\u52A8\u7A97\u521B\u5EFA\u5931\u8D25\u3002",
                    L"NexLing", MB_ICONERROR | MB_OK);
        return 1;
    }
    ShowWindow(hwnd, SW_SHOWNOACTIVATE);
    UpdateWindow(hwnd);
    log_line("splash shown");

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return 0;
}
