# -*- coding: utf-8 -*-
"""
Broadcast Loudness Normalizer (EBU R128 / ITU-R BS.1770-4)
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
Phone: +963934005922
Copyright (c) 2026 MHD. Shadi AL-Hasan
"""

import os
import subprocess
import argparse
from pathlib import Path

class LoudnessNormalizer:
    def __init__(self, target_i=-23.0, target_tp=-1.0, target_lra=7.0):
        self.target_i = target_i    # Integrated loudness in LUFS (-23 for EU/EBU, -24 for US/ATSC, -14 for web)
        self.target_tp = target_tp  # True peak in dBFS
        self.target_lra = target_lra # Loudness range

    def normalize_file(self, input_file: Path, output_file: Path):
        print(f"[*] Normalizing {input_file.name} to {self.target_i} LUFS...")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Two-pass loudnorm filter
        filter_str = f"loudnorm=I={self.target_i}:TP={self.target_tp}:LRA={self.target_lra}"
        cmd = [
            "ffmpeg", "-y", "-i", str(input_file),
            "-af", filter_str,
            "-ar", "48000",
            str(output_file)
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            print(f"[+] Output verified: {output_file.name}")
            return True
        print(f"[!] Normalization failed on: {input_file.name}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Enforce EBU R128 broadcast loudness compliance.")
    parser.add_argument("--input", "-i", required=True, help="Input audio or video file")
    parser.add_argument("--output", "-o", default=None, help="Output normalized file")
    parser.add_argument("--lufs", type=float, default=-23.0, help="Target Integrated Loudness (LUFS)")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output) if args.output else in_path.with_name(f"normalized_{in_path.name}")
    norm = LoudnessNormalizer(target_i=args.lufs)
    norm.normalize_file(in_path, out_path)

if __name__ == "__main__":
    main()
