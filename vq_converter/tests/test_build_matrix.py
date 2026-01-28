import os
import subprocess
import itertools
import sys
import tempfile
import shutil

# Configuration Options
# Map Player Mode -> ASM File (for building)
# Note: The CLI now handles selecting the ASM file for the user during generation,
# but for verification we need to know which one to compile using MADS manually 
# if we want to test "manual assembly" or we can trust the CLI's --output structure.
# Let's test the manual assembly path to ensure independence.

PLAYER_MODES = [
    ("vq_basic", "player.asm"),
    ("vq_samples", "sample_player.asm"),
    ("vq_pitch", "pitch_player.asm"),
    ("vq_multi_channel", "tracker_player.asm"),
    ("raw", "raw_player.asm")
]

CHANNELS = [1, 2]
OPTIMIZE = ["size", "speed"] 

TEST_WAV = "tests/test_complex.wav"

def run_test_case(mode, asm_file, channels, optimize):
    """
    Runs a single test case in a temporary directory.
    """
    print(f"--> Testing: {mode} | Ch:{channels} | Opt:{optimize}")
    
    # Create persistent output directory
    test_name = f"{mode}_ch{channels}_{optimize}"
    # Use absolute path to avoid confusion
    base_output_dir = os.path.join(os.getcwd(), "tests", "test_outputs")
    temp_dir = os.path.join(base_output_dir, test_name)
    os.makedirs(temp_dir, exist_ok=True)
    
    # Define outputs
    # We need a subdirectory because the CLI might generate multiple files
    # using the output name as a base.
    build_dir = os.path.join(temp_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    
    # 1. Run Encoder (CLI)
    # ---------------------------------------------------------
    cmd_cli = [
        sys.executable, "-m", "pokey_vq.cli",
        os.path.abspath(TEST_WAV),
        "--output", os.path.join(build_dir, "test_out.xex"),
        "--player", mode,
        "--channels", str(channels),
        "--optimize", optimize,
        "--rate", "4000"
    ]
    
    if mode == "vq_multi_channel" or mode == "vq_pitch":
            cmd_cli.extend(["--min-vector", "16", "--max-vector", "16"])

    try:
        # Run CLI
        subprocess.check_output(cmd_cli, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print(f"    [FAIL] CLI Encoding Failed")
        print("    " + e.output.decode('latin-1', errors='ignore').replace('\n', '\n    '))
        return False

    # 2. Manual Assembly Verification
    # ---------------------------------------------------------
    # We need to assemble the player using MADS, pointing it to our generated data.
    # The generated files (VQ_CFG.asm, etc.) are in `build_dir` (because of --output folder logic? 
    # or flat file logic? 
    # If output is "test_out.xex", CLI usually puts artifacts in same folder.
    
    # We need to locate the source ASM files (players_dir)
    project_root = os.getcwd() # Assumption: running from root
    players_dir = os.path.join(project_root, "players")
    
    # MADS Command
    # We need to include:
    # - The generated data directory (build_dir)
    # - The source code directory (players/)
    # - The source code "common" directory? (players/common is inside players)
    
    # Target ASM file
    target_asm = os.path.join(players_dir, asm_file)
    
    cmd_mads = [
        os.path.join(project_root, "bin/linux_x86_64/mads"), # Use project mads
        target_asm,
        f"-o:{os.path.join(build_dir, 'manual_test.xex')}",
        f"-i:{build_dir}",   # Include generated data
        f"-i:{players_dir}"  # Include source files
    ]
    
    try:
        subprocess.check_output(cmd_mads, stderr=subprocess.STDOUT)
        print("    [PASS] Assembly Success")
        return True
    except subprocess.CalledProcessError as e:
        print(f"    [FAIL] MADS Assembly Failed")
        print("    " + e.output.decode('latin-1', errors='ignore').replace('\n', '\n    '))
        return False

def run_tests():
    print("==================================================")
    print("  PokeyVQ Build Matrix Test")
    print("  Ensures all player modes link correctly.")
    print("==================================================")
    
    if not os.path.exists(TEST_WAV):
        print(f"Error: Test file not found: {TEST_WAV}")
        sys.exit(1)

    success_count = 0
    fail_count = 0
    
    for mode, asm in PLAYER_MODES:
        for chan in CHANNELS:
            # Skip invalid combos if necessary
            if mode == 'raw' and chan == 2:
                # Raw supports 2 channels? Yes, RawEncoder handles it.
                pass
            
            for opt in OPTIMIZE:
                if mode == 'raw' and opt == 'speed':
                    continue # Raw doesn't have speed/size variants really? 
                             # CLI ignores it or RAW implementation might not care.
                
                if run_test_case(mode, asm, chan, opt):
                    success_count += 1
                else:
                    fail_count += 1
                    
    print("\n--------------------------------------------------")
    print(f"RESULTS: {success_count} Passed, {fail_count} Failed")
    print("--------------------------------------------------")
    
    return fail_count

if __name__ == "__main__":
    sys.exit(run_tests())
