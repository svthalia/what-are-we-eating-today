#!/usr/bin/env python3

# what-are-we-eating-today - a slack polling bot for food
# Copyright (C) 2020 Jelle Besseling
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
from typing import Mapping, Any, Tuple, List, Optional, Sequence, Set

import boto3
import datetime
import json
import locale
import os
import pytz
import random
import sys
import time
import urllib3
import warnings
from enum import Enum, auto

TABLE_VOTES = "SlackVotes"
TABLE_MAPPING = "SlackMapping"

WBW_EMAIL = None
WBW_PASSWORD = None
WBW_LIST = None
ONE_DAY = 60 * 60 * 24
# How many times a failing Slack API call should be retried
MAX_RETRIES = 5

locale.setlocale(locale.LC_TIME, "nl_NL.UTF-8")
dynamodb = boto3.client("dynamodb")


class FoodType(Enum):
    pay_advance_bike = auto()
    pay_advance_deliver = auto()
    pay_self = auto()


EAT_REACTIONS = {
    "ramen": {
        "desc": "Chinese",
        "instr": "Don't forget to order plain rice for Simone (if she joins us)\n"
        "Order from here: http://www.lotusnijmegen.nl/pages/acties.php",
        "type": FoodType.pay_advance_bike,
    },
    "fries": {
        "desc": "Snackbar",
        "instr": "The person who pays chooses a snackbar to order from.",
        "type": FoodType.pay_advance_deliver,
    },
    "pizza": {
        "desc": "Pizza",
        "instr": "Check the menu at: "
        "https://www.pizzeriarotana.nl\n"
        "Destination: 6525EC Toernooiveld 212, order at ~17:30",
        "type": FoodType.pay_advance_deliver,
    },
    "dragon_face": {
        "desc": "Wok",
        "instr": "Check the menu at: https://nijmegen.iwokandgo.nl\n"
        "Don't forget to ask for chopsticks!\n"
        "Destination: 6525EC Toernooiveld 212, order at ~17:30",
        "type": FoodType.pay_advance_deliver,
    },
    "knife_fork_plate": {
        "desc": "<https://www.ru.nl/facilitairbedrijf/horeca/refter/menu-soep-week/|at the Refter>",
        "instr": "Everyone pays for themselves at the Refter restaurant, "
        "and there are multiple meals to choose there.\n"
        "Check for the daily menu: https://www.ru.nl/facilitairbedrijf/horeca/refter/menu-soep-week/",
        "type": FoodType.pay_self,
    },
    "hospital": {
        "desc": "<https://www.radboudumc.nl/patientenzorg"
        "/voorzieningen/eten-en-drinken/menu-van-de-dag/"
        + datetime.datetime.today().strftime("%A-%-d-%B")
        + "/|at the Hospital>",
        "instr": "Everyone pays for themselves at the hospital restaurant, "
        "and there are multiple meals to choose there.\n"
        "Check for the daily menu: https://www.radboudumc.nl/patientenzorg"
        "/voorzieningen/eten-en-drinken/menu-van-de-dag/"
        + datetime.datetime.today().strftime("%A-%-d-%B")
        + "/",
        "type": FoodType.pay_self,
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

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token
        self.client = urllib3.PoolManager()

    def chat_post_message(self, channel: str, text: str) -> Mapping[str, Any]:
        """https://api.slack.com/methods/chat.post.message"""
        return self.run_method("chat.postMessage", {"channel": channel, "text": text})

    def reactions_get(
        self, channel: str, timestamp: str, full=True
    ) -> Mapping[str, Any]:
        """https://api.slack.com/methods/reactions.get"""
        return self.run_method(
            "reactions.get", {"channel": channel, "timestamp": timestamp, "full": full}
        )

    def reactions_add(
        self, channel: str, timestamp: str, name: str
    ) -> Mapping[str, Any]:
        """https://api.slack.com/methods/reactions.add"""
        return self.run_method(
            "reactions.add", {"channel": channel, "timestamp": timestamp, "name": name}
        )

    def run_method(
        self, method: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Base method for running slack API calls"""
        for x in range(MAX_RETRIES):
            r = self.client.request(
                "POST",
                self.base_url + method,
                fields=arguments,
                headers={"Authorization": f"Bearer {self.token}",},
            )

            data = json.loads(r.data.decode("utf-8"))
            if data["ok"]:
                return data
            elif data["error"] == "ratelimited":
                time.sleep((x + 1) * 2)
            else:
                raise RuntimeError(f"Slack api call failed: {data}")
        raise RuntimeError(f"Slack api call failed: {data}")


def post_vote(bot: Bot, channel: str) -> None:
    """Sends a voting message to the channel `channel`"""

    message = bot.chat_post_message(
        channel,
        "<!everyone> What do you want to eat today?\n"
        + "\n".join(
            [f"{info['desc']}: :{label}:" for label, info in ALL_REACTIONS.items()]
        ),
    )

    if "ts" not in message:
        raise RuntimeError(f"Invalid response: {message}")

    dynamodb.put_item(
        TableName=TABLE_VOTES,
        Item={
            "ChannelId": {"S": message["channel"]},
            "Date": {"S": str(datetime.date.today())},
            "Msg": {"S": message["ts"]},
        },
    )

    for reaction in ALL_REACTIONS:
        bot.reactions_add(message["channel"], message["ts"], reaction)


def wbw_login() -> str:
    """Logs in to wiebetaaltwat.nl and returns the requests session"""
    http = urllib3.PoolManager()
    payload = {"user": {"email": WBW_EMAIL, "password": WBW_PASSWORD}}
    r = http.request(
        "POST",
        "https://api.wiebetaaltwat.nl/api/users/sign_in",
        body=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept-Version": "6",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    return r.headers["Set-Cookie"].split(";")[0]


def slack_mapping(wbw_id: str) -> str:
    item = dynamodb.get_item(TableName=TABLE_MAPPING, Key={"WbwUUID": {"S": wbw_id}})
    return item.get("Item", {}).get("SlackId", {}).get("S")


def wbw_get_lowest_member(voted: Set[str]) -> str:
    """Looks up the wiebetaaltwat balance and returns the slack name of the lowest standing balance holder

    If there is a tied lowest member, a random one is chosen.

    :param voted: the slack names of the people that should be considered
    """
    cookie = wbw_login()

    http = urllib3.PoolManager()
    r = http.request(
        "GET",
        f"https://api.wiebetaaltwat.nl/api/lists/{WBW_LIST}/balance",
        headers={
            "Accept-Version": "6",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Cookie": cookie,
        },
    )

    data = json.loads(r.data.decode("utf-8"))
    joining_members = []
    for member in reversed(data["balance"]["member_totals"]):
        wbw_id = member["member_total"]["member"]["id"]
        name = member["member_total"]["member"]["nickname"]
        balance = member["member_total"]["balance_total"]["fractional"]
        try:
            if slack_mapping(wbw_id) in voted:
                joining_members.append({"name": name, "balance": balance})
        except KeyError:
            warnings.warn(
                f"User not found in slack mapping: {name} ({wbw_id})", RuntimeWarning,
            )

    lowest_balance = min(joining_members, key=lambda i: i["balance"])["balance"]
    return random.choice(
        list(filter(lambda i: i["balance"] == lowest_balance, joining_members))
    )["name"]


def which_vote(
    channel: str, votes: Optional[Sequence[Mapping[Any, Any]]] = None
) -> Optional[str]:
    item = dynamodb.get_item(
        TableName=TABLE_VOTES,
        Key={"ChannelId": {"S": channel}, "Date": {"S": str(datetime.date.today())}},
    )
    choice = item["Item"].get("Choice", {}).get("S")
    timestamp = item["Item"]["Msg"]["S"]

    if float(timestamp) < time.time() - ONE_DAY:
        raise RuntimeError("Last vote was too long ago")

    if choice:
        return choice

    highest_vote = max(votes, key=lambda i: i["count"])["count"]
    choice = random.choice(list(filter(lambda i: i["count"] == highest_vote, votes)))[
        "reaction"
    ]
    if not choice:
        # choice throws an IndexError if the list is empty
        choice = random.choice(
            list(filter(lambda i: i["count"] == highest_vote, votes))
        )["reaction"]
    return choice


def last_poll(channel: str) -> str:
    item = dynamodb.get_item(
        TableName=TABLE_VOTES,
        Key={"ChannelId": {"S": channel}, "Date": {"S": str(datetime.date.today())}},
    )
    if "Item" not in item:
        raise Exception(f"No item found: {item}")
    timestamp = item["Item"]["Msg"]["S"]

    return timestamp


def last_poll_and_bee(channel: str) -> Tuple[str, str]:
    item = dynamodb.get_item(
        TableName=TABLE_VOTES,
        Key={"ChannelId": {"S": channel}, "Date": {"S": str(datetime.date.today())}},
    )
    if "Item" not in item:
        raise Exception(f"No item found: {item}")
    timestamp = item["Item"]["Msg"]["S"]
    bee_timestamp = item["Item"]["BeeMsg"]["S"]

    return timestamp, bee_timestamp


def check(bot: Bot, channel: str) -> None:
    """Tallies the last sent vote and sends the result plus the appointed courier."""

    timestamp = last_poll(channel)

    reactions = bot.reactions_get(channel, timestamp)
    for reaction in reactions["message"]["reactions"]:
        if reaction["name"] == "bomb":
            return

    voted_slack_ids: Set[str] = set()
    for reaction in reactions["message"]["reactions"]:
        if reaction["name"] in EAT_REACTIONS.keys():
            voted_slack_ids = voted_slack_ids.union(reaction["users"])

    votes = [
        {"reaction": reaction["name"], "count": reaction["count"]}
        for reaction in reactions["message"]["reactions"]
        if reaction["name"] in EAT_REACTIONS.keys() and reaction["count"] > 1
    ]

    choice = which_vote(channel, votes)

    info = EAT_REACTIONS[choice]
    message = f"<!everyone> We're eating {info['desc']}! " f"{info['instr']}"

    if info["type"] in {FoodType.pay_advance_deliver, FoodType.pay_advance_bike}:
        message += "\nEverybody that wants to join for dinner, adds a :bee: response to this message."

    ret = bot.chat_post_message(channel, message)
    if "ts" not in ret:
        raise RuntimeError(f"Invalid response: {message}")

    dynamodb.put_item(
        TableName=TABLE_VOTES,
        Item={
            "ChannelId": {"S": ret["channel"]},
            "Date": {"S": str(datetime.date.today())},
            "Msg": {"S": timestamp},
            "Choice": {"S": choice},
            "BeeMsg": {"S": ret["ts"]},
        },
    )


def remind(bot: Bot, channel: str) -> None:
    timestamp, bee_timestamp = last_poll_and_bee(channel)

    choice = which_vote(channel)
    info = EAT_REACTIONS[choice]
    message = f"<!everyone> Reminder: We're eating {info['desc']}! {info['instr']}"

    voted_slack_ids = set()
    reactions = bot.reactions_get(channel, bee_timestamp)
    for reaction in reactions["message"].get("reactions", []):
        if reaction["name"] == "bee":
            voted_slack_ids = voted_slack_ids.union(reaction["users"])

    if not voted_slack_ids:
        reactions = bot.reactions_get(channel, timestamp)
        for reaction in reactions["message"]["reactions"]:
            if reaction["name"] == "bomb":
                return
        for reaction in reactions["message"]["reactions"]:
            if reaction["name"] in EAT_REACTIONS.keys():
                voted_slack_ids = voted_slack_ids.union(reaction["users"])

    lowest = wbw_get_lowest_member(voted_slack_ids)

    if info["type"] == FoodType.pay_advance_bike and remind:
        message += f"\n{lowest} has the honour to :bike: today"
    elif info["type"] == FoodType.pay_advance_deliver and remind:
        message += f"\n{lowest} has the honour to pay for this :money_with_wings:"

    bot.chat_post_message(channel, message)


def setup() -> Tuple[str, str, str]:
    global WBW_EMAIL
    global WBW_PASSWORD
    global WBW_LIST

    WBW_EMAIL = os.environ["DJANGO_WBW_EMAIL"]
    WBW_PASSWORD = os.environ["DJANGO_WBW_PASSWORD"]
    WBW_LIST = os.getenv("WBW_LIST", "e52ec42b-3d9a-4a2e-8c40-93c3a2ec85b0")

    base_url = os.getenv("SLACK_BASE_URL", "https://slack.com/api/")
    token = os.environ["SLACK_TOKEN"]
    channel = os.getenv("SLACK_CHANNEL", "#general")
    return base_url, token, channel


def lambda_handler(event: Mapping[Any, Any], context) -> None:
    base_url, token, channel = setup()
    bot = Bot(base_url, token)
    if "override" in event:
        if event["override"] == "post":
            post_vote(bot, channel)
        elif event["override"] == "check":
            check(bot, channel)
        elif event["override"] == "remind":
            remind(bot, channel)
        else:
            raise Exception(f"Invalid override value: {event['override']}")
        return

    now = datetime.datetime.now(tz=pytz.timezone("Europe/Amsterdam"))
    if now.hour == 9 and now.minute == 0:
        post_vote(bot, channel)
    if now.hour == 16 and now.minute == 0:
        check(bot, channel)
    if now.hour == 16 and now.minute == 45:
        check(bot, channel)


if __name__ == "__main__":
    lambda_handler({"override": sys.argv[1]}, None)
