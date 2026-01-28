import os
import sys
import subprocess
import shutil
import platform
import argparse

# Define supported targets and their requirements
# structure: target_key: (os_name, arch_search_term, exe_suffix)
TARGETS = {
    "linux_x86_64":   ("linux", "x86_64", ""),
    "linux_aarch64":  ("linux", "aarch64", ""),
    "windows_x86_64": ("windows", "64", ".exe"),
    "windows_x86":    ("windows", "x86", ".exe"),
    "macos_x86_64":   ("darwin", "x86_64", ""),
    "macos_arm64":    ("darwin", "arm64", ""),
}

def get_host_info():
    system = platform.system().lower()
    machine = platform.machine().lower()
    return system, machine

def is_compatible(target, host_system, host_machine):
    """
    Check if the target is buildable on the current host.
    PyInstaller requires:
    1. OS check: Linux -> Linux, Windows -> Windows, Darwin -> Darwin
    2. Arch check: x86_64 -> x86_64 (mostly).
       Note: MacOS might support Universal builds or Rosetta, but keep it strict for now.
       Windows x64 can often build x86 if Python is x86.
    """
    req_os, req_arch, _ = TARGETS[target]
    
    # OS Check
    if host_system != req_os:
        return False, f"Host OS '{host_system}' cannot build for Target OS '{req_os}'."
        
    # Arch Check
    # This is rough. 
    # If Host is x86_64, logic matches.
    # If Host is aarch64 (linux), logic matches.
    # Windows: If host is 64-bit but python is 32-bit? PyInstaller bundles the RUNNING python.
    # So we should strictly check python arch potentially? 
    # For simplicity: check machine string containment.
    
    # Special case: Windows x86 build on Windows x64 might work if using 32-bit Python?
    # But usually we just assume one host = one target.
    
    # Strict matching for now to avoid confusion
    # Exception: amd64 vs x86_64
    normalized_host_arch = host_machine
    if normalized_host_arch == "amd64": normalized_host_arch = "x86_64"
    if normalized_host_arch == "arm64": normalized_host_arch = "aarch64" # Mac usually uses arm64?
    
    normalized_target_arch = req_arch
    if normalized_target_arch == "aarch64" and req_os == "darwin": normalized_target_arch = "arm64" 
    
    # Allow partial match or strict?
    # "x86_64" in "x86_64" -> True
    # "64" in "amd64" -> True (for windows)
    
    if req_arch not in normalized_host_arch and normalized_host_arch not in req_arch:
        # Allow Windows generic '64' match
        if req_os == "windows" and "64" in req_arch and "64" in normalized_host_arch:
            pass
        else:
             return False, f"Host Arch '{normalized_host_arch}' differs from Target Arch '{req_arch}'."
        
    return True, "Compatible"

def build(target, clean=True):
    print(f"\n[BUILD] Attempting to build target: {target}")
    
    host_system, host_machine = get_host_info()
    compatible, reason = is_compatible(target, host_system, host_machine)
    
    if not compatible:
        print(f"  [SKIP] Skipping {target}. Reason: {reason}")
        print("  (PyInstaller cannot cross-compile natively between OSs)")
        return False

    req_os, req_arch, suffix = TARGETS[target]
    exe_name = f"pokey_vq{suffix}"
    
    # 1. Clean previous build (if requested)
    # We clean at start of script usually, but per-target clean is fine
    if clean:
        if os.path.exists("build"): shutil.rmtree("build")
        # Don't delete dist entirely, might have other targets
        
    # 2. Configure Output
    print(f"  Host: {host_system} {host_machine}")
    print(f"  Output: dist/{target}/{exe_name}")

    # 3. Define Data inclusions (Platform specific separators)
    sep = ";" if host_system == "windows" else ":"
    
    add_data = []
    add_data.append(f"players{sep}players")
    add_data.append(f"bin{sep}bin")
    
    try:
        import customtkinter
        ctk_path = os.path.dirname(customtkinter.__file__)
        add_data.append(f"{ctk_path}{sep}customtkinter")
    except ImportError:
        print("  Error: customtkinter not installed.")
        return False

    # 4. Build Arguments
    args = [
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--windowed", 
        "--name", "pokey_vq",
        "--clean",
        "--distpath", ".", # Build to current dir first to allow move
    ]
    
    for d in add_data:
        args.extend(["--add-data", d])
        
    # Hidden imports
    hidden = [
        "PIL._tkinter_finder",
        "pokey_vq.encoders.vq",
        "pokey_vq.encoders.raw",
        "scipy.signal",
        "scipy.io.wavfile",
        "numpy",
        "soundfile",
    ]
    for h in hidden:
        args.extend(["--hidden-import", h])

    # Excludes
    excludes = [
        "librosa", "numba", "llvmlite", "matplotlib", "pandas",
        "scikit-learn", "sklearn", "ipython", "pytest", "docutils"
    ]
    for e in excludes:
         args.extend(["--exclude-module", e])

    # Entry point
    args.append("pokey_vq/gui.py")
    
    # 5. Run PyInstaller
    # print("  Running:", " ".join(args))
    try:
        subprocess.check_call(args)
    except subprocess.CalledProcessError as e:
        print(f"  Error: PyInstaller failed with code {e.returncode}")
        return False
        
    # 6. Organize Output
    target_dir = os.path.join("dist", target)
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
        
    # PyInstaller output name logic
    # On Linux: pokey_vq
    # On Windows: pokey_vq.exe
    
    # We used --name pokey_vq, so output is standard
    # Windows always adds .exe
    
    built_path = "pokey_vq.exe" if host_system == "windows" else "pokey_vq"
    dst_path = os.path.join(target_dir, exe_name)
    
    if os.path.exists(built_path):
        if os.path.exists(dst_path): os.remove(dst_path)
        shutil.move(built_path, dst_path)
        print(f"  [SUCCESS] Built: {os.path.abspath(dst_path)}")
        return True
    else:
        # Maybe it's in dist/ because we messed up --distpath logic?
        # Checked args: --distpath . -> creates in CWD.
        print(f"  [ERROR] Output file {built_path} not found.")
        return False

def main():
    parser = argparse.ArgumentParser(description="Build PokeyVQ Standalone Executable")
    
    parser.add_argument("targets", nargs="*", 
                        help=f"Specific targets to build. Supported: {', '.join(TARGETS.keys())}")
    
    parser.add_argument("--all", action="store_true", 
                        help="Attempt to build ALL supported targets (skipping incompatible ones)")
                        
    parser.add_argument("--clean", action="store_true", default=True,
                        help="Clean build directories before starting")

    args = parser.parse_args()
    
    # Determine what to build
    to_build = []
    
    if args.all:
        to_build = list(TARGETS.keys())
    elif args.targets:
        # Validate requested targets
        for t in args.targets:
            if t not in TARGETS:
                print(f"Error: Unknown target '{t}'. Supported: {list(TARGETS.keys())}")
                sys.exit(1)
            to_build.append(t)
    else:
        # Default: Detect current host and build matching target
        system, machine = get_host_info()
        
        # Heuristic matching
        matched = None
        if system == "linux" and "x86_64" in machine: matched = "linux_x86_64"
        elif system == "linux" and "aarch64" in machine: matched = "linux_aarch64"
        elif system == "windows" and ("64" in machine or "x86" in machine): matched = "windows_x86_64" # Default to 64
        elif system == "darwin" and "x86_64" in machine: matched = "macos_x86_64"
        elif system == "darwin" and "arm64" in machine: matched = "macos_arm64"
        
        if matched:
            print(f"Auto-detected Target: {matched}")
            to_build = [matched]
        else:
            print(f"Could not auto-detect target for {system} {machine}.")
            print("Please specify a target manually.")
            sys.exit(1)
            
    # Run Builds
    success_count = 0
    print(f"Build Queue: {to_build}")
    
    for t in to_build:
        if build(t, clean=args.clean):
            success_count += 1
            
    if success_count == 0:
        print("\nNo targets were built successfully.")
        sys.exit(1)
    else:
        print(f"\nCompleted. Built {success_count}/{len(to_build)} requested targets.")

if __name__ == "__main__":
    main()
