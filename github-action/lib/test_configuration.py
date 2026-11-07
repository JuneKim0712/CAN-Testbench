import json
from pathlib import Path
import tempfile
import unittest
from auto_discover import load_subsystem_config


class ConfigurationTests(unittest.TestCase):
    def test_manifest_overrides_and_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'custom/test'
            project.mkdir(parents=True)
            (project / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.16)')
            manifest = root / 'custom/testbench.json'
            config = dict(name='custom', target='custom/test', port='/dev/original', timeout=12)
            manifest.write_text(json.dumps(config))
            result = load_subsystem_config(directory, 'custom', str(manifest), '/dev/override')
            self.assertEqual('/dev/override', result['port'])
            for field, invalid in (('timeout', 0), ('baud', -1), ('target', '../outside'), ('name', 'bad\nname')):
                manifest.write_text(json.dumps({**config, field: invalid}))
                with self.assertRaises(ValueError):
                    load_subsystem_config(directory, 'custom', str(manifest))

    def test_corrupt_manifest_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'testbench.json'
            path.write_text('{invalid')
            with self.assertRaises(ValueError):
                load_subsystem_config(directory, 'root', str(path))
