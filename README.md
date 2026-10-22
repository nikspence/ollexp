# ollexp

Export a locally installed Ollama model to a directory containing its blobs and an updated `Modelfile`.

## Requirements

- Python 3.8 or newer.
- Ollama installed and available as `ollama` on your PATH.
- The model already available in Ollama, with its blob files accessible on the machine running this script.
- Enough free disk space for a copy of the model's referenced blobs.

No third-party Python packages are needed. 

## Usage

Run without arguments to open the interactive export menu:

```sh
python ollexp.py
```

Use Up/Down to select a model from `ollama list`. Tab cycles between the model
list, base export directory, and model export subdirectory. The base defaults to
the current directory; selecting a model resets the subdirectory to its sanitized
name. Type to append to a directory field, Backspace to delete, or Ctrl+U to clear
it. Enter exports to the base directory joined with the subdirectory and exits.
Esc or Ctrl+C cancels. The menu requires an interactive terminal.

```sh
python ollexp.py MODEL [DIRECTORY]
```

`MODEL` is the Ollama model name, including an optional tag. `DIRECTORY` is optional; by default, the script creates a directory in the current working directory using a filesystem-safe version of the model name.

Export to the default directory:

```sh
python ollexp.py llama3.2:latest
```

This creates:

```text
llama3.2_latest/
    Modelfile
    llama3.2_latest.gguf
```

Export to a specified directory:

```sh
python ollexp.py llama3.2:latest ./exports/llama
```

Quote paths containing spaces:

```sh
python ollexp.py llama3.2:latest "C:\Model Exports\llama"
```

Show command-line help:

```sh
python ollexp.py --help
```

## Export behavior

The script runs `ollama show MODEL --modelfile`, finds local files referenced by `FROM` and `ADAPTER` directives, and copies each unique file into the destination. It rewrites those directives to paths relative to the exported `Modelfile`, such as:

```text
FROM ./llama3.2_latest.gguf
```

When multiple unique blobs are referenced, filenames receive numbers starting at 1, for example `llama3.2_latest_1.gguf` and `llama3.2_latest_2.gguf`. Repeated references to the same file share one exported copy. Comments and triple-quoted template text are preserved.

Characters such as `/` and `:` in model names become underscores in directory and blob filenames. Explicit destination paths are used as provided.

The destination and missing parent directories are created automatically. Existing files with conflicting export names are never overwritten. If copying fails, files created by that export attempt are removed. Errors are printed to standard error and return exit code 1.

Blobs are copied byte for byte and given a `.gguf` extension; the script does not convert their contents or validate that they are GGUF files. It exports files referenced by the Modelfile, rather than every layer in Ollama's model storage. Blob paths must be accessible locally, including when Ollama is configured to use a remote server.
