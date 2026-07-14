"""自选股行情工具公共模块（Python）。"""

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta


# ---------- 常量 ----------
CACHE_VERSION = 1
CACHE_TTL_DAYS = 1
CACHE_FILE = '.watchlist_cache.json'

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
)

MARKET_MAP = {
    '0': '深A',
    '1': '沪A',
    '116': '港股',
    '100': '美股',
    '105': '新加坡',
    '107': '日本',
    '133': '英股',
}

# 列宽配置（按半角字符计，中文字符占 2）
COLS = {
    'code': 8,
    'name': 10,
    'market': 6,
    'price': 10,
    'high': 10,
    'low': 10,
    'change': 10,
    'pct': 10,
    'turnover': 8,
    'vr': 8,
    'vol': 14,
    'amount': 14,
    'hy': 10,
}

ANSI = {
    'red': '\033[31m',
    'green': '\033[32m',
    'white': '\033[37m',
    'reset': '\033[0m',
    'bold': '\033[1m',
}


def enable_windows_ansi():
    """在 Windows 10+ 的原生控制台中启用 ANSI 转义序列支持。"""
    if os.name != 'nt':
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        STD_OUTPUT_HANDLE = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


# ---------- 网络 ----------
def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.URLError as e:
        # macOS 等环境缺少证书时，降级到不验证证书重试一次
        if isinstance(e.reason, ssl.SSLError):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode('utf-8'))
        raise


# ---------- 格式化 ----------
def fmt_num(v, digits=2, divisor=1):
    if v is None or v == '-' or v == '':
        return '-'
    try:
        f = float(v) / divisor
    except (ValueError, TypeError):
        return str(v)
    if digits == 0:
        return f"{int(f):,}"
    return f"{f:,.{digits}f}"


def display_width(s):
    w = 0
    for c in str(s):
        w += 2 if ord(c) > 127 else 1
    return w


def pad_left(s, width):
    s = str(s)
    pad = width - display_width(s)
    if pad < 0:
        pad = 0
    return ' ' * pad + s


def pad_right(s, width):
    s = str(s)
    pad = width - display_width(s)
    if pad < 0:
        pad = 0
    return s + ' ' * pad


def pad_center(s, width):
    s = str(s)
    sw = display_width(s)
    left = (width - sw) // 2
    right = width - sw - left
    return ' ' * left + s + ' ' * right


def split_name(name):
    name = str(name)
    mid = (len(name) + 1) // 2
    return name[:mid], name[mid:]


# ---------- 颜色 ----------
def use_color(enabled=True):
    return enabled and sys.stdout.isatty()


def colorize(s, color, enabled=True):
    if not use_color(enabled):
        return s
    return f"{ANSI.get(color, ANSI['white'])}{s}{ANSI['reset']}"


def pct_color(pct):
    try:
        v = float(pct)
    except (ValueError, TypeError):
        return 'white'
    if v > 0:
        return 'red'
    if v < 0:
        return 'green'
    return 'white'


# ---------- 市场 / 代码解析 ----------
def market_name(market_code):
    return MARKET_MAP.get(str(market_code), f'市场{market_code}')


def parse_code_item(item):
    """把用户输入解析成 secid 元信息；无法解析时返回 None。"""
    item = str(item).strip()
    if not item:
        return None

    # 已是 secid 格式，如 0.300054、1.000001
    m = re.match(r'^(\d+)\.(\d+)$', item)
    if m:
        market, code = m.group(1), m.group(2)
        return {
            'secid': item,
            'code': code,
            'market': market_name(market),
            'name': code,
        }

    # 带市场前缀，如 sh600000、sz000001、hk00700
    prefix_map = {
        'sh': '1',
        'sz': '0',
        'hk': '116',
        'us': '100',
    }
    lower = item.lower()
    for prefix, market in prefix_map.items():
        if lower.startswith(prefix):
            code = item[len(prefix):]
            return {
                'secid': f'{market}.{code}',
                'code': code,
                'market': market_name(market),
                'name': code,
            }

    # 纯数字代码，按长度和首位粗略判断 A 股市场
    if re.match(r'^\d+$', item):
        code = item
        if len(code) == 6:
            first = code[0]
            if first in ('0', '2', '3'):
                market = '0'
            elif first in ('6', '9'):
                market = '1'
            else:
                return None
            return {
                'secid': f'{market}.{code}',
                'code': code,
                'market': market_name(market),
                'name': code,
            }

    return None


# ---------- 配置 ----------
def load_watchlist(path='watchlist.json'):
    with open(path, 'r', encoding='utf-8') as f:
        wl = json.load(f)
    stocks = wl.get('stocks', [])
    indices = wl.get('indices', [])
    if not isinstance(stocks, list):
        stocks = []
    if not isinstance(indices, list):
        indices = []
    return {'stocks': stocks, 'indices': indices, 'description': wl.get('description', '')}


# ---------- 缓存 ----------
def load_cache(cache_file=CACHE_FILE):
    if not os.path.exists(cache_file):
        return {'version': CACHE_VERSION, 'updated_at': '', 'items': {}}
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('version') != CACHE_VERSION:
            return {'version': CACHE_VERSION, 'updated_at': '', 'items': {}}
        return data
    except Exception:
        return {'version': CACHE_VERSION, 'updated_at': '', 'items': {}}


def save_cache(data, cache_file=CACHE_FILE):
    data['updated_at'] = datetime.now().isoformat()
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_cache_entry_stale(entry):
    updated = entry.get('updated_at', '')
    if not updated:
        return True
    try:
        updated_dt = datetime.fromisoformat(updated)
    except ValueError:
        return True
    return datetime.now() - updated_dt > timedelta(days=CACHE_TTL_DAYS)


# ---------- secid 解析 ----------
def search_secid(name):
    """通过东方财富 suggest API 搜索名称对应的 secid。"""
    try:
        url = (
            "https://searchapi.eastmoney.com/api/suggest/get?"
            f"input={urllib.parse.quote(name)}&type=14&count=5"
        )
        data = fetch(url, timeout=10)
        items = data.get('QuotationCodeTable', {}).get('Data', [])
        item = None
        for it in items:
            if it.get('Name') == name:
                item = it
                break
        if item is None and items:
            item = items[0]
        if item is None:
            return None
        secid = item.get('QuoteID')
        if not secid:
            return None
        market_code = str(item.get('MktNum', ''))
        return {
            'secid': secid,
            'code': item.get('Code', secid.split('.')[-1]),
            'market': market_name(market_code),
            'name': item.get('Name', name),
        }
    except Exception as e:
        print(f"[警告] 搜索 {name} 失败: {e}", file=sys.stderr)
        return None


def resolve_secids(names, cache_file=CACHE_FILE):
    """把名称/代码列表解析成以 secid 为键的字典。"""
    cache = load_cache(cache_file)
    items = cache.get('items', {})
    result = {}
    changed = False

    for name in names:
        key = str(name).strip()
        if not key:
            continue

        # 1. 命中缓存且未过期
        cached = items.get(key)
        if cached and not is_cache_entry_stale(cached):
            result[cached['secid']] = cached
            continue

        # 2. 尝试按代码解析
        parsed = parse_code_item(key)
        if parsed:
            result[parsed['secid']] = parsed
            items[key] = parsed
            changed = True
            continue

        # 3. 调用搜索 API
        found = search_secid(key)
        if found:
            result[found['secid']] = found
            items[key] = found
            changed = True
        else:
            print(f"[警告] 未找到 {key}", file=sys.stderr)

    if changed:
        cache['items'] = items
        save_cache(cache, cache_file)

    return result


# ---------- 行情 ----------
def fetch_quote_rows(secids):
    if not secids:
        return []
    fields = 'f12,f13,f14,f2,f3,f4,f5,f6,f8,f10,f15,f16,f17,f18'
    secid_str = ','.join(secids)
    quote_url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get?"
        f"fltt=2&invt=2&fields={fields}&secids={secid_str}"
    )
    qdata = fetch(quote_url, timeout=15)
    return qdata.get('data', {}).get('diff', []) or []


def fetch_kline_half_year(secid):
    """计算当前价相对约半年前收盘价的涨跌幅。"""
    try:
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            "&klt=101&fqt=0&end=20500101&lmt=200"
        )
        data = fetch(url, timeout=15)
        klines = data.get('data', {}).get('klines', [])
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
        if target_price is None or target_price == 0:
            return None
        current_price = float(latest[2])
        return round((current_price - target_price) / target_price * 100, 2)
    except Exception:
        return None


# ---------- 打印 ----------
def print_stocks(rows, use_color=True):
    header = (
        f"{pad_left('代码', COLS['code'])} "
        f"{pad_right('名称', COLS['name'])} "
        f"{pad_right('市场', COLS['market'])} "
        f"{pad_left('最新价', COLS['price'])} "
        f"{pad_left('最高价', COLS['high'])} "
        f"{pad_left('最低价', COLS['low'])} "
        f"{pad_left('涨跌额', COLS['change'])} "
        f"{pad_left('涨跌幅', COLS['pct'])} "
        f"{pad_left('换手率', COLS['turnover'])} "
        f"{pad_left('量比', COLS['vr'])} "
        f"{pad_left('成交量(手)', COLS['vol'])} "
        f"{pad_left('成交额(万)', COLS['amount'])} "
        f"{pad_left('半年涨跌', COLS['hy'])}"
    )
    print(colorize(header, 'bold', use_color))
    print('-' * display_width(header))

    for r in rows:
        meta = r.get('_meta', {})
        code = meta.get('code', r.get('f12', ''))
        name = meta.get('name', r.get('f14', ''))
        market = meta.get('market', market_name(r.get('f13', '')))
        price = fmt_num(r.get('f2'))
        high = fmt_num(r.get('f15'))
        low = fmt_num(r.get('f16'))
        change = fmt_num(r.get('f4'))
        pct = fmt_num(r.get('f3'))
        turnover = fmt_num(r.get('f8'))
        vr = fmt_num(r.get('f10'))
        vol = fmt_num(r.get('f5'), digits=0)
        amount = fmt_num(r.get('f6'), divisor=10000)
        hy = fmt_num(r.get('hyPct'))
        hy_str = f'{hy}%' if hy != '-' else '-'

        pct_val = r.get('f3')
        color = pct_color(pct_val)

        line = (
            f"{pad_left(code, COLS['code'])} "
            f"{pad_right(name, COLS['name'])} "
            f"{pad_right(market, COLS['market'])} "
            f"{pad_left(price, COLS['price'])} "
            f"{pad_left(high, COLS['high'])} "
            f"{pad_left(low, COLS['low'])} "
            f"{pad_left(change, COLS['change'])} "
            f"{pad_left(f'{pct}%', COLS['pct'])} "
            f"{pad_left(turnover, COLS['turnover'])} "
            f"{pad_left(vr, COLS['vr'])} "
            f"{pad_left(vol, COLS['vol'])} "
            f"{pad_left(amount, COLS['amount'])} "
            f"{pad_left(hy_str, COLS['hy'])}"
        )
        print(colorize(line, color, use_color))


def print_indices(rows, use_color=True):
    if not rows:
        return
    print()
    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        term_width = 120

    per_row = 4
    gap = 2
    min_box_width = 24
    padding = 1
    boxes = []
    max_left = 0
    max_right = 0

    for r in rows:
        name_top, name_bottom = split_name(r.get('f14', ''))
        price = fmt_num(r.get('f2'))
        change = fmt_num(r.get('f4'))
        pct = fmt_num(r.get('f3'))
        right1 = price
        right2 = f"{change} / {pct}%"
        max_left = max(max_left, display_width(name_top), display_width(name_bottom))
        max_right = max(max_right, display_width(right1), display_width(right2))
        boxes.append((name_top, name_bottom, right1, right2, pct_color(r.get('f3'))))

    box_width = max(min_box_width, max_left + gap + max_right + 2 * padding)
    per_row = max(1, term_width // (box_width + 2))

    for i in range(0, len(boxes), per_row):
        for line_idx in range(4):
            parts = []
            for j in range(per_row):
                if i + j >= len(boxes):
                    break
                name_top, name_bottom, right1, right2, color = boxes[i + j]
                if line_idx == 0:
                    part = '┌' + '─' * box_width + '┐'
                elif line_idx == 1:
                    part = ('│' + ' ' * padding + pad_right(name_top, max_left)
                            + ' ' * gap + pad_left(right1, max_right) + ' ' * padding + '│')
                elif line_idx == 2:
                    part = ('│' + ' ' * padding + pad_right(name_bottom, max_left)
                            + ' ' * gap + pad_left(right2, max_right) + ' ' * padding + '│')
                else:
                    part = '└' + '─' * box_width + '┘'
                parts.append(colorize(part, color, use_color))
            print('  '.join(parts))


# ---------- 主入口 ----------
def get_quotes(watchlist_path='watchlist.json', cache_file=CACHE_FILE, hy_values=None):
    """
    获取行情数据。
    :param hy_values: 用于缓存半年涨跌幅的字典，会被原地更新；若为 None 则每次都计算。
    :return: (stock_rows, index_rows, error_message)
    """
    try:
        wl = load_watchlist(watchlist_path)
    except Exception as e:
        return [], [], f'[错误] 读取配置失败: {e}'

    try:
        stock_meta = resolve_secids(wl['stocks'], cache_file)
        index_meta = resolve_secids(wl['indices'], cache_file)
    except Exception as e:
        return [], [], f'[错误] 解析股票代码失败: {e}'

    if not stock_meta and not index_meta:
        return [], [], '没有可查询的股票或指数'

    stock_secids = list(stock_meta.keys())
    index_secids = list(index_meta.keys())

    try:
        stock_rows = fetch_quote_rows(stock_secids)
        index_rows = fetch_quote_rows(index_secids)
    except Exception as e:
        return [], [], f'[错误] 获取行情失败: {e}'

    for r in stock_rows:
        secid = f"{r.get('f13', '')}.{r.get('f12', '')}"
        r['_meta'] = stock_meta.get(secid, {})
        if hy_values is not None:
            if secid not in hy_values:
                hy_values[secid] = fetch_kline_half_year(secid)
            r['hyPct'] = hy_values.get(secid)
        else:
            r['hyPct'] = fetch_kline_half_year(secid)

    for r in index_rows:
        secid = f"{r.get('f13', '')}.{r.get('f12', '')}"
        r['_meta'] = index_meta.get(secid, {})

    return stock_rows, index_rows, None


def print_quotes(stock_rows, index_rows, show_index=True, use_color=True):
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"自选股行情 ({len(stock_rows)} 只)    刷新时间: {now}")
    if stock_rows:
        print_stocks(stock_rows, use_color=use_color)
    if show_index and index_rows:
        print_indices(index_rows, use_color=use_color)
