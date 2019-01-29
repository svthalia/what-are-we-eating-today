import os
import sqlite3
import sys

import pytest

import bot

from bot import Bot, main


class BotMock(Bot):
    # noinspection PyMissingConstructor
    def __init__(self):
        self.methods_ran = list()
        self.return_items = None
        self.conn = sqlite3.connect(":memory:")
        self.init_db(self.conn)

    def run_method(self, method, arguments: dict):
        self.methods_ran.append({'method': method, 'arguments': arguments})
        return super(BotMock, self).run_method(method, arguments)


pytestmark = pytest.mark.skipif(
    os.getenv('SLACK_TOKEN') is None,
    reason="will only run live tests when a slack token is present"
)


def test_main_post():
    sys.argv = ["bot.py", "post"]
    main()


def wbw_get_lowest_member_mock(*args):
    return "Jelle"


def test_main_check():
    sys.argv = ["bot.py", "check"]
    bot.wbw_get_lowest_member = wbw_get_lowest_member_mock
    main()


def test_main_remind():
    sys.argv = ["bot.py", "remind"]
    main()
