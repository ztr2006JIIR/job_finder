import unittest
from unittest.mock import patch

from src.crawler_51job import _browser_launch_options


class BrowserConfigTests(unittest.TestCase):
    def test_cloud_uses_installed_chromium(self):
        with patch("src.crawler_51job.sys.platform", "linux"), patch(
            "src.crawler_51job.shutil.which", return_value="/usr/bin/chromium"
        ):
            options = _browser_launch_options()
        self.assertEqual(options["executable_path"], "/usr/bin/chromium")
        self.assertIn("--disable-dev-shm-usage", options["args"])

    def test_windows_keeps_playwright_browser(self):
        with patch("src.crawler_51job.sys.platform", "win32"):
            self.assertEqual(_browser_launch_options(False), {"headless": False})

    def test_linux_without_system_browser_keeps_playwright_default(self):
        with patch("src.crawler_51job.sys.platform", "linux"), patch(
            "src.crawler_51job.shutil.which", return_value=None
        ):
            self.assertEqual(_browser_launch_options(), {"headless": True})


if __name__ == "__main__":
    unittest.main()
