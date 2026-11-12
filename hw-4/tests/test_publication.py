import tempfile
import unittest
from pathlib import Path

from kazoo.exceptions import BadVersionError

from coordination.publication import PublicationStore


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = PublicationStore(Path(self.directory.name) / "sink.sqlite")

    def test_unfenced_old_leader_overwrites_pointer(self):
        self.store.create_run("run", fencing=False)
        self.store.claim("run", 1)
        self.store.claim("run", 2)
        self.store.publish("run", {"epoch": 2, "coordinator": "backup"})
        result = self.store.publish("run", {"epoch": 1, "coordinator": "old"})

        self.assertEqual(result["pointer_version"], 2)
        self.assertEqual(result["pointer"]["coordinator"], "old")

    def test_fenced_old_leader_is_rejected_without_partial_write(self):
        self.store.create_run("run", fencing=True)
        self.store.claim("run", 1)
        self.store.claim("run", 2)
        before = self.store.publish("run", {"epoch": 2, "coordinator": "backup"})

        with self.assertRaises(BadVersionError):
            self.store.publish("run", {"epoch": 1, "coordinator": "old"})

        self.assertEqual(self.store.inspect("run"), before)

    def test_epoch_remains_after_receiver_restart(self):
        self.store.create_run("run", fencing=True)
        self.store.claim("run", 2)
        recovered = PublicationStore(self.store.path)

        with self.assertRaises(BadVersionError):
            recovered.claim("run", 1)

        self.assertEqual(recovered.inspect("run")["epoch"], 2)


if __name__ == "__main__":
    unittest.main()
