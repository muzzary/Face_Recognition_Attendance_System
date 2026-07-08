import unittest
from pathlib import Path

from face_attendance.config import AppSettings, SettingsError


class AppSettingsTests(unittest.TestCase):
    def test_defaults_are_sensible(self) -> None:
        settings = AppSettings.from_env(environ={})

        self.assertEqual(settings.camera_index, 0)
        self.assertEqual(settings.similarity_threshold, 0.363)
        self.assertEqual(settings.enrollment_samples, 5)
        self.assertEqual(settings.cooldown_seconds, 60)
        self.assertEqual(settings.database_path, Path("data/attendance.db"))

    def test_env_overrides_apply(self) -> None:
        settings = AppSettings.from_env(
            environ={
                "FA_CAMERA_INDEX": "2",
                "FA_SIMILARITY_THRESHOLD": "0.5",
                "FA_DATABASE_PATH": "elsewhere/db.sqlite",
                "PATH": "ignored",
            }
        )

        self.assertEqual(settings.camera_index, 2)
        self.assertEqual(settings.similarity_threshold, 0.5)
        self.assertEqual(settings.database_path, Path("elsewhere/db.sqlite"))

    def test_invalid_value_names_the_variable(self) -> None:
        with self.assertRaises(SettingsError) as ctx:
            AppSettings.from_env(environ={"FA_CAMERA_INDEX": "-3"})
        self.assertIn("FA_CAMERA_INDEX", str(ctx.exception))

    def test_non_numeric_value_fails_loudly(self) -> None:
        with self.assertRaises(SettingsError):
            AppSettings.from_env(environ={"FA_COOLDOWN_SECONDS": "abc"})

    def test_unknown_variable_rejected(self) -> None:
        with self.assertRaises(SettingsError) as ctx:
            AppSettings.from_env(environ={"FA_TYPO_FIELD": "1"})
        self.assertIn("FA_TYPO_FIELD", str(ctx.exception))

    def test_liveness_defaults_form_valid_bands(self) -> None:
        settings = AppSettings.from_env(environ={})

        self.assertLess(settings.liveness_min_motion, settings.liveness_max_motion)
        self.assertGreaterEqual(settings.liveness_min_deformation, 0.0)

    def test_inverted_liveness_motion_band_rejected(self) -> None:
        with self.assertRaises(SettingsError) as ctx:
            AppSettings.from_env(
                environ={"FA_LIVENESS_MIN_MOTION": "0.5", "FA_LIVENESS_MAX_MOTION": "0.1"}
            )
        self.assertIn("liveness_min_motion", str(ctx.exception))

    def test_model_paths_derive_from_models_dir(self) -> None:
        settings = AppSettings.from_env(environ={"FA_MODELS_DIR": "custom_models"})

        self.assertEqual(
            settings.yunet_model_path,
            Path("custom_models/face_detection_yunet_2023mar.onnx"),
        )
        self.assertEqual(
            settings.sface_model_path,
            Path("custom_models/face_recognition_sface_2021dec.onnx"),
        )


if __name__ == "__main__":
    unittest.main()
