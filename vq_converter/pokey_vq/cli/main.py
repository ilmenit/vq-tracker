import sys
import argparse
from .builder import PokeyVQBuilder
from .helpers import get_valid_pal_rates

def main():
    # Generate Rate Table for Help
    valid_rates = get_valid_pal_rates()
    rate_table = "POKEY PAL Supported Rates (Selected):\n"
    rate_table += "--------------------------------------\n"
    
    # Format: Div $XX: XXXXX Hz | ...
    # Show values down to ~1500Hz which is Div 41. 
    
    col_count = 0
    buffer = []
    
    sorted_divs = sorted(valid_rates.keys())
    # Filter for reasonable audio rates (> 1500Hz)
    display_divs = [d for d in sorted_divs if valid_rates[d] >= 1500 and d >= 3]
    
    for d in display_divs:
        r = valid_rates[d]
        item = f"Div ${d:02X}: {int(r):5d} Hz"
        buffer.append(item)
        if len(buffer) >= 3:
            rate_table += "   ".join(buffer) + "\n"
            buffer = []
            
    if buffer:
        rate_table += "   ".join(buffer) + "\n"

    description = """
PokeyVQ - Atari 8-bit VQ Encoder & Player Builder
=================================================
Compresses audio and builds a standalone Atari XEX player.

Features:
- Variable-Rate Vector Quantization (VQ)
- Automatic POKEY frequency calculation
- Full 105-level POKEY voltage optimization (Always Active)
- Strict PAL Rate Enforcement with Auto-Snapping

Examples:
  python -m pokey_vq.cli music.mp3
  python -m pokey_vq.cli music.mp3 --quality 100 --rate 7917
  python -m pokey_vq.cli music.mp3 -r 8000 (Snaps to 7917Hz)
  python -m pokey_vq.cli speech.wav -r 4000 (Snaps to 3958Hz)
"""

    epilog = f"""
Parameters Detail:
------------------
--quality (0-100):
  The main fidelity control (Piecewise Logarithmic Scale).
  0   = Maximum Compression / Lowest Quality (Lambda 0.5)
  25  = Medium Quality (Lambda ~0.07)
  50  = High Quality (Lambda 0.01) [Default]
  75  = Very High Quality (Lambda 0.001)
  100 = Lossless-ish / Maximum Size (Lambda 0.0001)

--smoothness (0-100):
  Reduces "clicking" by penalizing large jumps between vectors.
  0   = No smoothing (Pure MSE)
  100 = Maximum smoothing (Alpha 1.0)
  Try values like 20-50 if audio sounds "staticky".

--codebook (Size):
  Number of unique patterns.
  Max 256 (Hard limit of 8-bit player).
  128 or 256 are standard.

--min-vector / --max-vector (Sample Lengths):
  Controls the duration of standard patterns.
  Short (1-4) = Better transient response, higher bitrate.
  Long (16+)  = Better tone compression, lower bitrate.

{rate_table}
"""

    parser = argparse.ArgumentParser(
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument('input', nargs='*', 
                        help='Input audio file(s).')
    
    parser.add_argument('-if', '--input-folder', action='append',
                        help='Recursively scan folder for audio files. Can be used multiple times.')

    parser.add_argument('-o', '--output', help='Optional output filename')
    parser.add_argument('-r', '--rate', type=int, default=7917, 
                        help='Sample Rate in Hz (Default: 7917)')
    
    parser.add_argument('--channels', type=int, choices=[1, 2], default=2,
                        help='Number of audio channels (1 or 2). Default: 2')
    
    # Algo Selection
    # Modes
    parser.add_argument('-p', '--player', type=str, 
        choices=['raw', 'vq_basic', 'vq_samples', 'vq_pitch', 'vq_multi_channel'], 
        default='vq_basic',
        help='Select player mode:\n'
             '  raw              = Max quality, low CPU, one sample (looping)\n'
             '  vq_basic         = Standard VQ, one sample (looping)\n'
             '  vq_samples       = Multi-sample playback (keyboard selection)\n'
             '  vq_pitch         = Piano keyboard with octave control\n'
             '  vq_multi_channel = Parallel multi-channel playback'
    )
    
    # Internal algo mapping handles these now
    parser.add_argument('--algo', type=str, default='fixed', help=argparse.SUPPRESS) # Legacy compat placeholder

    group = parser.add_argument_group('Compression Options')
    
    group.add_argument('-q', '--quality', type=float, default=50.0, 
                       help='Quality Score 0-100. Default: 50')
    
    group.add_argument('-s', '--smoothness', type=float, default=0.0, 
                       help='Smoothness Score 0-100. Default: 0')
    
    group.add_argument('-c', '--codebook', type=int, default=256, 
                       help='Codebook Size. Default: 256')
    
    # Enhance Default True
    # Enhance 
    group.add_argument('-e', '--enhance', type=str, choices=['on', 'off'], default='on',
                       help='Apply audio enhancements (Default: on)')
    
    # Deprecated --no-enhance (Still works but hidden or mapped)
    group.add_argument('--no-enhance', action='store_true', help=argparse.SUPPRESS)

    group.add_argument('--lbg', '-l', action='store_true', 
                       help='Use LBG/K-Means++ initialization (Slower, better quality)')

    # Advanced / Legacy
    group.add_argument('-i', '--iterations', type=int, default=50, 
                       help='Max VQ iterations. Default: 50')
    # group.add_argument('--sliding-window', action='store_true', help=argparse.SUPPRESS) # Removed
    group.add_argument('--raw', action='store_true', help=argparse.SUPPRESS) # Legacy alias
    group.add_argument('-miv', '--min-vector', type=int, default=1, 
                       help='Min Vector Length. Default: 1')
    group.add_argument('-mav', '--max-vector', type=int, default=16, 
                       help='Max Vector Length. Default: 16')
    group.add_argument('-w', '--window-size', type=int, default=255,
                       help='Window Size (Compression Window). Default: 255')
    
    # Voltage / Constrained
    group.add_argument('-v', '--voltage', type=str, choices=['on', 'off'], default='off',
                       help='Constrain VQ to POKEY voltage levels. (Default: off)')
    
    # Legacy -c / --constrained needs to be handled if we want to support it
    group.add_argument('--constrained', action='store_true', help=argparse.SUPPRESS)
                       

    # Output Control
    group.add_argument('--no-player', action='store_true',
                       help='Skip .xex player assembly (Generate data only)')

    group.add_argument('--show-cpu-use', type=str, choices=['on', 'off'], default='on',
                       help='Show CPU Usage indicator in player (Default: on)')

                       
    # Modes
    parser.add_argument('--optimize', '-op', choices=['size', 'speed'], default='size',
                        help="Optimization goal: 'size' (Packed 1-byte) or 'speed' (Fast 2-byte) [Default: size]")
    
    parser.add_argument('--fast-cpu', action='store_true', help=argparse.SUPPRESS) # Legacy Support
    parser.add_argument('--fast', '-f', action='store_true', help=argparse.SUPPRESS) # Legacy Alias

    
    parser.add_argument('--wav', choices=['on', 'off'], default='on',
                        help='Export verification WAV (Default: on)')
    
    parser.add_argument('--debug', action='store_true',
                        help='Show full traceback on error')

    # Show help if no arguments specified
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    
    # Validate min/max vector lengths
    if args.min_vector > args.max_vector:
        print(f"Warning: min-vector ({args.min_vector}) > max-vector ({args.max_vector}). Swapping values.")
        args.min_vector, args.max_vector = args.max_vector, args.min_vector
    
    app = PokeyVQBuilder(args)
    sys.exit(app.run())

if __name__ == '__main__':
    main()
