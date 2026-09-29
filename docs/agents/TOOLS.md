# JARVIS - Tool Reference

JARVIS has access to the following workspace tools:

## Core Tools
- `list_directory(path=".")`: Lists contents of a directory.
- `read_file(path)`: Reads a file's contents.
- `create_file(path, content)`: Creates a new file.
- `update_file(path, content)`: Updates an existing file (replaces content).
- `delete_file(path)`: Deletes a file. Requires user approval.
- `run_command(command, timeout=30)`: Executes a shell command. Requires user approval.
- `inspect_runtime()`: Returns info about Python, Node, Git versions.

## Advanced Tools
- `search_files(pattern, path=".", regex=False)`: Search within files.
- `search_web(query)`: Web search for research.
- `append_file(path, content)`: Append to a file without overwriting.
- `rename_file(old_path, new_path)`: Rename/move a file.
- `copy_file(src, dest)`: Copy a file.
- `get_file_info(path)`: Get file metadata (size, modified date).
- `list_directory_tree(path=".", max_depth=3)`: Recursive tree listing.
- `diff_files(path_a, path_b)`: Get unified diff.
- `install_package(name, manager="pip")`: Install dependencies.
- `patch_file(path, find, replace, count=1)`: Find-and-replace in a file.

## Multimodal & Attachment Tools
- `analyze_image(attachment_id, prompt)`: Inspects actual image pixels and visual content using a vision-capable model. Never guess from filename.
- `get_attachment_info(attachment_id)`: Returns metadata (filename, size, MIME, dimensions) for conversation attachments.
- Note: Conversation attachments are input artifacts managed by AttachmentManager, NOT files in the workspace directory. Do not use `list_directory` or `search_files` to find conversation attachments.

