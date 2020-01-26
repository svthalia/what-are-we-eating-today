#!/usr/bin/env python3

# what-are-we-eating-today - a slack polling bot for food
# Copyright (C) 2019 Jelle Besseling
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import argparse
import enum
import locale
import os
import random
import sys
import time

from datetime import datetime, timedelta

import pugsql
import requests

# Mapping from WBW names to Slack names:
from settings import SLACK_MAPPING

MAX_SLACK_API_RETRIES = 5
SLACK_BASE_URL = "https://slack.com/api/"

locale.setlocale(locale.LC_TIME, "nl_NL.UTF-8")


class DeliveryType(enum.Enum):
    BIKE = 1
    DELIVERY = 2
    EATING_OUT = 3


EAT_REACTIONS = {
    "ramen": {
        "desc": "Chinese",
        "instr": "Everybody that wants to join for dinner, adds a :bee: response to this message.\n"
        "Don't forget to order plain rice for Simone (if she joins us)\n"
        "Order from here: http://www.lotusnijmegen.nl/pages/acties.php",
        "type": DeliveryType.BIKE,
    },
    "fries": {
        "desc": "Snackbar",
        "instr": "The person who pays chooses a snackbar to order from.\n"
        "Everybody that wants to join for dinner, adds a :bee: response to this message.",
        "type": DeliveryType.DELIVERY,
    },
    "pizza": {
        "desc": "Pizza",
        "instr": "Check the menu at: "
        "https://www.pizzeriarotana.nl\n"
        "Destination: 6525EC Toernooiveld 212, order at ~17:30",
        "type": DeliveryType.DELIVERY,
    },
    "dragon_face": {
        "desc": "Wok",
        "instr": "Check the menu at: https://nijmegen.iwokandgo.nl\n"
        "Don't forget to ask for chopsticks!\n"
        "Destination: 6525EC Toernooiveld 212, order at ~17:30",
        "type": DeliveryType.DELIVERY,
    },
    "knife_fork_plate": {
        "desc": "<https://www.ru.nl/facilitairbedrijf/horeca/refter/menu-soep-week/|at the Refter>",
        "instr": "Everyone pays for themselves at the Refter restaurant, "
        "and there are multiple meals to choose there.\n"
        "Check for the daily menu: https://www.ru.nl/facilitairbedrijf/horeca/refter/menu-soep-week/",
        "type": DeliveryType.EATING_OUT,
    },
    "hospital": {
        "desc": "<https://www.radboudumc.nl/patientenzorg"
        "/voorzieningen/eten-en-drinken/menu-van-de-dag/"
        + datetime.today().strftime("%A-%-d-%B")
        + "/|at the Hospital>",
        "instr": "Everyone pays for themselves at the hospital restaurant, "
        "and there are multiple meals to choose there.\n"
        "Check for the daily menu: https://www.radboudumc.nl/patientenzorg"
        "/voorzieningen/eten-en-drinken/menu-van-de-dag/"
        + datetime.today().strftime("%A-%-d-%B")
        + "/",
        "type": DeliveryType.EATING_OUT,
    },
}

HOME_REACTIONS = {
    "house": {"desc": "I'm eating at home"},
    "x": {"desc": "I'm not going today"},
}

ALL_REACTIONS = {**EAT_REACTIONS, **HOME_REACTIONS}


class Bot:
    """A minimal wrapper for the Slack API,
    this class also manages the database
    """

    def __init__(self, token, db_name):
        self.token = token
        self.queries = pugsql.module("queries/")
        self.queries.connect(f"sqlite:///{db_name}")
        if not os.path.isfile(db_name):
            self.queries.init_db()

    def chat_post_message(self, channel, text):
        """https://api.slack.com/methods/chat.post.message"""
        return self.run_method("chat.postMessage", {"channel": channel, "text": text})

    def reactions_get(self, channel, timestamp, full=True):
        """https://api.slack.com/methods/reactions.get"""
        return self.run_method(
            "reactions.get", {"channel": channel, "timestamp": timestamp, "full": full}
        )

    def reactions_add(self, channel, timestamp, name):
        """https://api.slack.com/methods/reactions.add"""
        return self.run_method(
            "reactions.add", {"channel": channel, "timestamp": timestamp, "name": name}
        )

    def run_method(self, method, data: dict):
        """Base method for running slack API calls"""
        data["token"] = self.token
        for x in range(MAX_SLACK_API_RETRIES):
            r = requests.post(SLACK_BASE_URL + method, data=arguments)
            json = r.json()
            if json["ok"]:
                return json
            elif json["error"] == "ratelimited":
                time.sleep((x + 1) * 2)
            else:
                raise RuntimeError("Slack api call failed")


def post_vote(bot, channel):
    """Sends a voting message to the channel `channel`."""

    message = bot.chat_post_message(
        channel,
        "<!everyone> What do you want to eat today?\n"
        + "\n".join(
            [f"{info['desc']}: :{label}:" for label, info in ALL_REACTIONS.items()]
        ),
    )

    if "ts" not in message:
        print(message)
        raise RuntimeError("Invalid response")

    for reaction in ALL_REACTIONS:
        bot.reactions_add(message["channel"], message["ts"], reaction)

    bot.queries.add_vote_message(channel=message["channel"], timestamp=message["ts"])


def create_wbw_session():
    """Logs in to WieBetaaltWat and returns the requests session."""
    session = requests.Session()
    payload = {
        "user": {"email": arguments.wbw_username, "password": arguments.wbw_password}
    }
    response = session.post(
        "https://api.wiebetaaltwat.nl/api/users/sign_in",
        json=payload,
        headers={"Accept-Version": "6"},
    )
    return session, response


def wbw_get_lowest_member(voted):
    """Looks up the WieBetaaltWat balance and returns
    the slack name of the lowest standing balance holder.

    If there is a tied lowest member, a random one is chosen.

    :param voted: the slack names of the people that should be considered.
    """
    session, response = create_wbw_session()

    response = session.get(
        f"https://api.wiebetaaltwat.nl/api/lists/{arguments.wbw_list}/balance",
        headers={"Accept-Version": "6"},
        cookies=response.cookies,
    )

    data = response.json()
    joining_members = []
    for member in reversed(data["balance"]["member_totals"]):
        wbw_id = member["member_total"]["member"]["id"]
        name = member["member_total"]["member"]["nickname"]
        balance = member["member_total"]["balance_total"]["fractional"]
        try:
            if SLACK_MAPPING[wbw_id] in voted:
                joining_members.append({"name": name, "balance": balance})
        except KeyError:
            print(
                f"User not found in slack mapping: {name} ({wbw_id})", file=sys.stderr
            )

    lowest_balance = min(joining_members, key=lambda i: i["balance"])["balance"]
    return random.choice(
        list(filter(lambda i: i["balance"] == lowest_balance, joining_members))
    )["name"]


def check(bot, remind=False):
    """Tallies the last sent vote and sends
    the result plus the appointed courier.
    """

    vote_message = bot.queries.latest_vote_message()

    if vote_message is None:
        raise RuntimeError("No messages found at checking time")
    vote_id = vote_message["id"]
    channel = vote_message["channel"]
    timestamp = vote_message["timestamp"]
    choice = vote_message["choice"]
    if datetime.fromtimestamp(float(timestamp)) < datetime.now() - timedelta(days=1):
        raise RuntimeError("Last vote was too long ago")

    reactions = bot.reactions_get(channel, timestamp)
    for reaction in reactions["message"]["reactions"]:
        if reaction["name"] == "bomb":
            return
    filter_list = EAT_REACTIONS.keys()

    voted_slack_ids = set()
    for reaction in reactions["message"]["reactions"]:
        if reaction["name"] in filter_list:
            voted_slack_ids = voted_slack_ids.union(reaction["users"])

    try:
        votes = [
            {"reaction": reaction["name"], "count": reaction["count"]}
            for reaction in reactions["message"]["reactions"]
            if reaction["name"] in filter_list and reaction["count"] > 1
        ]

        try:
            # Get lowest member may raise a ValueError when nobody voted
            lowest = wbw_get_lowest_member(voted_slack_ids)

            # Choose a food, if the votes are tied a random food is chosen.
            # Max throws ValueError if the list is empty
            highest_vote = max(votes, key=lambda i: i["count"])["count"]
            if not choice:
                # choice throws an IndexError if the list is empty
                choice = random.choice(
                    list(filter(lambda i: i["count"] == highest_vote, votes))
                )["reaction"]

        except (IndexError, ValueError):
            bot.chat_post_message(channel, "No technicie this week? :(")
            return

        if not remind:
            bot.queries.set_choice(vote_id=vote_id, choice=choice)

        reminder = "Reminder: " if remind else ""

        info = EAT_REACTIONS[choice]
        message = f"<!everyone> {reminder}We're eating {info['desc']}! {info['instr']}"

        if info["type"] == DeliveryType.BIKE:
            message += f"\n{lowest} has the honour to :bike: today"
        elif info["type"] == DeliveryType.DELIVERY:
            message += f"\n{lowest} has the honour to pay for this :money_with_wings:"

        bot.chat_post_message(channel, message)

    except KeyError as e:
        bot.chat_post_message(
            channel,
            "Oh no something went wrong. Back to the manual method, @pingiun handle this!",
        )
        raise e


if __name__ == "__main__":
    argument_parser = argparse.ArgumentParser("What Are We Eating Today Slack Bot")

    argument_parser.add_argument(
        "--wbw-email", help="The username of the WieBetaaltWat user.", required=True
    )
    argument_parser.add_argument(
        "--wbw-password", help="The password of the WieBetaaltWat user.", required=True
    )
    argument_parser.add_argument(
        "--wbw-list", help="The WieBetaaltWat list.", required=True
    )

    argument_parser.add_argument(
        "--slack-token", help="The Slack API Token.", required=True
    )
    argument_parser.add_argument(
        "--slack-channel",
        help="The Slack channel to post the messages in.",
        required=True,
    )

    argument_parser.add_argument(
        "--database-path",
        help="Path to the SQLite3 database file (default: db.sqlite3).",
        default="db.sqlite3",
    )

    argument_parser.add_argument(
        "action", choices=("post", "check", "remind"), help="What action to perform."
    )

    arguments = argument_parser.parse_args()

    slack_api_bot = Bot(arguments.slack_token, arguments.database_path)
    if arguments.action == "post":
        post_vote(slack_api_bot, arguments.channel)
    elif arguments.action == "check":
        check(slack_api_bot)
    elif arguments.action == "remind":
        check(slack_api_bot, remind=True)
