# ollexp

`ollexp.py` exports an installed Ollama model to a self-contained directory. It copies the local files referenced by the model's `Modelfile` and rewrites those references so the exported model can be recreated with Ollama.

## Requirements

- Python 3.8 or newer.
- Ollama installed with `ollama` available on `PATH`.
- The model already installed in Ollama.
- Local read access to the files referenced by the model's `FROM` and `ADAPTER` directives.
- Enough free disk space for copies of those files.

`ollexp.py` uses only the Python standard library. No third-party packages are required.

## Usage

### Interactive menu

Run the script without arguments:

```powershell
python ollexp.py
```

The menu lists installed models from `ollama list`.

| Key | Action |
| --- | --- |
| Up / Down | Select a model when the model list is focused |
| R | Remove the selected model when the model list is focused |
| Tab | Cycle through the model list, base export directory, and model export subdirectory |
| Typing | Append to the active directory field |
| Backspace | Delete the previous character |
| Ctrl+U | Clear the active directory field |
| Enter | Export and exit |
| Esc / Ctrl+C | Cancel |

The base directory defaults to the current working directory. The subdirectory defaults to a filesystem-safe form of the selected model name and is updated when the model selection changes.

Press `R` while the model list is focused to remove the selected model. The menu asks for confirmation: press `Y` to run `ollama rm MODEL`, or press `N`, Enter, or Esc to cancel. If the last installed model is removed, the menu exits.

The subdirectory must be relative and cannot contain `..`. The base directory may be relative or absolute. The menu requires an interactive terminal; otherwise, use the positional command.

### Positional command

```powershell
python ollexp.py MODEL [DIRECTORY]
```

- `MODEL` is an installed Ollama model name, including an optional tag.
- `DIRECTORY` is optional. By default, the script creates a directory under the current directory using a sanitized model name.

Export to the default directory:

```powershell
python ollexp.py llama3.2:latest
```

This creates:

```text
llama3.2_latest/
    Modelfile
    llama3.2_latest.gguf
```

Export to a specific directory:

```powershell
python ollexp.py llama3.2:latest .\exports\llama
```

Quote paths containing spaces:

```powershell
python ollexp.py llama3.2:latest "C:\Model Exports\llama"
```

Show command-line help:

```powershell
python ollexp.py --help
```

## Export behavior

The script runs:

```text
ollama show MODEL --modelfile
```

It finds local files referenced by `FROM` and `ADAPTER` directives, copies each unique source file into the destination directory, and rewrites those directives to relative paths such as:

```text
FROM ./llama3.2_latest.gguf
```

Additional Modelfile content, including comments and template text, is preserved.

When one unique source file is referenced, it is named `<model>.gguf`. When multiple unique files are referenced, they are numbered as `<model>_1.gguf`, `<model>_2.gguf`, and so on. Repeated references to the same source share one exported copy.

For generated directory and file names, characters that are unsafe in filenames, such as `/` and `:`, are replaced with underscores. Windows reserved names are prefixed with an underscore. Explicit destination directories are not sanitized; they are expanded and resolved relative to the current directory.

## Safety and limitations

- Removing a model with `R` is permanent and uses the `ollama rm` command.
- The destination directory and missing parent directories are created automatically.
- Existing files that conflict with the export names are not overwritten. The export stops with an error instead.
- Files created by a failed export attempt are removed; pre-existing files and the destination directory are left in place.
- Copied files are named with a `.gguf` extension. Their contents are not converted or checked to verify that they are valid GGUF files.
- Only files referenced by `FROM` and `ADAPTER` are exported. Other layers in Ollama's internal model storage are not included.
- Referenced blob paths must be available locally. Exporting from a remote Ollama server will fail if those paths do not exist on the machine running this script.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Export completed successfully |
| `1` | An Ollama, file, or validation error occurred |
| `130` | The export was cancelled with Ctrl+C or Esc |

## Tests

Run the unit tests from this directory:

```powershell
python -m unittest -v
```
