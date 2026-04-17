from virchow.file_processing.file_types import VirchowMimeTypes
from virchow.file_store.models import ChatFileType


def mime_type_to_chat_file_type(mime_type: str | None) -> ChatFileType:
    if mime_type is None:
        return ChatFileType.PLAIN_TEXT

    if mime_type in VirchowMimeTypes.IMAGE_MIME_TYPES:
        return ChatFileType.IMAGE

    if mime_type in VirchowMimeTypes.CSV_MIME_TYPES:
        return ChatFileType.CSV

    if mime_type in VirchowMimeTypes.DOCUMENT_MIME_TYPES:
        return ChatFileType.DOC

    return ChatFileType.PLAIN_TEXT
