"""FSM States for the bot."""
from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    keywords = State()


class ChapterStates(StatesGroup):
    waiting_chapter_number = State()


class BroadcastStates(StatesGroup):
    waiting_content = State()
    confirm = State()
