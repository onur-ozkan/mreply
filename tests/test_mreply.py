import tempfile
import importlib.util
import importlib.machinery
from email import policy
from email.parser import BytesParser
from pathlib import Path
import unittest


EXAMPLES_DIR = Path(__file__).with_name("examples")
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "mreply"
LOADER = importlib.machinery.SourceFileLoader("mreply", str(SCRIPT_PATH))
SPEC = importlib.util.spec_from_loader("mreply", LOADER)
mreply = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(mreply)


class MreplyTests(unittest.TestCase):
    def load_example_bytes(self, name):
        return (EXAMPLES_DIR / name).read_bytes()

    def parse_message(self, data):
        return BytesParser(policy=policy.default).parsebytes(data)

    def test_build_reply_template_sanitizes_and_deduplicates_headers(self):
        message = self.parse_message(self.load_example_bytes("raw_message.eml"))

        template, subject, message_id = mreply.build_reply_template(
            message,
            local_addresses={"bob@example.com"},
        )

        self.assertEqual(subject, "Re: Patch 1")
        self.assertEqual(message_id, "<message-1@example.com>")
        self.assertIn("To: Onur Example <onur@example.com>", template)
        self.assertIn("Cc: Carol Example <carol@example.com>", template)
        self.assertNotIn("bob@example.com>, Bob Example", template)
        self.assertIn("In-Reply-To: <message-1@example.com>", template)
        self.assertIn("References: <thread-root@example.com> <message-1@example.com>", template)
        self.assertIn("> Hello world\n> second line", template)

    def test_build_reply_template_omits_empty_threading_headers(self):
        message = self.parse_message(self.load_example_bytes("no_message_id.eml"))

        template, subject, message_id = mreply.build_reply_template(message, local_addresses=set())

        self.assertEqual(subject, "Re: Test")
        self.assertEqual(message_id, "")
        self.assertNotIn("In-Reply-To:", template)
        self.assertNotIn("References:", template)

    def test_extract_plain_text_body_skips_attachments(self):
        message = self.parse_message(self.load_example_bytes("multipart_message.eml"))

        body = mreply.extract_plain_text_body(message)

        self.assertEqual(body.strip(), "visible text")

    def test_load_message_from_source_supports_single_message_mbox(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "single_message.mbox"
            source_path.write_bytes(self.load_example_bytes("single_message.mbox"))

            message = mreply.load_message_from_source(str(source_path))

        self.assertEqual(message["Subject"], "Patch 1")
        self.assertEqual(message["From"], "Onur Example <onur@example.com>")

    def test_load_message_from_source_rejects_multi_message_mbox(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "thread.mbox"
            source_path.write_bytes(self.load_example_bytes("multi_message.mbox"))

            with self.assertRaises(mreply.MreplyError):
                mreply.load_message_from_source(str(source_path))


if __name__ == "__main__":
    unittest.main()