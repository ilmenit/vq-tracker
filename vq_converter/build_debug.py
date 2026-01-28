
import os
import shutil
import subprocess

# Config
MADS_PATH = "./bin/linux_x86_64/mads"
DATA_DIR = "outputs/short_test-r7917-q50-s0-fix-enh-hifi"
PLAYER_SRC = "players/debug_player.asm"
OUTPUT_XEX = "debug_player.xex"

def build_debug_player():
    print("--- Building Debug Player ---")
    
    # 1. Check Data Availability
    if not os.path.exists(DATA_DIR):
        print(f"Error: Data directory not found: {DATA_DIR}")
        print("Please run the standard build first to generate VQ data.")
        return

    # 2. Copy Player to Data Dir (simplest way to resolve includes)
    # or Copy Data to current dir? 
    # Let's run MADS inside the Data Dir, copying the player there.
    
    target_asm = os.path.join(DATA_DIR, "debug_player.asm")
    shutil.copy2(PLAYER_SRC, target_asm)
    print(f"Copied player to {target_asm}")
    
    # 3. Run MADS
    cmd = [MADS_PATH, "debug_player.asm", f"-o:{OUTPUT_XEX}"]
    
    # MADS might need absolute path if running from subdir
    if not os.path.isabs(MADS_PATH):
         cmd[0] = os.path.abspath(MADS_PATH)
         
    print(f"Running MADS: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=DATA_DIR, capture_output=True, text=True)
    
    print(result.stdout)
    if result.returncode != 0:
        print(f"Build Failed: {result.stderr}")
    else:
        print(f"Success! Created {os.path.join(DATA_DIR, OUTPUT_XEX)}")

if __name__ == "__main__":
    build_debug_player()
