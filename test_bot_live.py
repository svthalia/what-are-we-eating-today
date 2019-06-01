import os
import sys

import pytest

import bot

from bot import main


pytestmark = pytest.mark.skipif(
    os.getenv("SLACK_TOKEN") is None,
    reason="will only run live tests when a slack token is present",
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
