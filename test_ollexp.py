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

    def menu(self, keys, models=None, output=None, real_export=False):
        iterator = iter(keys)
        output = output or io.StringIO()
        models = ['first:tag', 'org/second:tag'] if models is None else models
        with patch('ollexp.sys.stdin.isatty', return_value=True), \
             patch('ollexp.sys.stdout', output), \
             patch.object(output, 'isatty', return_value=True), \
             patch('ollexp.list_models', return_value=models), \
             patch('ollexp.export_details', return_value=(2048, 4096)), \
             patch('ollexp.export_model', wraps=ollexp.export_model if real_export else None,
                   **({} if real_export else {'return_value': (Path('export'), 1)})) as export, \
             patch('ollexp.terminal_input', return_value=contextlib.nullcontext(lambda: next(iterator))):
            self.export = export
            return ollexp.select_export()

    def test_selection_and_defaults(self):
        self.menu(['DOWN', '\r', '\r', 'q'])
        self.export.assert_called_once_with('org/second:tag', Path.cwd() / 'org_second_tag')

    def test_edit_and_validate_destination(self):
        keys = ['\t', '\x15', *'exports', '\t', '\x15', *'../bad', '\r',
                '\x15', *'customx', '\x08', '\r', 'Y', 'q']
        self.menu(keys)
        self.export.assert_called_once_with('first:tag', Path('exports/custom').resolve())

    def test_export_confirmation_keys_and_details(self):
        for key in ('y', 'Y', '\r', '\n'):
            with self.subTest(key=key):
                output = io.StringIO()
                self.menu(['\r', 'r', 'DOWN', key, 'q'], output=output)
                self.export.assert_called_once_with('first:tag', Path.cwd() / 'first_tag')
                screen = output.getvalue()
                self.assertIn('Model: first:tag', screen)
                self.assertIn('2.00 KiB (2,048 bytes)', screen)
                self.assertIn(str(Path.cwd() / 'first_tag'), screen)
                self.assertIn('Free disk space at destination: 4.00 KiB (4,096 bytes)', screen)

    def test_cancel_export_returns_to_menu(self):
        for key in ('n', 'N', '\x1b'):
            with self.subTest(key=key):
                output = io.StringIO()
                self.menu(['\r', key, 'DOWN', '\r', 'Y', 'q'], output=output)
                self.export.assert_called_once_with('org/second:tag', Path.cwd() / 'org_second_tag')
                self.assertIn('Export cancelled.', output.getvalue())

    def test_export_details_error_returns_to_menu(self):
        output = io.StringIO()
        with patch('ollexp.Path.resolve', side_effect=OSError('drive unavailable')):
            with self.assertRaises(KeyboardInterrupt):
                self.menu(['\r', '\x1b'], output=output)
        self.assertIn('Could not prepare export: drive unavailable', output.getvalue())

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
            self.menu(['R', 'Y', '\r', '\r', 'q'], output=output)
        remove.assert_called_once_with('first:tag')
        self.assertIn("Remove model 'first:tag'?", output.getvalue())
        self.export.assert_called_once_with('org/second:tag', Path.cwd() / 'org_second_tag')

    def test_remove_model_confirmation_cancelled(self):
        with patch('ollexp.remove_model') as remove:
            self.menu(['r', 'n', '\r', '\r', 'q'])
        remove.assert_not_called()
        self.export.assert_called_once_with('first:tag', Path.cwd() / 'first_tag')

    def test_remove_failure_returns_to_menu(self):
        output = io.StringIO()
        with patch('ollexp.remove_model', side_effect=ValueError('not found')):
            with self.assertRaises(KeyboardInterrupt):
                self.menu(['R', 'Y', '\x1b'], output=output)
        self.assertIn("Could not remove 'first:tag': not found", output.getvalue())

    def test_remove_last_model_returns_message(self):
        with patch('ollexp.remove_model'):
            self.assertEqual(self.menu(['R', 'Y'], models=['only:tag']),
                             'No installed models remain.')

    def test_r_in_directory_field_edits_text(self):
        with patch('ollexp.remove_model') as remove:
            with self.assertRaises(KeyboardInterrupt):
                self.menu(['\t', '\x15', 'r', '\x1b'])
        remove.assert_not_called()
    def test_main_exits_cleanly_after_removing_last_model(self):
        output = io.StringIO()
        with patch('ollexp.sys.argv', ['ollexp.py']), \
             patch('ollexp.select_export', return_value='No installed models remain.'), \
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
            output = io.StringIO()
            keys = ['\t', '\x15', *str(target.parent), '\t', '\x15', *'custom',
                    '\r', 'Y', 'q']
            with patch('ollexp.subprocess.run', return_value=result):
                self.assertIsNone(self.menu(keys, output=output, real_export=True))
            self.assertIn('Exported 1 blob(s) and Modelfile to', output.getvalue())
            self.assertEqual((target / 'first_tag.gguf').read_bytes(), b'model data')
            self.assertEqual((target / 'Modelfile').read_text(), 'FROM ./first_tag.gguf\n')

    def test_repeated_exports_preserve_selection_and_directories(self):
        keys = ['DOWN', '\t', '\x15', *'exports', '\t', '\x15', *'custom',
                '\r', 'Y', '\r', 'Y', 'Q']
        self.menu(keys)
        expected = ('org/second:tag', (Path('exports') / 'custom').resolve())
        self.assertEqual([call.args for call in self.export.call_args_list], [expected, expected])

    def test_export_error_returns_to_list(self):
        output = io.StringIO()
        with patch('ollexp.read_modelfile', side_effect=OSError('disk unavailable')):
            self.assertIsNone(self.menu(['\r', 'Y', 'Q'], output=output, real_export=True))
        self.assertIn("Could not export 'first:tag': disk unavailable", output.getvalue())

    def test_q_quits_list_without_export(self):
        for key in ('q', 'Q'):
            self.assertIsNone(self.menu([key]))
            self.export.assert_not_called()

    def test_q_in_directory_field_edits_text(self):
        self.menu(['\t', '\x15', *'qQ', '\r', 'Y', 'q'])
        self.export.assert_called_once_with('first:tag', (Path('qQ') / 'first_tag').resolve())

    def test_main_quit_is_successful(self):
        output = io.StringIO()
        with patch('ollexp.sys.argv', ['ollexp.py']), \
             patch('ollexp.select_export', return_value=None), \
             patch('ollexp.export_model') as export, \
             contextlib.redirect_stdout(output):
            self.assertEqual(ollexp.main(), 0)
        export.assert_not_called()
        self.assertEqual(output.getvalue(), '')

    def test_positional_export_still_runs_once(self):
        with patch('ollexp.sys.argv', ['ollexp.py', 'first:tag', 'exports']), \
             patch('ollexp.select_export') as menu, \
             patch('ollexp.export_model', return_value=(Path('exports'), 1)) as export, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ollexp.main(), 0)
        menu.assert_not_called()
        export.assert_called_once_with('first:tag', 'exports')


class DraftExportTests(unittest.TestCase):
    def test_confirmation_size_and_free_space_for_missing_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            model = root / 'model'
            draft = root / 'draft'
            model.write_bytes(b'model data')
            draft.write_bytes(b'draft data')
            modelfile = f'FROM "{model}"\nDRAFT "{draft}"\nADAPTER "{draft}"\n'
            target = root / 'new' / 'export'
            with patch('ollexp.read_modelfile', return_value=modelfile), \
                 patch('ollexp.shutil.disk_usage') as usage:
                usage.return_value.free = 123456
                self.assertEqual(ollexp.export_details('example', target), (20, 123456))
            usage.assert_called_once_with(root)
            self.assertFalse(target.parent.exists())

    def test_confirmation_uses_existing_destination_disk_space(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            model = root / 'model'
            model.write_bytes(b'model data')
            with patch('ollexp.read_modelfile', return_value=f'FROM "{model}"\n'), \
                 patch('ollexp.shutil.disk_usage') as usage:
                usage.return_value.free = 9876
                self.assertEqual(ollexp.export_details('example', root), (10, 9876))
                usage.assert_called_once_with(root)
                with self.assertRaisesRegex(ValueError, 'not a directory'):
                    ollexp.export_details('example', model / 'export')

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
