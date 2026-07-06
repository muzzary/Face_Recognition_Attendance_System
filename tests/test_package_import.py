import unittest

import face_attendance


class PackageImportTests(unittest.TestCase):
    def test_package_exposes_version(self) -> None:
        self.assertEqual(face_attendance.__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
