import time

import pytest
import pugsql

import bot
from bot import post_vote, check, Bot, ALL_REACTIONS


class BotMock(Bot):
    # noinspection PyMissingConstructor
    def __init__(self):
        self.methods_ran = list()
        self.return_items = None
        self.queries = pugsql.module("queries/")
        self.queries.connect(f"sqlite:///:memory:")
        self.queries.init_db()

    def run_method(self, method, arguments: dict):
        self.methods_ran.append({"method": method, "arguments": arguments})
        try:
            return self.return_items.pop()
        except IndexError:
            # Return None when the list is empty
            return None


def test_post_vote_sends_a_message_to_slack():
    mockbot = BotMock()
    mockbot.return_items = [{"ts": 1, "channel": "#general"}]
    post_vote(mockbot, "#general")
    assert (
        len([x for x in mockbot.methods_ran if x["method"] == "chat.postMessage"]) == 1
    )


def test_post_vote_adds_reactions_for_every_option():
    mockbot = BotMock()
    mockbot.return_items = [{"ts": 1, "channel": "#general"}]
    post_vote(mockbot, "#general")
    posted_reactions = list()
    for method in mockbot.methods_ran:
        if method["method"] == "chat.postMessage":
            continue
        assert method["arguments"]["name"] in ALL_REACTIONS.keys()
        posted_reactions.append(method["arguments"]["name"])

    assert set(ALL_REACTIONS.keys()) == set(posted_reactions)


def test_post_vote_adds_message_to_database():
    mockbot = BotMock()
    mockbot.return_items = [{"ts": 1, "channel": "#general"}]
    post_vote(mockbot, "#general")
    assert mockbot.queries.count()["count()"] == 1


def wbw_get_lowest_member_mock(*args):
    return "Jelle"


def test_check_throws_error_when_last_post_was_long_ago():
    mockbot = BotMock()
    mockbot.queries.add_vote_message(channel="#general", timestamp=1)

    with pytest.raises(RuntimeError, match="long ago"):
        check(mockbot)


def test_check_quits_early_when_bomb_is_reacted():
    mockbot = BotMock()
    mockbot.queries.add_vote_message(channel="#general", timestamp=time.time())

    mockbot.return_items = [{"message": {"reactions": [{"name": "bomb"}]}}]

    check(mockbot)
    assert len(mockbot.methods_ran) == 1
    assert mockbot.methods_ran[0]["method"] == "reactions.get"


def test_check_sends_sad_message_when_nobody_voted():
    bot.wbw_get_lowest_member = wbw_get_lowest_member_mock

    mockbot = BotMock()
    mockbot.queries.add_vote_message(channel="#general", timestamp=time.time())

    mockbot.return_items = [
        {
            "message": {
                "reactions": [
                    {"name": name, "users": ["self"], "count": 1}
                    for name in ALL_REACTIONS.keys()
                ]
            }
        }
    ]

    check(mockbot)
    for method in mockbot.methods_ran:
        if method["method"] == "chat.postMessage":
            assert method["arguments"]["text"] == "No technicie this week? :("


def test_choose_existing_choice_in_reminder():
    mockbot = BotMock()
    mockbot.queries.add_vote_message(channel="#general", timestamp=time.time())
    mockbot.queries.set_choice(
        vote_id=mockbot.queries.latest_vote_message()["id"], choice="ah"
    )

    mockbot.return_items = [
        {
            "message": {
                "reactions": [
                    {"name": name, "users": ["self"], "count": 2}
                    for name in ALL_REACTIONS.keys()
                ]
            }
        }
    ]

    check(mockbot, remind=True)

    for method in mockbot.methods_ran:
        if method["method"] == "chat.postMessage":
            assert (
                method["arguments"]["text"]
                == "<!everyone> Reminder: We're eating Albert Heijn! "
                "Login to ah.nl and make a list.\nJelle has the honour to "
                ":bike: today"
            )


def test_check_updates_table_with_choice():
    mockbot = BotMock()
    mockbot.queries.add_vote_message(channel="#general", timestamp=time.time())

    mockbot.return_items = [
        {
            "message": {
                "reactions": [
                    {"name": name, "users": ["self"], "count": 2}
                    for name in ALL_REACTIONS.keys()
                ]
            }
        }
    ]

    check(mockbot, remind=False)

    row = mockbot.queries.latest_vote_message()
    assert row["choice"] is not None
