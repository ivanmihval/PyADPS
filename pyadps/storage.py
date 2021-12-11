import json
import os
import os.path
from glob import glob
from io import BytesIO
from pathlib import PurePath, Path
from shutil import copyfile
from typing import Generator, Iterable, Union, NamedTuple, List
from json import load

from pyadps.helpers import calculate_hashsum_hex_from_file, calculate_hashsum
from pyadps.mail import Mail, MailFilter, MailAttachmentInfo


class MessageFileTooBigError(Exception):
    pass


class FileSearchResult(NamedTuple):
    path: str
    is_exist: bool

            
class Storage:
    MESSAGES_FOLDER = 'adps_messages'
    ATTACHMENTS_FOLDERS = 'adps_attachments'
    HASHSUM_FILENAME_PART_LEN = 10
    MESSAGE_FILE_MAX_SIZE_BYTES = 4 * 1024  # 4 KB

    def __init__(self, root_dir_path: str):
        self.root_dir_path = root_dir_path

    @classmethod
    def get_free_file_path(cls, path: Union[str, PurePath], hashsum_hex: str) -> FileSearchResult:
        attempts = 10000

        if not os.path.isfile(path):
            return FileSearchResult(path, False)

        if calculate_hashsum_hex_from_file(path) == hashsum_hex:
            return FileSearchResult(path, True)

        root, ext = os.path.splitext(path)
        for i in range(attempts):
            new_path = f'{root}_{i}{ext}'
            if not os.path.isfile(new_path):
                return FileSearchResult(path, False)

            if calculate_hashsum_hex_from_file(new_path) == hashsum_hex:
                return FileSearchResult(path, True)

        raise Exception(f'Could not get free path value for {path!r}')

    def find_attachment_path(self, hashsum_hex: str) -> str:
        attachments_folder_path = PurePath(self.root_dir_path) / self.ATTACHMENTS_FOLDERS
        for attachment_path in glob(f'{attachments_folder_path}/{hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN]}*'):
            calculated_hashsum = calculate_hashsum_hex_from_file(attachment_path)
            if calculated_hashsum == hashsum_hex:
                return attachment_path

        raise FileNotFoundError()

    @classmethod
    def load_mail(cls, msg_path) -> Mail:
        size_bytes = os.path.getsize(msg_path)
        if size_bytes > cls.MESSAGE_FILE_MAX_SIZE_BYTES:
            raise MessageFileTooBigError()

        with open(msg_path) as msg_json_file:
            msg_json = load(msg_json_file)

        return Mail.Schema().load(msg_json)

    def filter_mails(self, mail_filter: MailFilter) -> Generator[Mail, None, None]:
        # todo: add progress updater for click interface
        messages_folder_path = PurePath(self.root_dir_path) / self.MESSAGES_FOLDER
        for msg_path in glob(f'{messages_folder_path}/*.json'):
            mail = self.load_mail(msg_path)
            if mail_filter.filter_func(mail):
                yield mail

    def save_mail(self, mail: Mail, mail_attachment_infos: List[MailAttachmentInfo], target_folder_path: str):
        messages_folder = PurePath(target_folder_path) / self.MESSAGES_FOLDER
        attachments_folder = PurePath(target_folder_path) / self.ATTACHMENTS_FOLDERS

        os.makedirs(messages_folder, exist_ok=True)
        os.makedirs(attachments_folder, exist_ok=True)

        mail_serialized = Mail.Schema().dump(mail)
        mail_json_bytes = json.dumps(mail_serialized, indent=4, sort_keys=True).encode()
        hashsum = calculate_hashsum(BytesIO(mail_json_bytes))

        file_search_result = self.get_free_file_path(
            messages_folder
            / f'{hashsum.hex_digest[:self.HASHSUM_FILENAME_PART_LEN]}.json',
            hashsum_hex=hashsum.hex_digest
        )

        if not file_search_result.is_exist:
            with open(file_search_result.path, 'wb') as target_message_file:
                target_message_file.write(mail_json_bytes)

        for mail_attachment_info in mail_attachment_infos:
            try:
                attachment_path = self.find_attachment_path(mail_attachment_info.hashsum_hex)
            except FileNotFoundError:
                attachment_path = mail_attachment_info.path

            target_file_search_result = self.get_free_file_path(
                attachments_folder
                / f'{mail_attachment_info.hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN]}.bin',
                hashsum_hex=mail_attachment_info.hashsum_hex
            )

            if not target_file_search_result.is_exist:
                copyfile(attachment_path, target_file_search_result.path)

    def copy_mail(self, original_json_path: str, target_folder_path: str):
        # todo: add progress updater for click interface
        messages_folder = PurePath(target_folder_path) / self.MESSAGES_FOLDER
        attachments_folder = PurePath(target_folder_path) / self.ATTACHMENTS_FOLDERS

        message_file_hashsum = calculate_hashsum_hex_from_file(original_json_path)

        file_search_result = self.get_free_file_path(
            messages_folder
            / f'{message_file_hashsum[:self.HASHSUM_FILENAME_PART_LEN]}.json',
            hashsum_hex=message_file_hashsum
        )

        if not file_search_result.is_exist:
            copyfile(original_json_path, file_search_result.path)

        mail = self.load_mail(original_json_path)

        for attachment in mail.attachments:
            attachment_path = self.find_attachment_path(attachment.hashsum_hex)
            attachment_hashsum = calculate_hashsum_hex_from_file(attachment_path)
            target_file_search_result = self.get_free_file_path(
                attachments_folder
                / f'{attachment.hashsum_hex[:self.HASHSUM_FILENAME_PART_LEN]}.bin',
                hashsum_hex=attachment_hashsum
            )

            if not target_file_search_result.is_exist:
                copyfile(attachment_path, target_file_search_result.path)

    def copy_mails(self, msg_paths: Iterable[Union[str, Path]], target_folder_path: Union[str, Path]):
        # todo: add progress updater for click interface

        messages_folder = PurePath(target_folder_path) / self.MESSAGES_FOLDER
        attachments_folder = PurePath(target_folder_path) / self.ATTACHMENTS_FOLDERS

        os.makedirs(messages_folder)
        os.makedirs(attachments_folder)

        for msg_path in msg_paths:
            self.copy_mail(msg_path, target_folder_path)

