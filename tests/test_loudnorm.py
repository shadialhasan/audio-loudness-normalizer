# -*- coding: utf-8 -*-
"""
Automated Unit Tests for Audio Loudness Normalizer
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
"""

import os
import sys
import wave
import struct
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loudnorm import (
    LoudnessNormalizer,
    PRESETS,
    Logger,
    is_ffmpeg_available,
    load_config_file,
    load_env_file,
    build_parser,
)


def create_synthetic_audio(filepath: Path, duration_sec: float = 1.0, sample_rate: int = 48000):
    """Utility to generate a test WAV file for FFmpeg validation."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_sec * sample_rate)
    samples = [int(16000 * math.sin(2 * math.pi * 440 * (i / sample_rate))) for i in range(num_samples)]
    with wave.open(str(filepath), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        packed = struct.pack(f"<{len(samples)}h", *samples)
        wf.writeframes(packed)


class TestLoudnessNormalizer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_path = Path(self.temp_dir.name)
        self.normalizer = LoudnessNormalizer(
            target_i=-23.0,
            target_tp=-1.0,
            target_lra=7.0,
            sample_rate=48000,
            logger=Logger(color_enabled=False),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parameter_validation(self):
        with self.assertRaises(ValueError):
            LoudnessNormalizer(target_i=-80.0)
        with self.assertRaises(ValueError):
            LoudnessNormalizer(target_tp=1.0)
        with self.assertRaises(ValueError):
            LoudnessNormalizer(target_lra=0.5)
        with self.assertRaises(ValueError):
            LoudnessNormalizer(sample_rate=-10)

    def test_presets(self):
        norm_ebu = LoudnessNormalizer.from_preset("ebu_r128")
        self.assertEqual(norm_ebu.target_i, -23.0)
        self.assertEqual(norm_ebu.target_tp, -1.0)
        self.assertEqual(norm_ebu.target_lra, 7.0)

        norm_streaming = LoudnessNormalizer.from_preset("streaming")
        self.assertEqual(norm_streaming.target_i, -14.0)

        with self.assertRaises(ValueError):
            LoudnessNormalizer.from_preset("non_existent_preset")

    def test_command_building(self):
        filter_str = self.normalizer.build_filter_string()
        self.assertEqual(filter_str, "loudnorm=I=-23.0:TP=-1.0:LRA=7.0")

        in_f = Path("input.wav")
        out_f = Path("output.wav")
        cmd = self.normalizer.build_command(in_f, out_f)
        self.assertIn("ffmpeg", cmd[0])
        self.assertIn("-af", cmd)
        self.assertIn(filter_str, cmd)
        self.assertIn("48000", cmd)
        self.assertEqual(cmd[-1], str(out_f))

    def test_normalize_missing_input_file(self):
        missing = self.work_path / "does_not_exist.wav"
        ok, msg = self.normalizer.normalize_file(missing, self.work_path / "out.wav")
        self.assertFalse(ok)
        self.assertIn("Input file not found", msg)

    @patch("loudnorm.is_ffmpeg_available", return_value=False)
    def test_normalize_missing_ffmpeg(self, mock_ffmpeg):
        dummy_in = self.work_path / "dummy.wav"
        dummy_in.write_bytes(b"dummy")
        ok, msg = self.normalizer.normalize_file(dummy_in, self.work_path / "out.wav")
        self.assertFalse(ok)
        self.assertIn("FFmpeg executable not found", msg)

    @patch("subprocess.run")
    def test_normalize_mocked_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        dummy_in = self.work_path / "audio.wav"
        dummy_in.write_bytes(b"data")
        dummy_out = self.work_path / "norm.wav"

        ok, msg = self.normalizer.normalize_file(dummy_in, dummy_out)
        self.assertTrue(ok)
        self.assertEqual(msg, "Success")
        self.assertTrue(mock_run.called)

    @patch("subprocess.run")
    def test_normalize_mocked_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: Invalid codec parameters")
        dummy_in = self.work_path / "audio.wav"
        dummy_in.write_bytes(b"data")
        dummy_out = self.work_path / "norm.wav"

        ok, msg = self.normalizer.normalize_file(dummy_in, dummy_out)
        self.assertFalse(ok)
        self.assertIn("Invalid codec parameters", msg)

    def test_normalize_directory(self):
        in_dir = self.work_path / "batch_in"
        out_dir = self.work_path / "batch_out"
        in_dir.mkdir(parents=True, exist_ok=True)

        (in_dir / "test1.wav").write_bytes(b"1")
        (in_dir / "test2.wav").write_bytes(b"2")

        with patch.object(self.normalizer, "normalize_file", return_value=(True, "Success")):
            res = self.normalizer.normalize_directory(in_dir, out_dir)
            self.assertEqual(res["total"], 2)
            self.assertEqual(res["succeeded"], 2)
            self.assertEqual(res["failed"], 0)

    def test_normalize_missing_directory(self):
        res = self.normalizer.normalize_directory(self.work_path / "nonexistent", self.work_path / "out")
        self.assertEqual(res["total"], 0)

    def test_config_and_env_loaders(self):
        cfg_file = self.work_path / "test_cfg.json"
        cfg_file.write_text('{"target_i": -16.0, "preset": "podcast"}', encoding="utf-8")
        cfg = load_config_file(cfg_file)
        self.assertEqual(cfg["target_i"], -16.0)
        self.assertEqual(cfg["preset"], "podcast")

        env_file = self.work_path / ".env.test"
        env_file.write_text("TARGET_I=-14.0\nTARGET_TP=-1.5\n", encoding="utf-8")
        env = load_env_file(env_file)
        self.assertEqual(env["TARGET_I"], "-14.0")
        self.assertEqual(env["TARGET_TP"], "-1.5")

    def test_cli_parser(self):
        parser = build_parser()
        args = parser.parse_args(["--input", "song.wav", "--lufs", "-14.0", "--preset", "streaming"])
        self.assertEqual(args.input, "song.wav")
        self.assertEqual(args.lufs, -14.0)
        self.assertEqual(args.preset, "streaming")

    def test_real_ffmpeg_integration(self):
        """End-to-end integration test with live ffmpeg binary if available."""
        if not is_ffmpeg_available():
            self.skipTest("FFmpeg not available in local environment.")

        in_wav = self.work_path / "real_in.wav"
        out_wav = self.work_path / "real_out.wav"
        create_synthetic_audio(in_wav, duration_sec=1.5)

        ok, msg = self.normalizer.normalize_file(in_wav, out_wav)
        self.assertTrue(ok, f"FFmpeg failed: {msg}")
        self.assertTrue(out_wav.exists())
        self.assertGreater(out_wav.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
