#!/usr/bin/env python3
"""单次查询自选股行情。"""

import sys

from quotes_core import enable_windows_ansi, get_quotes, print_quotes


def print_help(script_name='get_watchlist_quotes.py'):
    print(f"用法: python {script_name} [--index on|off]")
    print("")
    print("参数:")
    print("  --index on|off    是否显示指数方块，默认 on")
    print("  -h, --help        显示此帮助信息")


def main():
    enable_windows_ansi()

    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()
        return

    show_index = True
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ('--index', '-index'):
            i += 1
            if i < len(sys.argv) and sys.argv[i].lower() in ('on', 'true', '1'):
                show_index = True
            else:
                show_index = False
        i += 1

    stock_rows, index_rows, err = get_quotes()
    if err:
        print(err)
        return

    print()
    print_quotes(stock_rows, index_rows, show_index=show_index)


if __name__ == '__main__':
    main()
