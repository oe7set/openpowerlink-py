"""``pl`` command-line interface for the bundled openPOWERLINK MN stack.

Subcommands::

    pl ifaces                                   list network interfaces
    pl run   --iface I --cdc C --xap X          start the stack, print live status
    pl read  --iface I --cdc C --xap X          one-shot DI/AI/DO/AO dump
    pl watch --iface I --cdc C --xap X          continuous DI/AI dump
    pl do    <ch> <0|1> --iface I --cdc C --xap X   pulse a digital output
    pl ao    <ch> --volts V --iface I ...           set an analog output

Most subcommands need a running stack, which requires raw-socket privileges
(root / CAP_NET_RAW on Linux, Npcap on Windows) and a POWERLINK-capable NIC.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time

from openpowerlink import _loader, _wrap


def _fmt_mac(mac) -> str:
    return ":".join(f"{b:02x}" for b in mac)


def cmd_ifaces(_args) -> int:
    try:
        lib = _wrap.bind(_loader.load())
    except _loader.NativeLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    count = ctypes.c_size_t(16)
    arr = (_wrap.PlwIface * 16)()
    rc = lib.plw_enum_ifaces(arr, ctypes.byref(count))
    if rc != 0:
        print(f"error: interface enumeration failed (oplk 0x{(-rc) & 0xFFFF:04X})",
              file=sys.stderr)
        return 1
    if count.value == 0:
        print("No POWERLINK-capable interfaces found.")
        return 0
    for i in range(count.value):
        iface = arr[i]
        name = iface.name.decode("utf-8", "replace")
        desc = iface.description.decode("utf-8", "replace")
        print(f"{name}\t{_fmt_mac(iface.mac)}\t{desc}")
    return 0


def _make_stack(args):
    from openpowerlink.stack import PowerlinkStack
    return PowerlinkStack(iface=args.iface, cdc=args.cdc, xap=args.xap,
                          node_id=args.node_id, cycle_us=args.cycle_us)


def _status_line(io) -> str:
    st = io.status()
    return (f"hb={st.heartbeat} cyc={st.cycle_count} "
            f"MN={'OP' if st.mn_operational else st.mn_nmt_state} "
            f"CN={'OP' if st.cn_operational else st.cn_nmt_state} "
            f"stack={'up' if st.stack_running else 'down'}")


def cmd_run(args) -> int:
    from openpowerlink.api import PowerlinkIO
    with _make_stack(args) as stack:
        io = PowerlinkIO(stack)
        print(f"openPOWERLINK {stack.version()} — {_status_line(io)}")
        print("Running. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(0.5)
                print(_status_line(io))
        except KeyboardInterrupt:
            print("\nStopping…")
    return 0


def cmd_read(args) -> int:
    from openpowerlink.api import PowerlinkIO
    with _make_stack(args) as stack:
        io = PowerlinkIO(stack)
        time.sleep(0.3)
        print("DI:", io.read_di())
        print("AI:", io.read_ai(), "=", [round(v, 3) for v in io.read_ai_volts()])
        print("DO:", io.read_do())
        print("AO:", io.read_ao())
        print(_status_line(io))
    return 0


def cmd_watch(args) -> int:
    from openpowerlink.api import PowerlinkIO
    with _make_stack(args) as stack:
        io = PowerlinkIO(stack)
        try:
            while True:
                di = "".join("1" if b else "0" for b in io.read_di())
                ai = [round(v, 2) for v in io.read_ai_volts()]
                print(f"\rDI={di} AI={ai} | {_status_line(io)}   ", end="")
                time.sleep(0.1)
        except KeyboardInterrupt:
            print()
    return 0


def cmd_do(args) -> int:
    from openpowerlink.api import PowerlinkIO
    with _make_stack(args) as stack:
        io = PowerlinkIO(stack)
        io.write_do(args.channel, bool(args.value))
        time.sleep(0.2)
        print(f"DO{args.channel} = {bool(args.value)} (readback {io.read_do()})")
    return 0


def cmd_ao(args) -> int:
    from openpowerlink.api import PowerlinkIO
    with _make_stack(args) as stack:
        io = PowerlinkIO(stack)
        if args.volts is not None:
            io.write_ao_volts(args.channel, args.volts)
        else:
            io.write_ao(args.channel, args.raw)
        time.sleep(0.2)
        print(f"AO{args.channel} readback: {io.read_ao()} "
              f"= {[round(v, 3) for v in io.read_ao_volts()]} V")
    return 0


def _add_stack_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--iface", required=True, help="network interface name")
    p.add_argument("--cdc", required=True, help="path to mnobd.cdc")
    p.add_argument("--xap", required=True, help="path to xap.xml")
    p.add_argument("--node-id", type=lambda s: int(s, 0), default=0xF0,
                   help="MN node id (default 0xF0)")
    p.add_argument("--cycle-us", type=int, default=5000,
                   help="cycle length hint in us (CDC 0x1006 is authoritative)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pl", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ifaces", help="list network interfaces")

    for name, fn, helptext in (
        ("run", cmd_run, "start the stack and print live status"),
        ("read", cmd_read, "one-shot DI/AI/DO/AO dump"),
        ("watch", cmd_watch, "continuous DI/AI dump"),
    ):
        p = sub.add_parser(name, help=helptext)
        _add_stack_args(p)
        p.set_defaults(func=fn)

    p_do = sub.add_parser("do", help="set a digital output")
    p_do.add_argument("channel", type=int)
    p_do.add_argument("value", type=int, choices=(0, 1))
    _add_stack_args(p_do)
    p_do.set_defaults(func=cmd_do)

    p_ao = sub.add_parser("ao", help="set an analog output")
    p_ao.add_argument("channel", type=int)
    g = p_ao.add_mutually_exclusive_group(required=True)
    g.add_argument("--volts", type=float)
    g.add_argument("--raw", type=int)
    _add_stack_args(p_ao)
    p_ao.set_defaults(func=cmd_ao)

    args = parser.parse_args(argv)
    if args.command == "ifaces":
        return cmd_ifaces(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
