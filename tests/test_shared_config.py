import unittest

from pi_kiosk.shared_config import config
from pi_kiosk.steps.webapp_kiosk import S3_RELEASE_BASE_URL
from pi_kiosk.steps.project_kiosk import TYPE_OF_PROJECT_PROMPT
from pi_kiosk.steps.video_kiosk import VIDEO_NEXT_ACTION_PROMPT
from pi_kiosk.totem_registration import REGISTER_TOTEM_TOKEN, REGISTER_TOTEM_URL
from pi_kiosk.totem_status import STATUS_INTERVAL_MINUTES


class SharedConfigTests(unittest.TestCase):
    def test_pi_uses_shared_service_configuration(self):
        shared = config()

        self.assertEqual(shared["s3ReleaseBaseUrl"], S3_RELEASE_BASE_URL)
        self.assertEqual(shared["registerTotemUrl"], REGISTER_TOTEM_URL)
        self.assertEqual(shared["registerTotemToken"], REGISTER_TOTEM_TOKEN)
        self.assertEqual(shared["statusIntervalMinutes"], STATUS_INTERVAL_MINUTES)
        self.assertEqual(shared["prompts"]["projectType"], TYPE_OF_PROJECT_PROMPT)
        self.assertEqual(shared["prompts"]["videoNextAction"], VIDEO_NEXT_ACTION_PROMPT)


if __name__ == "__main__":
    unittest.main()
