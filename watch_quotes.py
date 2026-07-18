#!/usr/bin/env python3
"""股票行情监视器 - 办公隐蔽版（跨平台，Windows / macOS / Linux）。

仅依赖 Python 标准库，Python 3.8+。
数据来源：东方财富公开 API，仅供个人看盘参考。
"""

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(SCRIPT_DIR, 'watchlist.json')
CACHE_FILE = os.path.join(SCRIPT_DIR, '.secids_cache.json')

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

IS_WINDOWS = os.name == 'nt'

# ANSI 颜色（前景）
C_RED = '\033[31m'
C_GREEN = '\033[32m'
C_GRAY = '\033[37m'
C_DARKGRAY = '\033[90m'
C_RESET = '\033[0m'
# 背景色（家庭模式交替行）
C_BG_DARK = '\033[100m'


# ---------- 终端环境 ----------
def enable_windows_ansi():
    """在 Windows 10+ 的原生控制台中启用 ANSI 转义序列支持。"""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def set_title(title):
    """设置终端窗口标题，跨平台。"""
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(str(title))
            return
        except Exception:
            pass
    try:
        sys.stdout.write('\033]0;%s\007' % title)
        sys.stdout.flush()
    except Exception:
        pass


class UnixTerminal:
    """macOS / Linux 下的终端原始输入模式管理（cbreak，保留 Ctrl+C 信号）。"""

    def __init__(self):
        self.fd = None
        self.old_attrs = None

    def setup(self):
        try:
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.old_attrs = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        except Exception:
            self.fd = None
            self.old_attrs = None

    def restore(self):
        if self.fd is not None and self.old_attrs is not None:
            try:
                import termios
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_attrs)
            except Exception:
                pass


def get_key():
    """非阻塞读取按键，返回 'esc' / 'b' / 'f9' / 's' / None。"""
    if IS_WINDOWS:
        try:
            import msvcrt
            if not msvcrt.kbhit():
                return None
            ch = msvcrt.getwch()
            if ch in ('\x00', '\xe0'):
                # 功能键：再读一个扫描码，F9 = 0x43
                ch2 = msvcrt.getwch()
                return 'f9' if ch2 == '\x43' else None
            if ch == '\x1b':
                return 'esc'
            ch = ch.lower()
            if ch == 'b':
                return 'b'
            if ch == 's':
                return 's'
        except Exception:
            pass
        return None
    try:
        import select
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if not r:
            return None
        ch = os.read(sys.stdin.fileno(), 1)
        if ch == b'\x1b':
            # 区分 Esc 与方向键/功能键的转义序列：稍后还有字节则是序列
            r2, _, _ = select.select([sys.stdin], [], [], 0.02)
            if r2:
                seq = os.read(sys.stdin.fileno(), 8)
                if seq == b'[20~':
                    # F9（xterm 序列，iTerm2 / Terminal.app 等均支持）
                    return 'f9'
                return None
            return 'esc'
        ch = ch.decode('utf-8', errors='ignore').lower()
        if ch == 'b':
            return 'b'
        if ch == 's':
            return 's'
    except Exception:
        pass
    return None


def wait_with_keys(interval, has_console):
    """等待 interval 秒，期间轮询按键；返回按键或 None。"""
    if not has_console:
        time.sleep(interval)
        return None
    slept = 0
    while slept < interval * 1000:
        time.sleep(0.1)
        slept += 100
        key = get_key()
        if key:
            return key
    return None


# ---------- 网络 ----------
def _urllib_get(url, timeout):
    """urllib 获取；证书校验失败时依次尝试系统 CA 路径、不验证证书。"""
    req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT,
        'Referer': 'https://quote.eastmoney.com/',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, 'reason', None), ssl.SSLError):
            raise
    # macOS 上 Python 常缺少根证书：尝试系统 CA 路径
    for cafile in ('/etc/ssl/cert.pem', '/opt/homebrew/etc/openssl@3/cert.pem',
                   '/usr/local/etc/openssl@3/cert.pem'):
        if not os.path.exists(cafile):
            continue
        try:
            ctx = ssl.create_default_context(cafile=cafile)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except Exception:
            continue
    # 最后降级为不验证证书
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def _curl_get(url, timeout):
    """用系统 curl 获取（macOS / Linux / Win10+ 均自带）。"""
    return subprocess.check_output([
        'curl', '-sS', '-m', str(int(timeout)),
        '-H', 'User-Agent: ' + USER_AGENT,
        '-H', 'Referer: https://quote.eastmoney.com/',
        url,
    ], stderr=subprocess.DEVNULL)


def _parse_json(body):
    text = body.decode('utf-8', errors='replace').strip()
    if not text.startswith(('{', '[')):
        # 被 WAF 拦截时可能返回 JSONP/空内容，视为失败以触发回退
        raise ValueError('response is not JSON')
    return json.loads(text)


def fetch(url, timeout=15):
    """GET 并解析 JSON；urllib 失败或被拦截时回退到系统 curl。"""
    urllib_err = None
    try:
        return _parse_json(_urllib_get(url, timeout))
    except Exception as e:
        urllib_err = e
    try:
        return _parse_json(_curl_get(url, timeout))
    except Exception as e:
        raise RuntimeError('fetch failed: %s; curl fallback failed: %s' % (urllib_err, e))


# ---------- 格式化 ----------
def fmt_num(v, digits=2, divisor=1):
    if v is None or v in ('-', '', 0, '0'):
        return '-'
    try:
        f = float(v) / divisor
    except (ValueError, TypeError):
        return str(v)
    if digits == 0:
        return f'{int(f):,}'
    return f'{f:,.{digits}f}'


def display_width(s):
    w = 0
    for c in str(s):
        w += 2 if ord(c) > 127 else 1
    return w


def pad_left(s, width):
    s = str(s)
    pad = max(0, width - display_width(s))
    return ' ' * pad + s


def pad_right(s, width):
    s = str(s)
    pad = max(0, width - display_width(s))
    return s + ' ' * pad


def colorize(s, color, enabled):
    if not enabled:
        return s
    return color + s + C_RESET


def pct_color(v, enabled):
    try:
        f = float(v)
    except (ValueError, TypeError):
        return C_GRAY if enabled else ''
    if f > 0:
        return C_RED if enabled else ''
    if f < 0:
        return C_GREEN if enabled else ''
    return C_GRAY if enabled else ''


# ---------- 代码解析 ----------
def parse_code_item(item):
    """把 secid / 带前缀代码 / 6 位 A 股代码解析成 secid；无法解析返回 None。"""
    item = str(item).strip()
    if not item:
        return None
    if re.match(r'^\d+\.\d+$', item):
        return item
    lower = item.lower()
    for prefix, market in (('sh', '1'), ('sz', '0'), ('hk', '116'), ('us', '100')):
        if lower.startswith(prefix) and lower[len(prefix):].isdigit():
            return '%s.%s' % (market, item[len(prefix):])
    if re.match(r'^\d{6}$', item):
        if item[0] in ('0', '2', '3'):
            return '0.' + item
        if item[0] in ('6', '9'):
            return '1.' + item
    return None


# ---------- 缓存：name -> secid ----------
def load_cache():
    try:
        # utf-8-sig：兼容 Windows PowerShell 写出的带 BOM 缓存
        with open(CACHE_FILE, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_cache(cache):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def search_secid(name):
    """通过东方财富 suggest API 搜索名称对应的 secid。"""
    try:
        url = ('https://searchapi.eastmoney.com/api/suggest/get?input=%s&type=14&count=5'
               % urllib.parse.quote(name))
        data = fetch(url, timeout=10)
        items = (data.get('QuotationCodeTable') or {}).get('Data') or []
        item = None
        for it in items:
            if it.get('Name') == name:
                item = it
                break
        if item is None and items:
            item = items[0]
        if item:
            return item.get('QuoteID')
    except Exception:
        pass
    return None


def resolve_secids(names):
    """把名称/代码列表解析成 secid 列表（保持顺序，搜索不到跳过）。"""
    cache = load_cache()
    secids = []
    changed = False
    for name in names:
        key = str(name).strip()
        if not key:
            continue
        secid = parse_code_item(key)
        if secid is None:
            if key in cache:
                secid = cache[key]
            else:
                secid = search_secid(key)
                if secid:
                    cache[key] = secid
                    changed = True
        if secid:
            secids.append(secid)
        else:
            print('[warn] not found: %s' % key, file=sys.stderr)
    if changed:
        save_cache(cache)
    return secids


# ---------- 行情 ----------
QUOTE_HOSTS = ('push2.eastmoney.com', 'push2delay.eastmoney.com')


def fetch_quote_rows(secids):
    if not secids:
        return []
    fields = 'f12,f13,f14,f2,f3,f4,f5,f6,f8,f10,f15,f16,f17,f18'
    last_err = None
    for host in QUOTE_HOSTS:
        # push2 被限流时回退到延迟行情镜像 push2delay，接口结构相同
        url = ('https://%s/api/qt/ulist.np/get?fltt=2&invt=2&fields=%s&secids=%s'
               % (host, fields, ','.join(secids)))
        try:
            data = fetch(url, timeout=15)
            return (data.get('data') or {}).get('diff') or []
        except Exception as e:
            last_err = e
    raise last_err


def fetch_half_year_pct(secid):
    """计算最新价相对约半年前收盘价的涨跌幅。"""
    try:
        url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s'
               '&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13'
               '&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'
               '&klt=101&fqt=0&end=20500101&lmt=200' % secid)
        data = fetch(url, timeout=15)
        klines = (data.get('data') or {}).get('klines') or []
        if not klines:
            return None
        latest = klines[-1].split(',')
        latest_date = datetime.strptime(latest[0], '%Y-%m-%d')
        target_date = latest_date - timedelta(days=180)
        target_price = None
        for k in klines:
            parts = k.split(',')
            d = datetime.strptime(parts[0], '%Y-%m-%d')
            if d >= target_date:
                target_price = float(parts[2])
                break
        if not target_price:
            return None
        current_price = float(latest[2])
        return round((current_price - target_price) / target_price * 100, 2)
    except Exception:
        return None


def get_quotes():
    """读取自选股配置并获取行情，返回 (stock_rows, index_rows, error)。"""
    try:
        with open(WATCHLIST_FILE, 'r', encoding='utf-8-sig') as f:
            wl = json.load(f)
        stocks = wl.get('stocks') or []
        indices = wl.get('indices') or []
    except Exception as e:
        return [], [], 'read watchlist failed: %s' % e

    stock_secids = resolve_secids(stocks)
    index_secids = resolve_secids(indices)
    if not stock_secids and not index_secids:
        return [], [], 'no stocks or indices'

    # 合并一次请求，减少接口调用
    all_rows = fetch_quote_rows(stock_secids + index_secids)
    index_set = set(index_secids)
    stock_rows = []
    index_rows = []
    for r in all_rows:
        secid = '%s.%s' % (r.get('f13'), r.get('f12'))
        if secid in index_set:
            index_rows.append(r)
        else:
            stock_rows.append(r)
    return stock_rows, index_rows, None


def apply_half_year(stock_rows, hy_values):
    """把半年涨跌幅附加到行数据上；hy_values 为 secid->pct 缓存。"""
    for r in stock_rows:
        secid = '%s.%s' % (r.get('f13'), r.get('f12'))
        if secid not in hy_values:
            hy_values[secid] = fetch_half_year_pct(secid)
        r['hyPct'] = hy_values.get(secid)


# ---------- 显示 ----------
def open_price_with_arrow(open_val, prev_close_val):
    price = fmt_num(open_val)
    try:
        o = float(open_val)
        p = float(prev_close_val)
        if o > p:
            return price, '↑'
        if o < p:
            return price, '↓'
        return price, '-'
    except (ValueError, TypeError):
        return price, ' '


def print_stock_rows(rows, stealth, use_color):
    if stealth:
        header = (pad_left('Code', 8) + ' ' + pad_right('Name', 8) + ' ' + pad_left('Chg%', 9)
                  + ' ' + pad_left('Chg', 9) + ' ' + pad_left('Last', 8) + ' '
                  + pad_left('VolR', 8) + ' ' + pad_left('Turn%', 8))
        print(colorize(header, C_GRAY, use_color))
        print(colorize('-' * 64, C_GRAY, use_color))
        for r in rows:
            line = (pad_left(r.get('f12', ''), 8) + ' ' + pad_right(r.get('f14', ''), 8) + ' '
                    + pad_left(fmt_num(r.get('f3')) + '%', 9) + ' ' + pad_left(fmt_num(r.get('f4')), 9) + ' '
                    + pad_left(fmt_num(r.get('f2')), 8) + ' ' + pad_left(fmt_num(r.get('f10')), 8) + ' '
                    + pad_left(fmt_num(r.get('f8')), 8))
            print(colorize(line, C_GRAY, use_color))
        return

    header = (pad_left('代码', 8) + ' ' + pad_right('名称', 8) + ' ' + pad_left('涨跌幅', 9)
              + ' ' + pad_left('涨跌额', 9) + ' ' + pad_left('最新', 8) + ' ' + pad_left('昨收', 8)
              + ' ' + pad_left('今开', 9) + ' ' + pad_left('最高', 8) + ' ' + pad_left('最低', 8)
              + ' ' + pad_left('量比', 8) + ' ' + pad_left('换手%', 8) + ' '
              + pad_left('成交亿', 9) + ' ' + pad_left('半年涨跌', 10))
    print(header)
    print('-' * 122)
    for i, r in enumerate(rows):
        open_price, arrow = open_price_with_arrow(r.get('f17'), r.get('f18'))
        hy = fmt_num(r.get('hyPct'))
        line = (pad_left(r.get('f12', ''), 8) + ' ' + pad_right(r.get('f14', ''), 8) + ' '
                + pad_left(fmt_num(r.get('f3')) + '%', 9) + ' ' + pad_left(fmt_num(r.get('f4')), 9) + ' '
                + pad_left(fmt_num(r.get('f2')), 8) + ' ' + pad_left(fmt_num(r.get('f18')), 8) + ' '
                + pad_left(open_price, 8) + arrow + ' ' + pad_left(fmt_num(r.get('f15')), 8) + ' '
                + pad_left(fmt_num(r.get('f16')), 8) + ' ' + pad_left(fmt_num(r.get('f10')), 8) + ' '
                + pad_left(fmt_num(r.get('f8')), 8) + ' ' + pad_left(fmt_num(r.get('f6'), divisor=100000000), 9) + ' '
                + pad_left(('-' if hy == '-' else hy + '%'), 10))
        fg = pct_color(r.get('f3'), use_color)
        if use_color and i % 2 == 1:
            # 奇数行加深灰背景，形成交替斑马纹
            print(C_BG_DARK + fg + line + C_RESET)
        else:
            print(colorize(line, fg, use_color))


def print_index_rows(rows, stealth, use_color):
    if not rows:
        return
    table_width = 64 if stealth else 122
    print()
    print(colorize('-' * table_width, C_GRAY, use_color))

    if stealth:
        for r in rows:
            line = (pad_right(r.get('f14', ''), 8) + ' ' + pad_left(fmt_num(r.get('f2')), 10) + ' '
                    + pad_left('%s / %s%%' % (fmt_num(r.get('f4')), fmt_num(r.get('f3'))), 20))
            print(colorize(line, C_GRAY, use_color))
        return

    per_row = 5
    sep = ' | '
    boxes = []
    min_box_w = 0
    for r in rows:
        name = str(r.get('f14', ''))
        price = fmt_num(r.get('f2'))
        right2 = '%s / %s%%' % (fmt_num(r.get('f4')), fmt_num(r.get('f3')))
        boxes.append((name, price, right2, r.get('f3')))
        min_box_w = max(min_box_w, display_width(name + price), display_width(right2))

    box_w = (table_width - (per_row - 1) * display_width(sep)) // per_row
    box_w = max(box_w, min_box_w)

    for i in range(0, len(boxes), per_row):
        line1 = ''
        line2 = ''
        for j in range(per_row):
            if i + j >= len(boxes):
                break
            name, price, right2, pct = boxes[i + j]
            part1 = name + ' ' * max(0, box_w - display_width(name + price)) + price
            part2 = ' ' * max(0, box_w - display_width(right2)) + right2
            if j > 0:
                line1 += sep
                line2 += sep
            line1 += part1
            line2 += part2
        print(pad_right(line1, table_width))
        print(pad_right(line2, table_width))


def print_quotes(stock_rows, index_rows, show_index, stealth, use_color):
    now = time.strftime('%H:%M:%S')
    if stealth:
        print(colorize('System Monitor  |  Last update: %s' % now, C_GRAY, use_color))
    else:
        print('自选股行情 (%d 只)    刷新时间: %s' % (len(stock_rows), now))
    if stock_rows:
        print_stock_rows(stock_rows, stealth, use_color)
    if stealth:
        rows_to_show = [r for r in index_rows if r.get('f14') in ('上证指数', '深证成指')]
    elif show_index:
        rows_to_show = index_rows
    else:
        rows_to_show = []
    if rows_to_show:
        print_index_rows(rows_to_show, stealth, use_color)


def show_fake_screen():
    t = time.strftime('%H:%M:%S')
    project_dir = 'D:\\project' if IS_WINDOWS else '~/project'
    lines = [
        '> npm run build',
        '',
        '> project@1.0.0 build %s' % project_dir,
        '> tsc && vite build',
        '',
        'vite v5.0.0 building for production...',
        '✓ 128 modules transformed.',
        'dist/index.html                   0.45 kB',
        'dist/assets/index-a1b2c3d4.js   142.31 kB',
        '✓ built in 3.42s',
        '',
        '[%s] Watching for changes...' % t,
    ]
    clear_screen()
    for line in lines:
        print(colorize(line, C_DARKGRAY, USE_COLOR))
    sys.stdout.flush()


# ---------- 清屏 ----------
USE_COLOR = sys.stdout.isatty()
HAS_CONSOLE = sys.stdin.isatty() and sys.stdout.isatty()


def clear_screen():
    if HAS_CONSOLE:
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()
    elif IS_WINDOWS:
        os.system('cls')
    else:
        os.system('clear')


def redraw_frame():
    """回到原点并重绘一帧（有控制台时）。"""
    sys.stdout.write('\033[H\033[J')


# ---------- 帮助 ----------
def print_help():
    print('用法: watch_quotes.py [刷新秒数] [--index on|off] [--stealth on|off] [--hy on|off] [--once]')
    print('')
    print('参数:')
    print('  刷新秒数           自动刷新间隔，默认 15 秒')
    print('  --index on|off     是否显示指数方块，默认 off（办公模式会固定显示上证/深证）')
    print('  --stealth on|off   隐蔽模式（灰白文字、伪装窗口标题），默认 on')
    print('  --hy on|off        启动时获取半年涨跌，默认 off')
    print('  --once             只取一次数据后退出')
    print('  -h, --help         显示此帮助')
    print('')
    print('快捷键:')
    print('  Esc                退出')
    print('  B / F9             老板键：切换伪装 npm 构建日志 / 正常行情')
    print('  S                  切换办公模式（灰白隐蔽）/ 家庭模式（中文红绿）')
    print('')
    print('示例:')
    cmd = 'watch.cmd' if IS_WINDOWS else './watch.sh'
    print('  %s               隐蔽模式，15秒刷新（办公推荐）' % cmd)
    print('  %s 30            隐蔽模式，30秒刷新' % cmd)
    print('  %s --once        取一次数据后退出' % cmd)
    print('  %s --stealth off --index on' % cmd)
    print('                     恢复中文红绿 + 指数（在家用）')


def parse_args(argv):
    interval = 15
    show_index = False
    stealth = True
    fetch_hy = False
    once = False
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ('-h', '--help'):
            return None
        if arg in ('--index', '-index'):
            i += 1
            show_index = i < len(argv) and argv[i].lower() in ('on', 'true')
        elif arg in ('--stealth', '-stealth'):
            i += 1
            stealth = not (i < len(argv) and argv[i].lower() in ('off', 'false'))
        elif arg in ('--hy', '-hy'):
            i += 1
            fetch_hy = i < len(argv) and argv[i].lower() in ('on', 'true')
        elif arg in ('--once', '-once'):
            once = True
        else:
            try:
                parsed = int(arg)
                if parsed > 0:
                    interval = parsed
            except ValueError:
                pass
        i += 1
    return interval, show_index, stealth, fetch_hy, once


# ---------- 主流程 ----------
def main():
    enable_windows_ansi()

    args = parse_args(sys.argv)
    if args is None:
        print_help()
        return
    interval, show_index, stealth, fetch_hy, once = args

    term = UnixTerminal()
    if HAS_CONSOLE and not IS_WINDOWS:
        term.setup()
    if HAS_CONSOLE:
        if stealth:
            set_title('System')
        if not once:
            sys.stdout.write('\033[?25l')  # 隐藏光标
            sys.stdout.flush()

    hy_values = {}
    first = True
    boss_mode = False

    try:
        if once:
            try:
                stock_rows, index_rows, err = get_quotes()
            except Exception as e:
                print('[error] fetch failed: %s' % e)
                sys.exit(1)
            if err:
                print(err)
                sys.exit(1)
            if fetch_hy:
                apply_half_year(stock_rows, hy_values)
            print_quotes(stock_rows, index_rows, show_index, stealth, USE_COLOR)
            return

        while True:
            try:
                if first:
                    print('Initializing...')
                    sys.stdout.flush()
                stock_rows, index_rows, err = get_quotes()
                if first:
                    clear_screen()
                    first = False
                    if fetch_hy:
                        apply_half_year(stock_rows, hy_values)
                elif fetch_hy:
                    apply_half_year(stock_rows, hy_values)

                if boss_mode:
                    show_fake_screen()
                else:
                    if HAS_CONSOLE:
                        redraw_frame()
                    if err:
                        print(err)
                    else:
                        print_quotes(stock_rows, index_rows, show_index, stealth, USE_COLOR)
            except Exception as e:
                if first:
                    clear_screen()
                    first = False
                print('[error] fetch failed: %s' % e)

            if not boss_mode:
                print()
                if stealth:
                    print(colorize('Refresh: %ds  |  Esc exit  |  B hide  |  S mode'
                                   % interval, C_DARKGRAY, USE_COLOR))
                else:
                    print('每 %d 秒自动刷新，按 Esc 退出，按 B 伪装，按 S 切换模式...' % interval)
            sys.stdout.flush()

            key = wait_with_keys(interval, HAS_CONSOLE)
            if key == 'esc':
                break
            if key in ('b', 'f9'):
                boss_mode = not boss_mode
                if boss_mode:
                    show_fake_screen()
                else:
                    clear_screen()
            elif key == 's':
                stealth = not stealth
                show_index = not show_index
                if HAS_CONSOLE:
                    set_title('System' if stealth else '行情监视器')
                clear_screen()
    except KeyboardInterrupt:
        pass
    finally:
        term.restore()
        if HAS_CONSOLE:
            if not once:
                sys.stdout.write('\033[?25h')  # 恢复光标
                sys.stdout.flush()
                clear_screen()
            set_title('Command Prompt' if IS_WINDOWS else '')
        print('Exited')


if __name__ == '__main__':
    main()
