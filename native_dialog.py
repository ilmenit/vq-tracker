"""POKEY VQ Tracker - Native File Dialogs

Cross-platform native file/folder selection using OS dialogs.

Backend priority:
  1. Win32 ctypes (Windows only) - comdlg32.dll / shell32.dll
     The actual Windows file dialog API. Zero dependencies, instant, 100% reliable.
  2. tkinter.filedialog  - Python standard library (when bundled)
  3. OS subprocess        - osascript (Mac), zenity/kdialog (Linux), PowerShell (Win fallback)

All backends produce truly native OS dialogs.
"""
import logging
import os
import platform
import subprocess
from typing import List, Optional

logger = logging.getLogger("tracker.native_dialog")

_SYSTEM = platform.system()


# =========================================================================
# BACKEND 1 (Windows): ctypes Win32 API - comdlg32.dll / shell32.dll
# =========================================================================
# This calls the same native Windows dialogs that Explorer uses.
# comdlg32.dll is a core Windows system DLL, always present.

_win32_available = None


def _check_win32() -> bool:
    """Check if Win32 ctypes API is available (Windows only)."""
    global _win32_available
    if _win32_available is not None:
        return _win32_available
    if _SYSTEM != "Windows":
        _win32_available = False
        return False
    try:
        import ctypes
        import ctypes.wintypes
        # Verify the DLLs load
        ctypes.windll.comdlg32
        ctypes.windll.shell32
        ctypes.windll.ole32
        _win32_available = True
    except Exception:
        _win32_available = False
    return _win32_available


def _build_win32_filter(filters: Optional[dict]) -> str:
    """Convert filter dict to Win32 OPENFILENAME filter string.

    Win32 format: pairs of (description, pattern) separated by null chars,
    terminated by double null. Example: "Audio\\0*.wav;*.mp3\\0All\\0*.*\\0\\0"
    """
    parts = []
    if filters:
        for name, spec in filters.items():
            exts = ";".join(f"*.{e.strip()}" for e in spec.split(","))
            parts.append(f"{name} ({exts})")
            parts.append(exts)
    parts.append("All Files (*.*)")
    parts.append("*.*")
    # Join with null chars, add trailing double null
    return "\0".join(parts) + "\0\0"


def _win32_open_files(title: Optional[str], start_dir: Optional[str],
                      filters: Optional[dict], allow_multi: bool) -> List[str]:
    """Open file dialog using Win32 GetOpenFileNameW (comdlg32.dll)."""
    import ctypes
    import ctypes.wintypes

    # OPENFILENAMEW structure
    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize",       ctypes.wintypes.DWORD),
            ("hwndOwner",         ctypes.wintypes.HWND),
            ("hInstance",         ctypes.wintypes.HINSTANCE),
            ("lpstrFilter",       ctypes.wintypes.LPCWSTR),
            ("lpstrCustomFilter", ctypes.wintypes.LPWSTR),
            ("nMaxCustFilter",    ctypes.wintypes.DWORD),
            ("nFilterIndex",      ctypes.wintypes.DWORD),
            ("lpstrFile",         ctypes.wintypes.LPWSTR),
            ("nMaxFile",          ctypes.wintypes.DWORD),
            ("lpstrFileTitle",    ctypes.wintypes.LPWSTR),
            ("nMaxFileTitle",     ctypes.wintypes.DWORD),
            ("lpstrInitialDir",   ctypes.wintypes.LPCWSTR),
            ("lpstrTitle",        ctypes.wintypes.LPCWSTR),
            ("Flags",             ctypes.wintypes.DWORD),
            ("nFileOffset",       ctypes.wintypes.WORD),
            ("nFileExtension",    ctypes.wintypes.WORD),
            ("lpstrDefExt",       ctypes.wintypes.LPCWSTR),
            ("lCustData",         ctypes.wintypes.LPARAM),
            ("lpfnHook",          ctypes.c_void_p),
            ("lpTemplateName",    ctypes.wintypes.LPCWSTR),
            ("pvReserved",        ctypes.c_void_p),
            ("dwReserved",        ctypes.wintypes.DWORD),
            ("FlagsEx",           ctypes.wintypes.DWORD),
        ]

    OFN_ALLOWMULTISELECT = 0x00000200
    OFN_EXPLORER         = 0x00080000
    OFN_FILEMUSTEXIST    = 0x00001000
    OFN_PATHMUSTEXIST    = 0x00000800
    OFN_NOCHANGEDIR      = 0x00000008

    # Large buffer for multi-select (null-separated paths)
    buf_size = 65536
    buf = ctypes.create_unicode_buffer(buf_size)

    flags = OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR
    if allow_multi:
        flags |= OFN_ALLOWMULTISELECT

    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = None
    ofn.lpstrFilter = _build_win32_filter(filters)
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buf, ctypes.wintypes.LPWSTR)
    ofn.nMaxFile = buf_size
    ofn.lpstrTitle = title or "Select Files"
    ofn.Flags = flags
    if start_dir and os.path.isdir(start_dir):
        ofn.lpstrInitialDir = start_dir

    result = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn))
    if not result:
        return []

    # Parse the buffer
    # Single file: "C:\path\to\file.wav\0"
    # Multi-select: "C:\dir\0file1.wav\0file2.wav\0\0"
    raw = buf[:]
    # Find the double-null terminator
    parts = []
    current = ""
    i = 0
    while i < buf_size:
        ch = raw[i]
        if ch == "\0":
            if current:
                parts.append(current)
                current = ""
            else:
                break  # Double null = end
        else:
            current += ch
        i += 1

    if not parts:
        return []

    if len(parts) == 1:
        # Single file selected (full path)
        return [parts[0]] if os.path.exists(parts[0]) else []
    else:
        # Multi-select: first part is directory, rest are filenames
        directory = parts[0]
        return [os.path.join(directory, f) for f in parts[1:] if f]


def _win32_save_file(title: Optional[str], start_dir: Optional[str],
                     filters: Optional[dict], default_name: Optional[str]) -> Optional[str]:
    """Save file dialog using Win32 GetSaveFileNameW (comdlg32.dll)."""
    import ctypes
    import ctypes.wintypes

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize",       ctypes.wintypes.DWORD),
            ("hwndOwner",         ctypes.wintypes.HWND),
            ("hInstance",         ctypes.wintypes.HINSTANCE),
            ("lpstrFilter",       ctypes.wintypes.LPCWSTR),
            ("lpstrCustomFilter", ctypes.wintypes.LPWSTR),
            ("nMaxCustFilter",    ctypes.wintypes.DWORD),
            ("nFilterIndex",      ctypes.wintypes.DWORD),
            ("lpstrFile",         ctypes.wintypes.LPWSTR),
            ("nMaxFile",          ctypes.wintypes.DWORD),
            ("lpstrFileTitle",    ctypes.wintypes.LPWSTR),
            ("nMaxFileTitle",     ctypes.wintypes.DWORD),
            ("lpstrInitialDir",   ctypes.wintypes.LPCWSTR),
            ("lpstrTitle",        ctypes.wintypes.LPCWSTR),
            ("Flags",             ctypes.wintypes.DWORD),
            ("nFileOffset",       ctypes.wintypes.WORD),
            ("nFileExtension",    ctypes.wintypes.WORD),
            ("lpstrDefExt",       ctypes.wintypes.LPCWSTR),
            ("lCustData",         ctypes.wintypes.LPARAM),
            ("lpfnHook",          ctypes.c_void_p),
            ("lpTemplateName",    ctypes.wintypes.LPCWSTR),
            ("pvReserved",        ctypes.c_void_p),
            ("dwReserved",        ctypes.wintypes.DWORD),
            ("FlagsEx",           ctypes.wintypes.DWORD),
        ]

    OFN_EXPLORER       = 0x00080000
    OFN_OVERWRITEPROMPT = 0x00000002
    OFN_PATHMUSTEXIST  = 0x00000800
    OFN_NOCHANGEDIR    = 0x00000008

    buf_size = 4096
    buf = ctypes.create_unicode_buffer(default_name or "", buf_size)

    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = None
    ofn.lpstrFilter = _build_win32_filter(filters)
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buf, ctypes.wintypes.LPWSTR)
    ofn.nMaxFile = buf_size
    ofn.lpstrTitle = title or "Save File"
    ofn.Flags = OFN_EXPLORER | OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR
    if start_dir and os.path.isdir(start_dir):
        ofn.lpstrInitialDir = start_dir

    # Set default extension from first filter
    if filters:
        first_spec = list(filters.values())[0]
        first_ext = first_spec.split(",")[0].strip().lstrip(".")
        ofn.lpstrDefExt = first_ext

    result = ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(ofn))
    if not result:
        return None

    path = buf.value
    return path if path else None


def _win32_pick_folder(title: Optional[str], start_dir: Optional[str]) -> Optional[str]:
    """Pick folder using modern IFileOpenDialog COM interface (Vista+).

    Shows the full Explorer-style dialog with breadcrumb bar, favorites,
    search, etc. Falls back to SHBrowseForFolderW on pre-Vista (XP).
    
    IMPORTANT: Only falls back to legacy if the modern dialog could not be
    created at all (e.g., COM init failure on XP). If the modern dialog was
    shown and the user cancelled or any cleanup error occurred, we return
    None immediately — never showing a second dialog.
    """
    try:
        return _win32_pick_folder_modern(title, start_dir)
    except _DialogShownError:
        # Dialog was shown but errored during cleanup — user already interacted
        logger.debug("IFileOpenDialog cleanup error after dialog was shown")
        return None
    except Exception as e:
        # Dialog couldn't be created — safe to try legacy
        logger.debug(f"IFileOpenDialog failed ({e}), trying SHBrowseForFolder")
        return _win32_pick_folder_legacy(title, start_dir)


class _DialogShownError(Exception):
    """Raised when a dialog was shown but failed during result/cleanup."""
    pass


def _win32_pick_folder_modern(title: Optional[str], start_dir: Optional[str]) -> Optional[str]:
    """Pick folder via IFileOpenDialog (Vista+ modern Explorer dialog)."""
    import ctypes
    import ctypes.wintypes

    # COM GUIDs
    CLSID_FileOpenDialog = _GUID('{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}')
    IID_IFileOpenDialog  = _GUID('{D57C7288-D4AD-4768-BE02-9D969532D960}')
    IID_IShellItem       = _GUID('{43826D1E-E718-42EE-BC55-A1E261C37BFE}')

    # IFileDialog options
    FOS_PICKFOLDERS      = 0x00000020
    FOS_FORCEFILESYSTEM  = 0x00000040
    FOS_NOCHANGEDIR      = 0x00000008

    # SIGDN for GetDisplayName
    SIGDN_FILESYSPATH = 0x80058000

    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    # Initialize COM
    ole32.CoInitialize(None)

    # Create IFileOpenDialog instance
    pDialog = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(CLSID_FileOpenDialog),
        None,
        1,  # CLSCTX_INPROC_SERVER
        ctypes.byref(IID_IFileOpenDialog),
        ctypes.byref(pDialog),
    )
    if hr != 0:
        raise OSError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08X}")

    # Get the vtable - IFileOpenDialog inherits:
    # IUnknown (0,1,2) -> IModalWindow (3) -> IFileDialog (4..26) -> IFileOpenDialog(27..)
    vtable = ctypes.cast(
        ctypes.cast(pDialog, ctypes.POINTER(ctypes.c_void_p))[0],
        ctypes.POINTER(ctypes.c_void_p * 28),
    ).contents

    try:
        # SetOptions: vtable index 9
        # HRESULT SetOptions(FILEOPENDIALOGOPTIONS)
        SetOptions = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.c_uint
        )(vtable[9])

        # GetOptions: vtable index 10
        GetOptions = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)
        )(vtable[10])

        opts = ctypes.c_uint()
        GetOptions(pDialog, ctypes.byref(opts))
        SetOptions(pDialog, opts.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_NOCHANGEDIR)

        # SetTitle: vtable index 17
        SetTitle = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.wintypes.LPCWSTR
        )(vtable[17])
        if title:
            SetTitle(pDialog, title)

        # Set initial folder if provided: SetFolder vtable index 12
        if start_dir and os.path.isdir(start_dir):
            pFolder = ctypes.c_void_p()
            hr = shell32.SHCreateItemFromParsingName(
                ctypes.wintypes.LPCWSTR(start_dir),
                None,
                ctypes.byref(IID_IShellItem),
                ctypes.byref(pFolder),
            )
            if hr == 0 and pFolder:
                SetFolder = ctypes.WINFUNCTYPE(
                    ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p
                )(vtable[12])
                SetFolder(pDialog, pFolder)
                # Release IShellItem
                _com_release(pFolder)

        # Show: vtable index 3 (IModalWindow::Show)
        Show = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.wintypes.HWND
        )(vtable[3])
        hr = Show(pDialog, None)

        # After Show() returns, the dialog has been displayed to the user.
        # Any errors from here on are cleanup/result errors — we must NOT
        # fall back to a legacy dialog (the user already saw one).
        try:
            if hr != 0:
                # User cancelled or error
                return None

            # GetResult: vtable index 20
            GetResult = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
            )(vtable[20])
            pItem = ctypes.c_void_p()
            hr = GetResult(pDialog, ctypes.byref(pItem))
            if hr != 0 or not pItem:
                return None

            try:
                # Get path from IShellItem::GetDisplayName (vtable index 5)
                item_vtable = ctypes.cast(
                    ctypes.cast(pItem, ctypes.POINTER(ctypes.c_void_p))[0],
                    ctypes.POINTER(ctypes.c_void_p * 6),
                ).contents

                GetDisplayName = ctypes.WINFUNCTYPE(
                    ctypes.HRESULT, ctypes.c_void_p, ctypes.c_uint,
                    ctypes.POINTER(ctypes.wintypes.LPWSTR)
                )(item_vtable[5])

                path_ptr = ctypes.wintypes.LPWSTR()
                hr = GetDisplayName(pItem, SIGDN_FILESYSPATH, ctypes.byref(path_ptr))
                if hr == 0 and path_ptr:
                    path = path_ptr.value
                    ole32.CoTaskMemFree(path_ptr)
                    return path
            finally:
                _com_release(pItem)
        except Exception as e:
            raise _DialogShownError(str(e)) from e

    finally:
        try:
            _com_release(pDialog)
        except Exception:
            pass  # Don't let cleanup errors mask the real result

    return None


def _GUID(guid_string: str):
    """Create a ctypes GUID structure from a string like '{...}'."""
    import ctypes
    import ctypes.wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    guid = GUID()
    ctypes.windll.ole32.CLSIDFromString(
        ctypes.wintypes.LPCWSTR(guid_string),
        ctypes.byref(guid),
    )
    return guid


def _com_release(ptr):
    """Call IUnknown::Release on a COM pointer (vtable index 2)."""
    import ctypes
    if ptr:
        vtable = ctypes.cast(
            ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p * 3),
        ).contents
        Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        Release(ptr)


def _win32_pick_folder_legacy(title: Optional[str], start_dir: Optional[str]) -> Optional[str]:
    """Pick folder using legacy SHBrowseForFolderW (pre-Vista fallback)."""
    import ctypes
    import ctypes.wintypes

    BIF_RETURNONLYFSDIRS = 0x00000001
    BIF_NEWDIALOGSTYLE   = 0x00000040
    BIF_EDITBOX          = 0x00000010

    BFFCALLBACK = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.wintypes.HWND,
        ctypes.c_uint,
        ctypes.wintypes.LPARAM,
        ctypes.wintypes.LPARAM,
    )

    BFFM_INITIALIZED = 1
    BFFM_SETSELECTIONW = 0x0467

    init_path = start_dir if start_dir and os.path.isdir(start_dir) else None

    @BFFCALLBACK
    def _browse_callback(hwnd, msg, lp, data):
        if msg == BFFM_INITIALIZED and init_path:
            ctypes.windll.user32.SendMessageW(
                hwnd, BFFM_SETSELECTIONW, True,
                ctypes.wintypes.LPCWSTR(init_path))
        return 0

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [
            ("hwndOwner",      ctypes.wintypes.HWND),
            ("pidlRoot",       ctypes.c_void_p),
            ("pszDisplayName", ctypes.wintypes.LPWSTR),
            ("lpszTitle",      ctypes.wintypes.LPCWSTR),
            ("ulFlags",        ctypes.c_uint),
            ("lpfn",           BFFCALLBACK),
            ("lParam",         ctypes.wintypes.LPARAM),
            ("iImage",         ctypes.c_int),
        ]

    ctypes.windll.ole32.CoInitialize(None)

    display_buf = ctypes.create_unicode_buffer(260)

    bi = BROWSEINFOW()
    bi.hwndOwner = None
    bi.pszDisplayName = ctypes.cast(display_buf, ctypes.wintypes.LPWSTR)
    bi.lpszTitle = title or "Select Folder"
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX
    bi.lpfn = _browse_callback
    bi.lParam = 0

    pidl = ctypes.windll.shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return None

    path_buf = ctypes.create_unicode_buffer(260)
    result = ctypes.windll.shell32.SHGetPathFromIDListW(pidl, path_buf)

    ctypes.windll.ole32.CoTaskMemFree(pidl)

    if result and path_buf.value:
        return path_buf.value
    return None


# =========================================================================
# BACKEND 2: tkinter.filedialog (standard library)
# =========================================================================

_tk_available = None


def _check_tk() -> bool:
    """Check if tkinter is usable (not always available in frozen apps)."""
    global _tk_available
    if _tk_available is not None:
        return _tk_available
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
        _tk_available = True
    except Exception:
        _tk_available = False
    return _tk_available


def _tk_open_files(title: Optional[str], start_dir: Optional[str],
                   filters: Optional[dict], allow_multi: bool) -> List[str]:
    """Open file dialog via tkinter (native OS dialog)."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.focus_force()

    filetypes = []
    if filters:
        for name, spec in filters.items():
            exts = " ".join(f"*.{e.strip()}" for e in spec.split(","))
            filetypes.append((name, exts))
        filetypes.append(("All files", "*.*"))

    kwargs = {}
    if title:
        kwargs["title"] = title
    if start_dir and os.path.isdir(start_dir):
        kwargs["initialdir"] = start_dir
    if filetypes:
        kwargs["filetypes"] = filetypes

    if allow_multi:
        result = filedialog.askopenfilenames(**kwargs)
        paths = list(result) if result else []
    else:
        result = filedialog.askopenfilename(**kwargs)
        paths = [result] if result else []

    root.destroy()
    return [p for p in paths if p]


def _tk_pick_folder(title: Optional[str], start_dir: Optional[str]) -> Optional[str]:
    """Pick folder via tkinter (native OS dialog)."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.focus_force()

    kwargs = {}
    if title:
        kwargs["title"] = title
    if start_dir and os.path.isdir(start_dir):
        kwargs["initialdir"] = start_dir

    result = filedialog.askdirectory(**kwargs)
    root.destroy()
    return result if result else None


def _tk_save_file(title: Optional[str], start_dir: Optional[str],
                  filters: Optional[dict], default_name: Optional[str]) -> Optional[str]:
    """Save file dialog via tkinter."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.focus_force()

    filetypes = []
    if filters:
        for name, spec in filters.items():
            exts = " ".join(f"*.{e.strip()}" for e in spec.split(","))
            filetypes.append((name, exts))
        filetypes.append(("All files", "*.*"))

    kwargs = {}
    if title:
        kwargs["title"] = title
    if start_dir and os.path.isdir(start_dir):
        kwargs["initialdir"] = start_dir
    if filetypes:
        kwargs["filetypes"] = filetypes
    if default_name:
        kwargs["initialfile"] = default_name

    result = filedialog.asksaveasfilename(**kwargs)
    root.destroy()
    return result if result else None


# =========================================================================
# BACKEND 3: OS subprocess (Mac: osascript, Linux: zenity/kdialog)
# =========================================================================

# --- macOS: osascript ---

def _osa_escape(s: str) -> str:
    """Escape a string for AppleScript double-quoted strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _mac_open_files(title: Optional[str], start_dir: Optional[str],
                    filters: Optional[dict], allow_multi: bool) -> List[str]:
    """Open file dialog via osascript (macOS)."""
    type_clause = ""
    if filters:
        exts = []
        for spec in filters.values():
            exts.extend(e.strip() for e in spec.split(","))
        type_list = ", ".join(f'"{e}"' for e in exts)
        type_clause = f" of type {{{type_list}}}"

    multi_clause = " with multiple selections allowed" if allow_multi else ""
    prompt = _osa_escape(title or "Select Files")
    default_loc = ""
    if start_dir and os.path.isdir(start_dir):
        default_loc = f' default location POSIX file "{_osa_escape(start_dir)}"'

    script = (
        f'set theFiles to choose file with prompt "{prompt}"'
        f'{default_loc}{type_clause}{multi_clause}\n'
    )
    if allow_multi:
        script += (
            'set output to ""\n'
            'repeat with f in theFiles\n'
            '  set output to output & POSIX path of f & linefeed\n'
            'end repeat\n'
            'return output\n'
        )
    else:
        script += 'return POSIX path of theFiles\n'

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [p for p in result.stdout.strip().split("\n") if p and os.path.exists(p)]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"osascript failed: {e}")
    return []


def _mac_pick_folder(title: Optional[str], start_dir: Optional[str]) -> Optional[str]:
    """Pick folder via osascript (macOS)."""
    prompt = _osa_escape(title or "Select Folder")
    default_loc = ""
    if start_dir and os.path.isdir(start_dir):
        default_loc = f' default location POSIX file "{_osa_escape(start_dir)}"'

    script = (
        f'set theFolder to choose folder with prompt "{prompt}"{default_loc}\n'
        'return POSIX path of theFolder\n'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and result.stdout.strip():
            path = result.stdout.strip()
            return path if os.path.isdir(path) else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"osascript failed: {e}")
    return None


def _mac_save_file(title: Optional[str], start_dir: Optional[str],
                   filters: Optional[dict], default_name: Optional[str]) -> Optional[str]:
    """Save file dialog via osascript (macOS)."""
    prompt = _osa_escape(title or "Save File")
    default_loc = ""
    if start_dir and os.path.isdir(start_dir):
        default_loc = f' default location POSIX file "{_osa_escape(start_dir)}"'
    default_file = ""
    if default_name:
        default_file = f' default name "{_osa_escape(default_name)}"'

    script = (
        f'set theFile to choose file name with prompt "{prompt}"{default_loc}{default_file}\n'
        'return POSIX path of theFile\n'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"osascript failed: {e}")
    return None


# --- Linux: zenity / kdialog ---

_linux_tool = None
_linux_tool_checked = False


def _find_linux_dialog() -> Optional[str]:
    """Find available Linux dialog tool (cached)."""
    global _linux_tool, _linux_tool_checked
    if _linux_tool_checked:
        return _linux_tool
    _linux_tool_checked = True
    for tool in ("zenity", "kdialog", "yad"):
        try:
            subprocess.run([tool, "--version"], capture_output=True, timeout=5)
            _linux_tool = tool
            return _linux_tool
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None


def _linux_open_files(title: Optional[str], start_dir: Optional[str],
                      filters: Optional[dict], allow_multi: bool) -> List[str]:
    """Open file dialog via zenity/kdialog (Linux)."""
    tool = _find_linux_dialog()
    if not tool:
        return []

    if tool == "zenity":
        cmd = ["zenity", "--file-selection", "--title", title or "Select Files"]
        if allow_multi:
            cmd.append("--multiple")
            cmd.extend(["--separator", "|"])
        if filters:
            for name, spec in filters.items():
                exts = " ".join(f"*.{e.strip()}" for e in spec.split(","))
                cmd.extend(["--file-filter", f"{name} | {exts}"])
            cmd.extend(["--file-filter", "All Files | *"])
        if start_dir and os.path.isdir(start_dir):
            cmd.extend(["--filename", start_dir + "/"])
    elif tool == "kdialog":
        if allow_multi:
            cmd = ["kdialog", "--getopenfilename", start_dir or ".", "--multiple"]
        else:
            cmd = ["kdialog", "--getopenfilename", start_dir or "."]
        if filters:
            specs = []
            for name, spec in filters.items():
                exts = " ".join(f"*.{e.strip()}" for e in spec.split(","))
                specs.append(f"{exts}|{name}")
            cmd.append(" ".join(specs))
        cmd.extend(["--title", title or "Select Files"])
    else:
        cmd = ["yad", "--file", "--title", title or "Select Files"]
        if allow_multi:
            cmd.append("--multiple")
            cmd.extend(["--separator", "|"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and result.stdout.strip():
            sep = "|" if tool in ("zenity", "yad") else "\n"
            return [p for p in result.stdout.strip().split(sep) if p and os.path.exists(p)]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"{tool} failed: {e}")
    return []


def _linux_pick_folder(title: Optional[str], start_dir: Optional[str]) -> Optional[str]:
    """Pick folder via zenity/kdialog (Linux)."""
    tool = _find_linux_dialog()
    if not tool:
        return None

    if tool == "zenity":
        cmd = ["zenity", "--file-selection", "--directory",
               "--title", title or "Select Folder"]
        if start_dir and os.path.isdir(start_dir):
            cmd.extend(["--filename", start_dir + "/"])
    elif tool == "kdialog":
        cmd = ["kdialog", "--getexistingdirectory", start_dir or ".",
               "--title", title or "Select Folder"]
    else:
        cmd = ["yad", "--file", "--directory", "--title", title or "Select Folder"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and result.stdout.strip():
            path = result.stdout.strip()
            return path if os.path.isdir(path) else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"{tool} failed: {e}")
    return None


def _linux_save_file(title: Optional[str], start_dir: Optional[str],
                     filters: Optional[dict], default_name: Optional[str]) -> Optional[str]:
    """Save file dialog via zenity/kdialog (Linux)."""
    tool = _find_linux_dialog()
    if not tool:
        return None

    if tool == "zenity":
        cmd = ["zenity", "--file-selection", "--save",
               "--title", title or "Save File", "--confirm-overwrite"]
        if filters:
            for name, spec in filters.items():
                exts = " ".join(f"*.{e.strip()}" for e in spec.split(","))
                cmd.extend(["--file-filter", f"{name} | {exts}"])
        init = start_dir or "."
        if default_name:
            init = os.path.join(init, default_name)
        cmd.extend(["--filename", init])
    elif tool == "kdialog":
        init = os.path.join(start_dir or ".", default_name or "")
        cmd = ["kdialog", "--getsavefilename", init,
               "--title", title or "Save File"]
    else:
        cmd = ["yad", "--file", "--save", "--title", title or "Save File"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"{tool} failed: {e}")
    return None


# =========================================================================
# Windows PowerShell fallback (if ctypes somehow fails)
# =========================================================================

def _run_powershell(script: str) -> str:
    """Run a PowerShell script and return stdout."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"PowerShell failed: {e}")
        return ""


def _ps_escape(s: str) -> str:
    """Escape for PowerShell single-quoted strings."""
    return s.replace("'", "''")


def _ps_build_filter(filters: Optional[dict]) -> str:
    """Convert filter dict to PowerShell dialog filter string."""
    if not filters:
        return "All Files (*.*)|*.*"
    parts = []
    for name, spec in filters.items():
        exts = ";".join(f"*.{e.strip()}" for e in spec.split(","))
        parts.append(f"{name} ({exts})|{exts}")
    parts.append("All Files (*.*)|*.*")
    return "|".join(parts)


def _ps_open_files(title: Optional[str], start_dir: Optional[str],
                   filters: Optional[dict], allow_multi: bool) -> List[str]:
    """Open file dialog via PowerShell (Windows fallback)."""
    ps_filter = _ps_escape(_ps_build_filter(filters))
    multi_str = "$true" if allow_multi else "$false"
    title_str = _ps_escape(title or "Select Files")

    script = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "$d = New-Object System.Windows.Forms.OpenFileDialog\n"
        f"$d.Title = '{title_str}'\n"
        f"$d.Filter = '{ps_filter}'\n"
        f"$d.Multiselect = {multi_str}\n"
    )
    if start_dir and os.path.isdir(start_dir):
        script += f"$d.InitialDirectory = '{_ps_escape(start_dir)}'\n"
    script += (
        "$null = $d.ShowDialog()\n"
        "if ($d.FileNames.Count -gt 0) { $d.FileNames -join '|' }\n"
    )
    output = _run_powershell(script)
    if output:
        return [p for p in output.split("|") if p and os.path.exists(p)]
    return []


def _ps_pick_folder(title: Optional[str], start_dir: Optional[str]) -> Optional[str]:
    """Pick folder via PowerShell (Windows fallback)."""
    title_str = _ps_escape(title or "Select Folder")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog\n"
        f"$d.Description = '{title_str}'\n"
        "$d.ShowNewFolderButton = $true\n"
    )
    if start_dir and os.path.isdir(start_dir):
        script += f"$d.SelectedPath = '{_ps_escape(start_dir)}'\n"
    script += (
        "$null = $d.ShowDialog()\n"
        "if ($d.SelectedPath) { $d.SelectedPath }\n"
    )
    output = _run_powershell(script)
    return output if output and os.path.isdir(output) else None


def _ps_save_file(title: Optional[str], start_dir: Optional[str],
                  filters: Optional[dict], default_name: Optional[str]) -> Optional[str]:
    """Save file dialog via PowerShell (Windows fallback)."""
    ps_filter = _ps_escape(_ps_build_filter(filters))
    title_str = _ps_escape(title or "Save File")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "$d = New-Object System.Windows.Forms.SaveFileDialog\n"
        f"$d.Title = '{title_str}'\n"
        f"$d.Filter = '{ps_filter}'\n"
    )
    if start_dir and os.path.isdir(start_dir):
        script += f"$d.InitialDirectory = '{_ps_escape(start_dir)}'\n"
    if default_name:
        script += f"$d.FileName = '{_ps_escape(default_name)}'\n"
    script += (
        "$null = $d.ShowDialog()\n"
        "if ($d.FileName) { $d.FileName }\n"
    )
    output = _run_powershell(script)
    return output if output else None


# =========================================================================
# BACKEND DETECTION
# =========================================================================

_backend = None  # 'win32', 'tkinter', 'os_subprocess', or 'none'


def get_backend() -> str:
    """Return which backend is active."""
    global _backend
    if _backend is not None:
        return _backend

    # Windows: prefer Win32 ctypes (fastest, most reliable, zero deps)
    if _check_win32():
        _backend = "win32"
        logger.info("Native dialog backend: Win32 ctypes (comdlg32.dll)")
        return _backend

    # Try tkinter (cross-platform, sometimes excluded from PyInstaller)
    if _check_tk():
        _backend = "tkinter"
        logger.info("Native dialog backend: tkinter")
        return _backend

    # OS-specific subprocess tools
    if _SYSTEM == "Windows":
        # PowerShell is always on modern Windows
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "echo ok"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0:
                _backend = "os_subprocess"
                logger.info("Native dialog backend: PowerShell")
                return _backend
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    elif _SYSTEM == "Darwin":
        try:
            r = subprocess.run(
                ["osascript", "-e", 'return "ok"'],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                _backend = "os_subprocess"
                logger.info("Native dialog backend: osascript")
                return _backend
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    else:
        if _find_linux_dialog():
            _backend = "os_subprocess"
            logger.info(f"Native dialog backend: {_find_linux_dialog()}")
            return _backend

    _backend = "none"
    logger.warning("No native dialog backend available")
    return _backend


# =========================================================================
# DISPATCH HELPERS
# =========================================================================

def _dispatch_open(title, start_dir, filters, allow_multi) -> List[str]:
    """Try all available backends for open files."""
    # Win32 ctypes
    if _check_win32():
        try:
            return _win32_open_files(title, start_dir, filters, allow_multi)
        except Exception as e:
            logger.warning(f"Win32 open_files failed: {e}")

    # tkinter
    if _check_tk():
        try:
            return _tk_open_files(title, start_dir, filters, allow_multi)
        except Exception as e:
            logger.warning(f"tkinter open_files failed: {e}")

    # OS subprocess
    try:
        if _SYSTEM == "Windows":
            return _ps_open_files(title, start_dir, filters, allow_multi)
        elif _SYSTEM == "Darwin":
            return _mac_open_files(title, start_dir, filters, allow_multi)
        else:
            return _linux_open_files(title, start_dir, filters, allow_multi)
    except Exception as e:
        logger.error(f"Subprocess open_files failed: {e}")

    return []


def _dispatch_folder(title, start_dir) -> Optional[str]:
    """Try all available backends for pick folder."""
    if _check_win32():
        try:
            return _win32_pick_folder(title, start_dir)
        except Exception as e:
            logger.warning(f"Win32 pick_folder failed: {e}")

    if _check_tk():
        try:
            return _tk_pick_folder(title, start_dir)
        except Exception as e:
            logger.warning(f"tkinter pick_folder failed: {e}")

    try:
        if _SYSTEM == "Windows":
            return _ps_pick_folder(title, start_dir)
        elif _SYSTEM == "Darwin":
            return _mac_pick_folder(title, start_dir)
        else:
            return _linux_pick_folder(title, start_dir)
    except Exception as e:
        logger.error(f"Subprocess pick_folder failed: {e}")

    return None


def _dispatch_save(title, start_dir, filters, default_name) -> Optional[str]:
    """Try all available backends for save file."""
    if _check_win32():
        try:
            return _win32_save_file(title, start_dir, filters, default_name)
        except Exception as e:
            logger.warning(f"Win32 save_file failed: {e}")

    if _check_tk():
        try:
            return _tk_save_file(title, start_dir, filters, default_name)
        except Exception as e:
            logger.warning(f"tkinter save_file failed: {e}")

    try:
        if _SYSTEM == "Windows":
            return _ps_save_file(title, start_dir, filters, default_name)
        elif _SYSTEM == "Darwin":
            return _mac_save_file(title, start_dir, filters, default_name)
        else:
            return _linux_save_file(title, start_dir, filters, default_name)
    except Exception as e:
        logger.error(f"Subprocess save_file failed: {e}")

    return None


# =========================================================================
# PUBLIC API
# =========================================================================

def open_files(title: str = "Select Files",
               start_dir: Optional[str] = None,
               filters: Optional[dict] = None,
               allow_multi: bool = True) -> List[str]:
    """Open native file selection dialog.

    Args:
        title: Dialog window title.
        start_dir: Initial directory to show.
        filters: File type filters as {description: "ext1,ext2,..."}
                 Example: {"Audio Files": "wav,mp3,ogg,flac,aiff,aif,m4a,wma"}
        allow_multi: If True, allow selecting multiple files.

    Returns:
        List of selected file paths (empty if cancelled).
    """
    get_backend()  # Ensure detection has run
    return _dispatch_open(title, start_dir, filters, allow_multi)


def pick_folder(title: str = "Select Folder",
                start_dir: Optional[str] = None) -> Optional[str]:
    """Open native folder selection dialog.

    Args:
        title: Dialog window title.
        start_dir: Initial directory to show.

    Returns:
        Selected folder path, or None if cancelled.
    """
    get_backend()
    return _dispatch_folder(title, start_dir)


def save_file(title: str = "Save File",
              start_dir: Optional[str] = None,
              filters: Optional[dict] = None,
              default_name: Optional[str] = None) -> Optional[str]:
    """Open native save file dialog.

    Args:
        title: Dialog window title.
        start_dir: Initial directory to show.
        filters: File type filters as {description: "ext1,ext2,..."}
        default_name: Default file name.

    Returns:
        Selected file path, or None if cancelled.
    """
    get_backend()
    return _dispatch_save(title, start_dir, filters, default_name)


def cleanup():
    """Shutdown the dialog backend (call on app exit)."""
    pass
