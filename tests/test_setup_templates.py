"""Check setup examples against existing readers using temporary fake data."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from support import TEMP_ROOT
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from goodmorning.calendar.secretary_calendar import load_config_file, main as calendar_main
from goodmorning.records.state import read_profile_timezone, scan_projects
from goodmorning.weather import parse_profile
from goodmorning.runtime_files import profile_fields


class SetupTemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def test_profile_empty_and_confirmed_values(self):
        template = (ROOT / "templates/profile.template.md").read_text()
        profile = self.directory / "profile.md"
        profile.write_text(template)
        self.assertEqual(parse_profile(profile), ("", ""))
        self.assertEqual(read_profile_timezone(str(self.directory)), "")
        profile.write_text(template.replace('city: ""', 'city: "London, GB"')
                           .replace('region: ""', 'region: "global"')
                           .replace('timezone: ""', 'timezone: "Europe/London"'))
        self.assertEqual(parse_profile(profile), ("London, GB", "global"))
        self.assertEqual(read_profile_timezone(str(self.directory)), "Europe/London")

    def test_reply_language_preserves_explicit_choices(self):
        template = (ROOT / "templates/profile.template.md").read_text()
        for language in ("English", "简体中文", "繁體中文", "English and French", "follow my message language"):
            (self.directory / "profile.md").write_text(template.replace('secretary_language: ""', 'secretary_language: "' + language + '"'))
            self.assertEqual(profile_fields(self.directory)["secretary_language"], language)

    def test_secretary_name_is_optional_short_and_safe(self):
        from goodmorning.runtime_files import normalize_secretary_name
        from goodmorning.setup_check import profile_status
        template = (ROOT / "templates/profile.template.md").read_text()
        self.assertEqual(normalize_secretary_name("Aria"), "Aria")
        self.assertEqual(normalize_secretary_name("小秘"), "小秘")
        self.assertEqual(normalize_secretary_name(""), "")
        for bad in ("x" * 31, "***", "a\nb"):
            with self.assertRaises(ValueError):
                normalize_secretary_name(bad)
        (self.directory / "profile.md").write_text(template.replace('secretary_name: ""', 'secretary_name: "Aria"'))
        self.assertEqual(profile_fields(self.directory)["secretary_name"], "Aria")
        # Optional: missing name keeps an otherwise ready profile valid.
        (self.directory / "profile.md").write_text('secretary_language: English\ncity: London, GB\ntimezone: Europe/London\nnews_country: GB\n')
        status = profile_status(self.directory, profile_fields(self.directory))
        self.assertTrue(status["profile_ready"])
        self.assertIsNone(status["secretary_name"])

    def test_project_last_update_is_readable(self):
        projects = self.directory / "projects"
        projects.mkdir()
        template = (ROOT / "templates/project.template.md").read_text()
        (projects / "example.md").write_text(
            template.replace('last_update: ""', 'last_update: 2026-10-09'))
        self.assertEqual(scan_projects(str(self.directory)),
                         {"example": {"last_update": "2026-10-09"}})

    def test_optional_role_and_expertise_fields_are_empty_then_readable(self):
        template = (ROOT / "templates/profile.template.md").read_text()
        path = self.directory / "profile.md"
        path.write_text(template)
        fields = profile_fields(self.directory)
        self.assertEqual(fields["occupations"], "")
        self.assertEqual(fields["expertise_fields"], "")
        path.write_text(template.replace('occupations: ""', 'occupations: "student; teaching assistant"')
                       .replace('expertise_fields: ""', 'expertise_fields: "statistics; scientific computing"'))
        fields = profile_fields(self.directory)
        self.assertEqual(fields["occupations"], "student; teaching assistant")
        self.assertEqual(fields["expertise_fields"], "statistics; scientific computing")

    def test_profile_remains_readable_without_optional_context(self):
        (self.directory / "profile.md").write_text('city: "London, GB"\nregion: "global"\ntimezone: "UTC"\n')
        fields = profile_fields(self.directory)
        self.assertNotIn("occupations", fields)
        self.assertNotIn("expertise_fields", fields)
        self.assertEqual(read_profile_timezone(str(self.directory)), "UTC")

    def test_calendar_config_initializes_empty_store(self):
        document = (ROOT / "config.example.md").read_text()
        config = json.loads(re.search(r"```json\n(.*?)\n```", document, re.S).group(1))
        config.update(secretary_dir=str(self.directory), timezone="UTC")
        path = self.directory / "calendar.config.json"
        path.write_text(json.dumps(config))
        self.assertEqual(load_config_file(str(path)), config)
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(output):
            result = calendar_main(["--config", str(path), "--init", "--json"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["custom"], 0)
        self.assertTrue((self.directory / "calendar.sqlite").is_file())


if __name__ == "__main__":
    unittest.main()
