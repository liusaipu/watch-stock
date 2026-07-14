#!/usr/bin/env python3
"""定时刷新自选股行情。"""

import os
import sys
import time
import traceback

from quotes_core import enable_windows_ansi, get_quotes, print_quotes


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_help(script_name='watch_quotes.py'):
    print(f"用法: python {script_name} [刷新秒数] [--index on|off]")
    print("")
    print("参数:")
    print("  刷新秒数          自动刷新间隔，默认 3 秒")
    print("  --index on|off    是否显示指数方块，默认 on")
    print("  -h, --help        显示此帮助信息")


def parse_args(argv):
    interval = 3
    show_index = True
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ('--index', '-index'):
            i += 1
            if i < len(argv) and argv[i].lower() in ('on', 'true', '1'):
                show_index = True
            else:
                show_index = False
        elif arg in ('-h', '--help'):
            return None, None
        else:
            try:
                parsed = int(arg)
                if parsed > 0:
                    interval = parsed
            except ValueError:
                pass
        i += 1
    return interval, show_index


def main():
    enable_windows_ansi()

    args = parse_args(sys.argv)
    if args == (None, None):
        print_help()
        return
    interval, show_index = args

    hy_cache = {}
    hy_refresh_counter = 0
    last_stock_rows = []
    last_index_rows = []
    last_error = None

    clear_screen()
    while True:
        try:
            # 每 10 次刷新重新计算半年涨跌幅
            if hy_refresh_counter % 10 == 0:
                hy_cache.clear()
            stock_rows, index_rows, err = get_quotes(hy_values=hy_cache)
            hy_refresh_counter += 1
            clear_screen()
            if err:
                last_error = err
            else:
                last_stock_rows = stock_rows
                last_index_rows = index_rows
                last_error = None

            print_quotes(
                last_stock_rows,
                last_index_rows,
                show_index=show_index,
            )
            if last_error:
                print(f"\n[提示] {last_error}")
        except KeyboardInterrupt:
            clear_screen()
            print("已退出")
            break
        except Exception as e:
            clear_screen()
            print(f"[错误] 运行异常: {e}")
            traceback.print_exc()

        print(f"\n每 {interval} 秒自动刷新，按 Ctrl+C 退出...")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            clear_screen()
            print("已退出")
            break


if __name__ == '__main__':
    main()
