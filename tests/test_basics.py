import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import igcommon
import post


class RedactTests(unittest.TestCase):
    def test_token_never_appears_in_output(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("IG_ACCESS_TOKEN=abc123secret\nIG_USER_ID=42\n")
        try:
            env = igcommon.load_env(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(env["IG_USER_ID"], "42")
        self.assertNotIn("abc123secret", igcommon.redact("failed with abc123secret in url"))

    def test_set_env_value_replaces_in_place(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("IG_ACCESS_TOKEN=old\nIG_USER_ID=42\n")
        try:
            igcommon.set_env_value("IG_ACCESS_TOKEN", "new", f.name)
            text = open(f.name).read()
            mode = os.stat(f.name).st_mode & 0o777
        finally:
            os.unlink(f.name)
        self.assertIn("IG_ACCESS_TOKEN=new", text)
        self.assertIn("IG_USER_ID=42", text)
        self.assertEqual(mode, 0o600)


class QueueTests(unittest.TestCase):
    QUEUE = [{"name": "One", "status": "approved"}, {"name": "Two", "status": "draft"},
             {"name": "Dup", "status": "approved"}, {"name": "dup", "status": "approved"}]

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(post.find_queue_entry(self.QUEUE, "one")["name"], "One")

    def test_unknown_name_exits(self):
        with self.assertRaises(SystemExit):
            post.find_queue_entry(self.QUEUE, "missing")

    def test_duplicate_names_exit(self):
        with self.assertRaises(SystemExit):
            post.find_queue_entry(self.QUEUE, "dup")


if __name__ == "__main__":
    unittest.main()
