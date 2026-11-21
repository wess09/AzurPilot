import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from module.api import background_service as service


class BackgroundMigrationTest(unittest.TestCase):
    def test_concurrent_legacy_retries_share_entry_and_normal_uploads_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch.object(service, 'LIBRARY_DIR', directory), patch.object(service, 'INDEX_FILE', directory / 'index.json'):
                def upload(_):
                    return service.gallery_add_bytes(b'picture', 'old.png', 'image/png', legacy=True)
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    entries = list(pool.map(upload, range(20)))
                self.assertEqual(len({item['id'] for item in entries}), 1)
                self.assertEqual(len(service.gallery_list()), 1)
                self.assertEqual((directory / entries[0]['id']).read_bytes(), b'picture')
                ordinary = [service.gallery_add_bytes(b'picture', 'old.png', 'image/png') for _ in range(2)]
                self.assertNotEqual(ordinary[0]['id'], ordinary[1]['id'])
                self.assertEqual(len(service.gallery_list()), 3)

    def test_failed_index_commit_can_be_retried_without_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch.object(service, 'LIBRARY_DIR', directory), patch.object(service, 'INDEX_FILE', directory / 'index.json'):
                with patch.object(service, '_write_index', side_effect=OSError('disk full')):
                    with self.assertRaises(OSError):
                        service.gallery_add_bytes(b'picture', 'old.png', 'image/png', legacy=True)
                service.gallery_add_bytes(b'picture', 'old.png', 'image/png', legacy=True)
                self.assertEqual(len(service.gallery_list()), 1)


if __name__ == '__main__':
    unittest.main()
