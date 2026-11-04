"""Captura uma janela Tk do processo pai, sem bloquear seu loop de eventos."""

import argparse
from pathlib import Path

from tests.windows_input import capture_window, windows_for_pid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int)
    parser.add_argument("hwnd", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.hwnd not in windows_for_pid(args.pid):
        raise RuntimeError("A captura deve pertencer ao processo de teste.")
    capture_window(args.hwnd, args.output)


if __name__ == "__main__":
    main()
