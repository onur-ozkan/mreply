import tempfile
import importlib.util
import importlib.machinery
from email import policy
from email.parser import BytesParser
from pathlib import Path
import unittest
from unittest import mock


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
        self.assertIn("MIME-Version: 1.0", template)
        self.assertIn("Content-Type: text/plain; charset=UTF-8", template)
        self.assertIn("Content-Transfer-Encoding: 8bit", template)
        expected_quote = (
            "On Thu, 09 Apr 2026 12:34:56 +0300\n"
            "Onur Example <onur@example.com> wrote:\n\n"
            "> Hello world\n"
            "> second line"
        )
        self.assertIn(expected_quote, template)

    def test_build_reply_template_omits_empty_threading_headers(self):
        message = self.parse_message(self.load_example_bytes("no_message_id.eml"))

        template, subject, message_id = mreply.build_reply_template(message, local_addresses=set())

        self.assertEqual(subject, "Re: Test")
        self.assertEqual(message_id, "")
        self.assertNotIn("In-Reply-To:", template)
        self.assertNotIn("References:", template)
        self.assertIn("Onur <onur@example.com> wrote:\n\n> Body", template)

    def test_extract_plain_text_body_skips_attachments(self):
        message = self.parse_message(self.load_example_bytes("multipart_message.eml"))

        body = mreply.extract_plain_text_body(message)

        self.assertEqual(body.strip(), "visible text")

    def test_extract_plain_text_body_prefers_utf8_when_charset_is_missing(self):
        message = self.parse_message(self.load_example_bytes("utf8_no_charset.eml"))

        body = mreply.extract_plain_text_body(message)
        template, _, _ = mreply.build_reply_template(message, local_addresses={"bob@example.com"})

        self.assertEqual(body.strip(), "Onur Özkan")
        self.assertIn("MIME-Version: 1.0", template)
        self.assertIn("Content-Type: text/plain; charset=UTF-8", template)
        self.assertIn("Content-Transfer-Encoding: 8bit", template)
        self.assertIn("> Onur Özkan", template)

    def test_load_message_from_source_supports_single_message_mbox(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "single_message.mbox"
            source_path.write_bytes(self.load_example_bytes("single_message.mbox"))

            message = mreply.load_message_from_source(str(source_path))

        self.assertEqual(message["Subject"], "Patch 1")
        self.assertEqual(message["From"], "Onur Example <onur@example.com>")

    def test_load_messages_from_source_supports_multi_message_mbox(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "thread.mbox"
            source_path.write_bytes(self.load_example_bytes("multi_message.mbox"))

            messages = mreply.load_messages_from_source(str(source_path))

        self.assertEqual([message["Subject"] for message in messages], ["Patch 1", "Patch 2"])

    def test_load_message_from_source_rejects_multi_message_mbox(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "thread.mbox"
            source_path.write_bytes(self.load_example_bytes("multi_message.mbox"))

            with self.assertRaises(mreply.MreplyError):
                mreply.load_message_from_source(str(source_path))

    def test_main_replies_to_multi_message_source_and_sends_after_edit_loop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "thread.mbox"
            source_path.write_bytes(self.load_example_bytes("multi_message.mbox"))
            edited_drafts = []
            send_commands = []

            def fake_run(command, check=False, capture_output=False, text=False):
                if command[0] == "editor":
                    draft_path = Path(command[-1])
                    edited_drafts.append(draft_path)
                    draft_path.write_text(
                        draft_path.read_text(encoding="utf-8") + "\nReply body\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    return mock.Mock(returncode=0)

                if command[:2] == ["git", "send-email"]:
                    send_commands.append(command)
                    return mock.Mock(returncode=0)

                raise AssertionError(f"unexpected command: {command}")

            with mock.patch.object(
                mreply,
                "build_editor_command",
                side_effect=lambda _editor, _line_length, target_path: ["editor", str(target_path)],
            ):
                with mock.patch.object(mreply, "get_local_addresses", return_value=set()):
                    with mock.patch.object(mreply.subprocess, "run", side_effect=fake_run):
                        with mock.patch.dict("os.environ", {"HOME": temp_dir}, clear=False):
                            exit_code = mreply.main(["--reply", str(source_path)])
                            self.assertTrue(all(path.exists() for path in edited_drafts))

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(edited_drafts), 2)
        self.assertEqual(len(send_commands), 1)
        self.assertEqual(send_commands[0][2:], [str(path) for path in edited_drafts])


if __name__ == "__main__":
    unittest.main()
