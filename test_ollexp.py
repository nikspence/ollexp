import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ollexp


class MenuTests(unittest.TestCase):
    def test_list_models(self):
        result = subprocess.CompletedProcess([], 0,
            'NAME   ID   SIZE   MODIFIED\norg/first:latest abc 2 GB today\nsecond:tag def 3 GB today\n', '')
        with patch('ollexp.subprocess.run', return_value=result) as run:
            self.assertEqual(ollexp.list_models(), ['org/first:latest', 'second:tag'])
        self.assertEqual(run.call_args.args[0], ['ollama', 'list'])

    def test_empty_and_failed_list(self):
        for result in (subprocess.CompletedProcess([], 0, 'NAME ID SIZE MODIFIED\n', ''),
                       subprocess.CompletedProcess([], 1, '', 'server unavailable')):
            with patch('ollexp.subprocess.run', return_value=result):
                with self.assertRaises(ValueError):
                    ollexp.list_models()

    def menu(self, keys, models=None, output=None):
        iterator = iter(keys)
        output = output or io.StringIO()
        models = ['first:tag', 'org/second:tag'] if models is None else models
        with patch('ollexp.sys.stdin.isatty', return_value=True), \
             patch('ollexp.sys.stdout', output), \
             patch.object(output, 'isatty', return_value=True), \
             patch('ollexp.list_models', return_value=models), \
             patch('ollexp.terminal_input', return_value=contextlib.nullcontext(lambda: next(iterator))):
            return ollexp.select_export()

    def test_selection_and_defaults(self):
        self.assertEqual(self.menu(['DOWN', '\r']),
                         ('org/second:tag', Path.cwd() / 'org_second_tag'))

    def test_edit_and_validate_destination(self):
        keys = ['\t', '\x15', *'exports', '\t', '\x15', *'../bad', '\r',
                '\x15', *'customx', '\x08', '\r']
        self.assertEqual(self.menu(keys), ('first:tag', Path('exports/custom')))

    def test_cancel(self):
        with self.assertRaises(KeyboardInterrupt):
            self.menu(['\x1b'])

    def test_remove_model_command(self):
        result = subprocess.CompletedProcess([], 0, "deleted 'first:tag'\n", '')
        with patch('ollexp.subprocess.run', return_value=result) as run:
            ollexp.remove_model('first:tag')
        self.assertEqual(run.call_args.args[0], ['ollama', 'rm', 'first:tag'])

    def test_remove_model_command_error(self):
        result = subprocess.CompletedProcess([], 1, '', 'model not found')
        with patch('ollexp.subprocess.run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'model not found'):
                ollexp.remove_model('missing:tag')

    def test_remove_selected_model_after_confirmation(self):
        output = io.StringIO()
        with patch('ollexp.remove_model') as remove:
            choice = self.menu(['R', 'Y', '\r'], output=output)
        remove.assert_called_once_with('first:tag')
        self.assertIn("Remove model 'first:tag'?", output.getvalue())
        self.assertEqual(choice,
                         ('org/second:tag', Path.cwd() / 'org_second_tag'))

    def test_remove_model_confirmation_cancelled(self):
        with patch('ollexp.remove_model') as remove:
            choice = self.menu(['r', 'n', '\r'])
        remove.assert_not_called()
        self.assertEqual(choice, ('first:tag', Path.cwd() / 'first_tag'))

    def test_remove_failure_returns_to_menu(self):
        output = io.StringIO()
        with patch('ollexp.remove_model', side_effect=ValueError('not found')):
            with self.assertRaises(KeyboardInterrupt):
                self.menu(['R', 'Y', '\x1b'], output=output)
        self.assertIn("Could not remove 'first:tag': not found", output.getvalue())

    def test_remove_last_model_returns_none(self):
        with patch('ollexp.remove_model'):
            self.assertIsNone(self.menu(['R', 'Y'], models=['only:tag']))

    def test_r_in_directory_field_edits_text(self):
        with patch('ollexp.remove_model') as remove:
            with self.assertRaises(KeyboardInterrupt):
                self.menu(['\t', '\x15', 'r', '\x1b'])
        remove.assert_not_called()
    def test_main_exits_cleanly_after_removing_last_model(self):
        output = io.StringIO()
        with patch('ollexp.sys.argv', ['ollexp.py']), \
             patch('ollexp.select_export', return_value=None), \
             contextlib.redirect_stdout(output):
            self.assertEqual(ollexp.main(), 0)
        self.assertIn('No installed models remain.', output.getvalue())
    def test_menu_exports_using_existing_flow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blob = root / 'blob'
            blob.write_bytes(b'model data')
            result = subprocess.CompletedProcess([], 0, f'FROM "{blob}"\n', '')
            target = root / 'exports' / 'custom'
            with patch('ollexp.sys.argv', ['ollexp.py']), \
                 patch('ollexp.select_export', return_value=('first:tag', target)), \
                 patch('ollexp.subprocess.run', return_value=result), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ollexp.main(), 0)
            self.assertEqual((target / 'first_tag.gguf').read_bytes(), b'model data')
            self.assertEqual((target / 'Modelfile').read_text(), 'FROM ./first_tag.gguf\n')


class DraftExportTests(unittest.TestCase):
    def test_export_copies_draft_and_preserves_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / 'model blob'
            draft = root / 'draft blob'
            model.write_bytes(b'model data')
            draft.write_bytes(b'draft data')
            extra = '# DRAFT ignored\nTEMPLATE """\nDRAFT template text\n"""\n'
            modelfile = f'FROM "{model}"\n  draft "{draft}"\nADAPTER "{draft}"\n' + extra
            result = subprocess.CompletedProcess([], 0, modelfile, '')
            target = root / 'export'
            with patch('ollexp.subprocess.run', return_value=result):
                destination, count = ollexp.export_model('example:tag', target)
            self.assertEqual((destination, count), (target.resolve(), 2))
            self.assertEqual((target / 'example_tag_1.gguf').read_bytes(), b'model data')
            self.assertEqual((target / 'example_tag_2.gguf').read_bytes(), b'draft data')
            self.assertEqual((target / 'Modelfile').read_text(),
                             'FROM ./example_tag_1.gguf\n'
                             '  draft ./example_tag_2.gguf\n'
                             'ADAPTER ./example_tag_2.gguf\n' + extra)

    def test_missing_draft_fails_before_creating_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / 'model'
            model.write_bytes(b'model data')
            result = subprocess.CompletedProcess(
                [], 0, f'FROM "{model}"\nDRAFT "{root / "missing"}"\n', '')
            target = root / 'export'
            with patch('ollexp.subprocess.run', return_value=result):
                with self.assertRaisesRegex(ValueError, 'DRAFT does not reference'):
                    ollexp.export_model('example', target)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
