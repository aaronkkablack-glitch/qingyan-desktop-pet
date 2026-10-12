"""Windows本地资源采样；不操作窗口、不发送聊天请求。"""
import argparse
import ctypes
from ctypes import wintypes
import json
import time

class Memory(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ("peak_working", "working", "peak_paged", "paged",
        "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private")]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("pid",type=int)
    ap.add_argument("--seconds",type=int,default=30)
    args=ap.parse_args()
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.GetProcessHandleCount.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    psapi=ctypes.WinDLL("psapi",use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD]
    handle=kernel.OpenProcess(0x410,False,args.pid)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    samples=[]
    previous_cpu = None
    previous_time = time.monotonic()
    try:
        for _ in range(max(1,args.seconds)):
            mem=Memory(); mem.cb=ctypes.sizeof(mem)
            count=wintypes.DWORD()
            if not psapi.GetProcessMemoryInfo(handle,ctypes.byref(mem),mem.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            kernel.GetProcessHandleCount(handle,ctypes.byref(count))
            times = [wintypes.FILETIME() for _ in range(4)]
            kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))
            cpu = sum((t.dwHighDateTime << 32) + t.dwLowDateTime for t in times[2:]) / 10000000
            now = time.monotonic()
            cpu_pct = None if previous_cpu is None else round(100*(cpu-previous_cpu)/(now-previous_time),2)
            samples.append({"working_mb":round(mem.working/1048576,2),
                            "private_mb":round(mem.private/1048576,2),"handles":count.value,
                            "cpu_percent_one_core":cpu_pct})
            previous_cpu, previous_time = cpu, now
            time.sleep(1)
        print(json.dumps({"pid":args.pid,"samples":samples,"scope":"idle local process; not a soak test"}))
    finally: kernel.CloseHandle(handle)

if __name__ == "__main__": main()
