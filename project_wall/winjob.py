"""Windows Job Object helper.

Ties child process lifetime to the parent: when the parent (`wall serve`)
exits for any reason — clean shutdown, Task Manager kill, OS shutdown —
every process assigned to the job is terminated by the kernel.

Without this, hard-killing the launcher would orphan Streamlit/Vite/uvicorn
children, and the user would have to hunt them down manually.

No-op on non-Windows platforms; on those, child cleanup happens via the
explicit `ProcessManager.stop()` path.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class WindowsJob:
    def __init__(self) -> None:
        self._handle: int | None = None
        self._enabled = sys.platform == "win32"
        if self._enabled:
            try:
                self._handle = self._create()
            except OSError:
                # Allocation or info-set failed — fall back to best-effort
                # cleanup via ProcessManager.stop(). Never raise: the launcher
                # must still boot if job objects are unavailable.
                self._handle = None

    def assign(self, pid: int) -> bool:
        """Attach an existing process to the job. Returns False on any failure
        so callers can decide whether to log."""
        if not self._enabled or self._handle is None:
            return False
        kernel32 = ctypes.windll.kernel32
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        h_proc = kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid
        )
        if not h_proc:
            return False
        try:
            return bool(kernel32.AssignProcessToJobObject(self._handle, h_proc))
        finally:
            kernel32.CloseHandle(h_proc)

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            ctypes.windll.kernel32.CloseHandle(self._handle)
        finally:
            self._handle = None

    # --- internals ---

    @staticmethod
    def _create() -> int:
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_void_p),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL

        h = kernel32.CreateJobObjectW(None, None)
        if not h:
            raise ctypes.WinError()
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            h,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = ctypes.WinError()
            kernel32.CloseHandle(h)
            raise err
        return h
