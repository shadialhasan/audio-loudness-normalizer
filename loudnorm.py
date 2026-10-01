# -*- coding: utf-8 -*-
"""
Broadcast Loudness Normalizer (EBU R128 / ITU-R BS.1770-4)
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
Phone: +963934005922
Copyright (c) 2026 MHD. Shadi AL-Hasan
"""

import os
import sys
import json
import shutil
import subprocess
import argparse
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# Enable VT100 colors on legacy Windows consoles if possible
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


class Logger:
    """Terminal logger with ANSI colors and cross-platform fallback."""
    COLORS = {
        "RESET": "\033[0m",
        "BOLD": "\033[1m",
        "CYAN": "\033[36m",
        "GREEN": "\033[32m",
        "YELLOW": "\033[33m",
        "RED": "\033[31m",
        "MAGENTA": "\033[35m",
        "GRAY": "\033[90m",
    }

    def __init__(self, color_enabled: bool = True):
        self.color_enabled = color_enabled and (
            hasattr(sys.stdout, "isatty") and sys.stdout.isatty() or os.getenv("FORCE_COLOR") == "1"
        )

    def _c(self, color_name: str, text: str) -> str:
        if self.color_enabled and color_name in self.COLORS:
            return f"{self.COLORS[color_name]}{text}{self.COLORS['RESET']}"
        return text

    def info(self, msg: str):
        print(f"{self._c('CYAN', '[*]')} {msg}")

    def success(self, msg: str):
        print(f"{self._c('GREEN', '[+]')} {msg}")

    def warning(self, msg: str):
        print(f"{self._c('YELLOW', '[!]')} {msg}")

    def error(self, msg: str):
        print(f"{self._c('RED', '[-] ERROR:')} {msg}", file=sys.stderr)


log = Logger()

# Predefined industry loudness standards
PRESETS: Dict[str, Dict[str, float]] = {
    "ebu_r128": {"target_i": -23.0, "target_tp": -1.0, "target_lra": 7.0},
    "atsc_a85": {"target_i": -24.0, "target_tp": -2.0, "target_lra": 14.0},
    "streaming": {"target_i": -14.0, "target_tp": -1.0, "target_lra": 11.0},
    "podcast": {"target_i": -16.0, "target_tp": -1.0, "target_lra": 11.0},
}


def load_env_file(filepath: Path) -> Dict[str, str]:
    """Parse key=value pairs from a .env file without external dependencies."""
    env_vars: Dict[str, str] = {}
    if not filepath.exists() or not filepath.is_file():
        return env_vars
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    except Exception as exc:
        log.warning(f"Could not parse environment file {filepath}: {exc}")
    return env_vars


def load_config_file(filepath: Path) -> Dict[str, Any]:
    """Load configuration dictionary from JSON file."""
    if not filepath.exists() or not filepath.is_file():
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning(f"Could not load config file {filepath}: {exc}")
        return {}


def is_ffmpeg_available(ffmpeg_path: str = "ffmpeg") -> bool:
    """Verify if FFmpeg binary is available on system PATH."""
    return shutil.which(ffmpeg_path) is not None


class LoudnessNormalizer:
    """Automates ITU-R BS.1770-4 / EBU R128 loudness normalization using FFmpeg loudnorm filter."""

    def __init__(
        self,
        target_i: float = -23.0,
        target_tp: float = -1.0,
        target_lra: float = 7.0,
        sample_rate: int = 48000,
        ffmpeg_path: str = "ffmpeg",
        logger: Optional[Logger] = None,
    ):
        if not (-70.0 <= target_i <= -5.0):
            raise ValueError(f"target_i must be within [-70.0, -5.0] LUFS, got {target_i}")
        if not (-10.0 <= target_tp <= 0.0):
            raise ValueError(f"target_tp must be within [-10.0, 0.0] dBFS, got {target_tp}")
        if not (1.0 <= target_lra <= 50.0):
            raise ValueError(f"target_lra must be within [1.0, 50.0] LU, got {target_lra}")
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")

        self.target_i = float(target_i)
        self.target_tp = float(target_tp)
        self.target_lra = float(target_lra)
        self.sample_rate = int(sample_rate)
        self.ffmpeg_path = ffmpeg_path
        self.log = logger or log

    @classmethod
    def from_preset(
        cls,
        preset_name: str,
        sample_rate: int = 48000,
        ffmpeg_path: str = "ffmpeg",
        logger: Optional[Logger] = None,
    ) -> "LoudnessNormalizer":
        """Instantiate normalizer configured according to standard broadcast presets."""
        preset_key = preset_name.lower().strip()
        if preset_key not in PRESETS:
            valid = ", ".join(PRESETS.keys())
            raise ValueError(f"Unknown preset '{preset_name}'. Supported presets: {valid}")
        cfg = PRESETS[preset_key]
        return cls(
            target_i=cfg["target_i"],
            target_tp=cfg["target_tp"],
            target_lra=cfg["target_lra"],
            sample_rate=sample_rate,
            ffmpeg_path=ffmpeg_path,
            logger=logger,
        )

    def build_filter_string(self) -> str:
        """Construct the FFmpeg audio filter parameter string."""
        return f"loudnorm=I={self.target_i}:TP={self.target_tp}:LRA={self.target_lra}"

    def build_command(self, input_file: Path, output_file: Path) -> List[str]:
        """Construct complete subprocess command arguments."""
        filter_str = self.build_filter_string()
        return [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(input_file),
            "-af",
            filter_str,
            "-ar",
            str(self.sample_rate),
            str(output_file),
        ]

    def normalize_file(self, input_file: Path, output_file: Path, timeout_sec: int = 300) -> Tuple[bool, str]:
        """
        Executes loudness normalization on a single audio file.
        Returns: (success: bool, message: str)
        """
        input_file = Path(input_file)
        output_file = Path(output_file)

        if not input_file.exists():
            msg = f"Input file not found: {input_file}"
            self.log.error(msg)
            return False, msg

        if not is_ffmpeg_available(self.ffmpeg_path):
            msg = f"FFmpeg executable not found at '{self.ffmpeg_path}'. Please install FFmpeg."
            self.log.error(msg)
            return False, msg

        self.log.info(
            f"Normalizing {input_file.name} -> Target: {self.target_i} LUFS, TP: {self.target_tp} dBFS, LRA: {self.target_lra} LU"
        )
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            cmd = self.build_command(input_file, output_file)
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
                check=False,
            )

            if res.returncode == 0:
                self.log.success(f"Output verified: {output_file.name}")
                return True, "Success"
            else:
                err_msg = res.stderr.strip().splitlines()[-1] if res.stderr else "Unknown FFmpeg error"
                self.log.error(f"FFmpeg failed with exit code {res.returncode}: {err_msg}")
                return False, err_msg
        except subprocess.TimeoutExpired:
            msg = f"FFmpeg processing timed out after {timeout_sec} seconds"
            self.log.error(msg)
            return False, msg
        except Exception as exc:
            msg = f"Normalization failed on {input_file.name}: {exc}"
            self.log.error(msg)
            return False, msg

    def normalize_directory(
        self, input_dir: Path, output_dir: Path, pattern: str = "*.wav"
    ) -> Dict[str, Any]:
        """Normalize all matching audio files within a directory."""
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)

        if not input_dir.exists() or not input_dir.is_dir():
            self.log.error(f"Directory not found: {input_dir}")
            return {"total": 0, "succeeded": 0, "failed": 0}

        files = sorted(list(input_dir.glob(pattern)))
        self.log.info(f"Discovered {len(files)} files matching pattern '{pattern}' in {input_dir}")

        succeeded = 0
        failed = 0

        for idx, file_path in enumerate(files, 1):
            out_file = output_dir / f"norm_{file_path.name}"
            ok, _ = self.normalize_file(file_path, out_file)
            if ok:
                succeeded += 1
            else:
                failed += 1

        self.log.info(f"Batch Summary: {succeeded}/{len(files)} files normalized successfully.")
        return {"total": len(files), "succeeded": succeeded, "failed": failed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enforce EBU R128 / ITU-R BS.1770-4 broadcast and streaming loudness compliance."
    )
    parser.add_argument("--input", "-i", type=str, required=False, help="Input audio or video file or folder")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output normalized file or folder")
    parser.add_argument(
        "--lufs",
        type=float,
        default=None,
        help="Target Integrated Loudness in LUFS (-23.0 for EBU R128, -14.0 for streaming)",
    )
    parser.add_argument("--tp", type=float, default=None, help="Target True Peak in dBFS (e.g. -1.0)")
    parser.add_argument("--lra", type=float, default=None, help="Target Loudness Range (e.g. 7.0)")
    parser.add_argument(
        "--preset",
        "-p",
        type=str,
        default=None,
        choices=list(PRESETS.keys()),
        help="Predefined standard profile (ebu_r128, atsc_a85, streaming, podcast)",
    )
    parser.add_argument("--sample-rate", "-sr", type=int, default=None, help="Output sample rate in Hz (default 48000)")
    parser.add_argument("--config", "-c", type=str, default="config.json", help="Path to JSON configuration file")
    parser.add_argument("--env-file", type=str, default=".env", help="Path to .env configuration file")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color codes")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    cfg_file = Path(args.config)
    env_file = Path(args.env_file)
    cfg_data = load_config_file(cfg_file)
    env_data = load_env_file(env_file)

    def resolve(cli_val, env_key, cfg_key, default_val, cast_fn=str):
        if cli_val is not None:
            return cast_fn(cli_val)
        if env_key in env_data:
            return cast_fn(env_data[env_key])
        if cfg_key in cfg_data:
            return cast_fn(cfg_data[cfg_key])
        return default_val

    custom_logger = Logger(color_enabled=not args.no_color)

    if not args.input:
        parser.print_help()
        custom_logger.error("Missing required argument: --input / -i")
        sys.exit(1)

    preset = resolve(args.preset, "PRESET", "preset", None, str)
    if preset and preset in PRESETS:
        preset_cfg = PRESETS[preset]
        default_i = preset_cfg["target_i"]
        default_tp = preset_cfg["target_tp"]
        default_lra = preset_cfg["target_lra"]
    else:
        default_i = -23.0
        default_tp = -1.0
        default_lra = 7.0

    target_i = resolve(args.lufs, "TARGET_I", "target_i", default_i, float)
    target_tp = resolve(args.tp, "TARGET_TP", "target_tp", default_tp, float)
    target_lra = resolve(args.lra, "TARGET_LRA", "target_lra", default_lra, float)
    sample_rate = resolve(args.sample_rate, "SAMPLE_RATE", "sample_rate", 48000, int)
    ffmpeg_bin = resolve(None, "FFMPEG_PATH", "ffmpeg_path", "ffmpeg", str)

    in_path = Path(args.input)
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = in_path.with_name(f"normalized_{in_path.name}")

    try:
        normalizer = LoudnessNormalizer(
            target_i=target_i,
            target_tp=target_tp,
            target_lra=target_lra,
            sample_rate=sample_rate,
            ffmpeg_path=ffmpeg_bin,
            logger=custom_logger,
        )

        if in_path.is_dir():
            normalizer.normalize_directory(in_path, out_path)
        else:
            success, _ = normalizer.normalize_file(in_path, out_path)
            if not success:
                sys.exit(1)
    except Exception as exc:
        custom_logger.error(f"Fatal execution error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
