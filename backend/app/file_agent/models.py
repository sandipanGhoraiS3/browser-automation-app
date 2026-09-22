from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid')

class PathArgs(Arguments):
    path: str = Field(min_length=1, max_length=1000, description='Path relative to the user PC Downloads folder.')

class ListArgs(Arguments):
    path: str = '.'

class WriteArgs(PathArgs):
    content: str = Field(max_length=20_000_000, description='Document content. Common Office/PDF formats are generated from UTF-8 text; use base64 for arbitrary binary files.')
    encoding: Literal['utf-8', 'base64'] = 'utf-8'
    overwrite: bool = False

class TransferArgs(Arguments):
    source: str
    destination: str

class ScreenshotArgs(PathArgs):
    mode: Literal['viewport', 'full_page'] = 'viewport'

class DownloadArgs(PathArgs):
    download_id: str = Field(description='ID returned by detected browser downloads or file_list_downloads.')

class EmptyArgs(Arguments):
    pass
