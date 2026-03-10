"""笔记解析器工厂"""
from scripts.note_parser import NoteParser
from scripts.html_note_parser import HtmlNoteParser
from scripts.lite_note_parser import LiteNoteParser
from scripts.collaboration_note_parser import CollaborationNoteParser
from scripts.note import Note


class NoteParserFactory:
    """笔记解析器工厂"""

    @staticmethod
    def create_parser(note_type: str) -> NoteParser:
        """
        根据笔记类型创建对应的解析器
        :param note_type: 笔记类型
        :return: 笔记解析器实例
        """
        if Note.is_collaboration_note(note_type):
            return CollaborationNoteParser()
        elif note_type == 'lite/markdown':
            return LiteNoteParser()
        else:
            return HtmlNoteParser()
