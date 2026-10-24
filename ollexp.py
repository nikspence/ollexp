"""Export an installed Ollama model and its local blobs without dependencies."""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def list_models():
    """Read model names from Ollama's whitespace-separated list table."""
    result = subprocess.run(
        ['ollama', 'list'], capture_output=True, text=True,
        encoding='utf-8', errors='replace', check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or f'ollama exited with {result.returncode}')
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if rows and rows[0][0] == 'NAME':
        rows.pop(0)
    models = list(dict.fromkeys(row[0] for row in rows))
    if not models:
        raise ValueError('No installed models found. Install a model with ollama pull first.')
    return models


def remove_model(model):
    """Remove an installed model through Ollama's rm command."""
    result = subprocess.run(
        ['ollama', 'rm', model], capture_output=True, text=True,
        encoding='utf-8', errors='replace', check=False,
    )
    if result.returncode:
        message = (result.stderr.strip() or result.stdout.strip()
                   or f'ollama exited with {result.returncode}')
        raise ValueError(message)


@contextmanager
def terminal_input():
    """Enable immediate keyboard input and restore terminal settings on exit."""
    if os.name == 'nt':
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.restype = ctypes.c_void_p
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not kernel.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)):
            raise OSError('Could not read console settings.')
        if not kernel.SetConsoleMode(ctypes.c_void_p(handle), mode.value | 4):
            raise OSError('Could not enable terminal display controls.')

        def read_key():
            key = msvcrt.getwch()
            if key in ('\x00', '\xe0'):
                return {'H': 'UP', 'P': 'DOWN'}.get(msvcrt.getwch(), '')
            return key

        try:
            yield read_key
        finally:
            kernel.SetConsoleMode(ctypes.c_void_p(handle), mode.value)
    else:
        import termios
        import tty
        import select
        descriptor = sys.stdin.fileno()
        previous = termios.tcgetattr(descriptor)

        def read_key():
            key = os.read(descriptor, 1)
            if key == b'\x1b':
                sequence = b''
                while select.select([descriptor], [], [], 0.05)[0]:
                    sequence += os.read(descriptor, 1)
                    if len(sequence) >= 2:
                        break
                return {b'[A': 'UP', b'OA': 'UP', b'[B': 'DOWN', b'OB': 'DOWN'}.get(sequence, '\x1b')
            # Read a complete UTF-8 character, including non-ASCII directory names.
            length = next((n for mask, prefix, n in (
                (0xE0, 0xC0, 2), (0xF0, 0xE0, 3), (0xF8, 0xF0, 4)
            ) if key[0] & mask == prefix), 1)
            for _ in range(length - 1):
                key += os.read(descriptor, 1)
            return key.decode('utf-8', errors='replace')

        try:
            tty.setraw(descriptor)
            yield read_key
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def select_export():
    """Return a model export choice, or None if the last model was removed."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('The menu requires an interactive terminal. Use MODEL [DIRECTORY] instead.')
    models = list_models()
    selected = focus = 0
    fields = [str(Path.cwd()), safe_name(models[0])]
    confirming = False
    message = ''
    with terminal_input() as read_key:
        sys.stdout.write('\x1b[?1049h\x1b[?25l')
        try:
            while True:
                columns, rows = shutil.get_terminal_size((80, 24))
                visible = max(1, rows - (12 if confirming else 10))
                start = max(0, min(selected - visible // 2, len(models) - visible))
                lines = [
                    'Export an Ollama model',
                    'Up/Down: select model  Tab: select field  Enter: export model  R: remove model Esc/Ctrl+C: cancel/exit',
                    '',
                ]
                for index in range(start, min(start + visible, len(models))):
                    marker = '>' if index == selected else ' '
                    lines.append(f'{marker} {models[index]}')
                lines.append('')
                if confirming:
                    lines.extend([
                        '',
                        f"Remove model '{models[selected]}'?",
                        'Press Y to confirm; N, Enter, or Esc to cancel.',
                        message,
                    ])
                else:
                    for index, label in enumerate(
                            ('Base export directory', 'Model export subdirectory'), 1):
                        marker = '>' if focus == index else ' '
                        lines.append(f'{marker} {label}: {fields[index - 1]}')
                    lines.extend([
                        '',
                        'Type to edit; Backspace removes; Ctrl+U clears the active field.',
                        message,
                    ])
                # Strip control characters from external names and clip to avoid wrapping.
                display = [''.join(c for c in line if c.isprintable())[:max(1, columns - 1)]
                           for line in lines]
                sys.stdout.write('\x1b[H\x1b[2J' + '\r\n'.join(display))
                sys.stdout.flush()
                key = read_key()
                message = ''
                if key == '\x03':
                    raise KeyboardInterrupt
                if confirming:
                    if key in ('y', 'Y'):
                        model = models[selected]
                        try:
                            remove_model(model)
                        except (OSError, ValueError) as error:
                            message = f"Could not remove '{model}': {error}"
                        else:
                            models.pop(selected)
                            if not models:
                                return None
                            selected = min(selected, len(models) - 1)
                            fields[1] = safe_name(models[selected])
                            message = f"Removed '{model}'."
                        confirming = False
                    elif key in ('n', 'N', '\r', '\n', '\x1b'):
                        confirming = False
                    continue
                if key == '\x1b':
                    raise KeyboardInterrupt
                if key == '\t':
                    focus = (focus + 1) % 3
                elif key in ('UP', 'DOWN') and focus == 0:
                    selected = (selected + (1 if key == 'DOWN' else -1)) % len(models)
                    fields[1] = safe_name(models[selected])
                elif key.lower() == 'r' and focus == 0:
                    confirming = True
                elif key in ('\r', '\n'):
                    subdirectory = Path(fields[1])
                    if not fields[0].strip() or not fields[1].strip():
                        message = 'Both directory fields are required.'
                    elif subdirectory.is_absolute() or subdirectory.drive or '..' in subdirectory.parts:
                        message = 'Use a relative subdirectory within the base export directory.'
                    else:
                        return models[selected], Path(fields[0]).expanduser() / subdirectory
                elif focus:
                    if key in ('\x08', '\x7f'):
                        fields[focus - 1] = fields[focus - 1][:-1]
                    elif key == '\x15':
                        fields[focus - 1] = ''
                    elif len(key) == 1 and key.isprintable():
                        fields[focus - 1] += key
        finally:
            sys.stdout.write('\x1b[?25h\x1b[?1049l')
            sys.stdout.flush()


def safe_name(model):
    """Make model tags and namespaces safe as Windows and Unix filenames."""
    name = re.sub(r'[^\w.\-]', '_', model).strip('. ')
    if not name:
        name = 'model'
    if name.split('.')[0].upper() in {
        'CON', 'PRN', 'AUX', 'NUL',
        *(f'COM{i}' for i in range(1, 10)),
        *(f'LPT{i}' for i in range(1, 10)),
    }:
        name = '_' + name
    return name


def blob_references(modelfile):
    """Find file directives, ignoring comments and triple-quoted text bodies."""
    references = []
    in_text = False
    for index, line in enumerate(modelfile.splitlines(keepends=True)):
        if in_text:
            if line.count('"""') % 2:
                in_text = False
            continue
        if line.lstrip().startswith('#'):
            continue
        match = re.match(r'^(\s*)(FROM|ADAPTER|DRAFT)\s+(.+?)\s*$', line, re.I)
        if match:
            value = match.group(3)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
                value = value[1:-1]
            source = Path(value).expanduser()
            if not source.is_file():
                raise ValueError(
                    f'{match.group(2)} does not reference a readable local file: {value}'
                )
            references.append((index, match.group(1), match.group(2), source.resolve()))
        elif line.count('"""') % 2:
            in_text = True
    if not any(directive.upper() == 'FROM' for _, _, directive, _ in references):
        raise ValueError('Ollama returned no FROM file directive.')
    return references


def export_model(model, destination=None):
    result = subprocess.run(
        ['ollama', 'show', model, '--modelfile'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or f'ollama exited with {result.returncode}')

    references = blob_references(result.stdout)
    sources = list(dict.fromkeys(source for _, _, _, source in references))
    name = safe_name(model)
    destination = Path(destination) if destination is not None else Path.cwd() / name
    destination = destination.expanduser().resolve()
    filenames = {
        source: f'{name}_{index}.gguf' if len(sources) > 1 else f'{name}.gguf'
        for index, source in enumerate(sources, 1)
    }
    lines = result.stdout.splitlines(keepends=True)
    for index, indent, directive, source in references:
        lines[index] = f'{indent}{directive} ./{filenames[source]}\n'

    destination.mkdir(parents=True, exist_ok=True)
    targets = [destination / filename for filename in filenames.values()]
    targets.append(destination / 'Modelfile')
    for target in targets:
        if target.exists():
            raise FileExistsError(f'Refusing to overwrite existing file: {target}')

    created = []
    try:
        for source, filename in filenames.items():
            target = destination / filename
            with target.open('xb') as output:
                created.append(target)
                with source.open('rb') as blob:
                    shutil.copyfileobj(blob, output, length=1024 * 1024)
        with (destination / 'Modelfile').open('x', encoding='utf-8', newline='\n') as output:
            created.append(destination / 'Modelfile')
            output.write(''.join(lines))
    except BaseException:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise
    return destination, len(sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', help='Installed Ollama model name, including its tag')
    parser.add_argument(
        'directory', nargs='?',
        help='Export directory (default: current directory / sanitized model name)',
    )
    try:
        if len(sys.argv) == 1:
            selection = select_export()
            if selection is None:
                print('No installed models remain.')
                return 0
            model, directory = selection
        else:
            args = parser.parse_args()
            model, directory = args.model, args.directory
        destination, count = export_model(model, directory)
    except KeyboardInterrupt:
        print('Export cancelled.', file=sys.stderr)
        return 130
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    print(f'Exported {count} blob(s) and Modelfile to {destination}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
