from app.file_agent.models import PathArgs, ListArgs, WriteArgs, TransferArgs, ScreenshotArgs, DownloadArgs, EmptyArgs

FILE_TOOLS = {
    'create_folder': (PathArgs, 'Create a folder and any missing parents inside PC Downloads.'),
    'create_file': (WriteArgs, 'Create a file in PC Downloads. Generates PDF, DOC/DOCX, XLS/XLSX and PPT/PPTX by extension; supports text, CSV, Markdown, JSON, HTML and base64 binary. Never overwrite.'),
    'write_file': (WriteArgs, 'Write a file in PC Downloads, generating common document formats by extension. Overwrite requires confirmation.'),
    'append_file': (WriteArgs, 'Append UTF-8 text to a file in PC Downloads.'),
    'read_file': (PathArgs, 'Read a UTF-8 file from PC Downloads.'),
    'list_directory': (ListArgs, 'List files and folders in PC Downloads.'),
    'file_exists': (PathArgs, 'Check whether a file exists in PC Downloads.'),
    'folder_exists': (PathArgs, 'Check whether a folder exists in PC Downloads.'),
    'copy_file': (TransferArgs, 'Copy a file within PC Downloads; never overwrite.'),
    'move_file': (TransferArgs, 'Move a file within PC Downloads; never overwrite.'),
    'rename_file': (TransferArgs, 'Rename a file within PC Downloads; never overwrite.'),
    'delete_file': (PathArgs, 'Delete one file from PC Downloads. Requires confirmation.'),
    'save_screenshot': (ScreenshotArgs, 'Capture and save a browser screenshot into PC Downloads.'),
    'save_download': (DownloadArgs, 'Return the PC Downloads location of a completed website download.'),
    'list_downloads': (EmptyArgs, 'List completed downloads detected in this browser session.'),
}

def tool_definitions():
    return [{'name': 'file_' + name, 'description': description, 'parameters': schema.model_json_schema()} for name, (schema, description) in FILE_TOOLS.items()]
