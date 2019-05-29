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

import enum
import os
import random
import sqlite3
import sys
import time

import requests

# Mapping from WBW names to Slack names:
from settings import SLACK_MAPPING

TABLE_VOTES = 'vote_message'
VOTES_ID = 'id'
VOTES_CHANNEL = 'channel'
VOTES_TIMESTAMP = 'timestamp'
VOTES_CHOICE = 'choice'
WBW_EMAIL = None
WBW_PASSWORD = None
WBW_LIST = None
ONE_DAY = 60 * 60 * 24
# How many times a failing Slack API call should be retried
MAX_RETRIES = 5


class DeliveryType(enum.Enum):
    bike = 1
    delivery = 2
    eating_out = 3


EAT_REACTIONS = {
    'ramen': {
        'desc': 'Chinese',
        'instr': "https://eetvoudig.technicie.nl\n"
                 "Don't forget to order plain rice for Simone "
                 "(if she joins us)\n",
                 "Order from here: http://www.lotusnijmegen.nl/pages/acties.php"
        'type': DeliveryType.bike,
    },
    'fries': {
        'desc': 'Fest',
        'instr': "https://eetfestijn.technicie.nl",
        'type': DeliveryType.bike,
    },
    'ah': {
        'desc': 'Albert Heijn',
        'instr': "Login to ah.nl and make a list.",
        'type': DeliveryType.bike,
    },
    'sandwich': {
        'desc': 'Subway',
        'instr': "Choose your sub at: "
                 "https://www.subway.com/nl-NL/MenuNutrition/Menu/All",
        'type': DeliveryType.bike,
    },
    'pizza': {
        'desc': 'Pizza',
        'instr': "Check the menu at: "
                 "https://www.pizzeriarotana.nl\n",
                 "Destination: 6525EC Toernooiveld 212, order at ~17:30",
        'type': DeliveryType.delivery,
    },
    'dragon_face': {
        'desc': 'Wok',
        'instr': "Check the menu at: https://nijmegen.iwokandgo.nl\n"
                 "Don't forget to ask for chopsticks!\n",
                 "Destination: 6525EC Toernooiveld 212, order at ~17:30",
        'type': DeliveryType.delivery,
    },
    'knife_fork_plate': {
        'desc': 'at the Refter',
        'instr': "Everyone pays for themselves at the Refter restaurant, "
                 "and there are multiple meals to choose there.\n",
                 "Check for the daily menu: https://www.ru.nl/facilitairbedrijf/horeca/refter/menu-soep-week/",
        'type': DeliveryType.eating_out,
    },
}
HOME_REACTIONS = {
    'house': {
        'desc': "I'm eating at home",
    },
    'x': {
        'desc': "I'm not going today",
    },
}
ALL_REACTIONS = {**EAT_REACTIONS, **HOME_REACTIONS}


class Bot:
    """A minimal wrapper for the Slack API,
    this class also manages the database
    """

    def __init__(self, base_url, token, db_name):
        self.base_url = base_url
        self.token = token
        if not os.path.isfile(db_name):
            self.conn = sqlite3.connect(db_name)
            self.init_db(self.conn)
        else:
            self.conn = sqlite3.connect(db_name)

    @staticmethod
    def init_db(conn):
        """Create the required tables for the database"""
        c = conn.cursor()

        c.execute(
            f'CREATE TABLE `{TABLE_VOTES}` '
            f'(`{VOTES_ID}` INTEGER, '
            f'`{VOTES_CHANNEL}` TEXT, '
            f'`{VOTES_TIMESTAMP}` TEXT, '
            f'`{VOTES_CHOICE}` TEXT, '
            f'PRIMARY KEY(`{VOTES_ID}`));'
        )

        conn.commit()

    def chat_post_message(self, channel, text):
        """https://api.slack.com/methods/chat.post.message"""
        return self.run_method(
            'chat.postMessage',
            {'channel': channel, 'text': text}
        )

    def reactions_get(self, channel, timestamp, full=True):
        """https://api.slack.com/methods/reactions.get"""
        return self.run_method(
            'reactions.get',
            {'channel': channel, 'timestamp': timestamp, 'full': full}
        )

    def reactions_add(self, channel, timestamp, name):
        """https://api.slack.com/methods/reactions.add"""
        return self.run_method(
            'reactions.add',
            {'channel': channel, 'timestamp': timestamp, 'name': name}
        )

    def run_method(self, method, arguments: dict):
        """Base method for running slack API calls"""
        arguments['token'] = self.token
        for x in range(MAX_RETRIES):
            r = requests.post(self.base_url + method, data=arguments)
            json = r.json()
            if json['ok']:
                return json
            elif json['error'] == 'ratelimited':
                time.sleep((x + 1) * 2)
            else:
                print(json)
                raise RuntimeError("Slack api call failed")


def post_vote(bot, channel):
    """Sends a voting message to the channel `channel`"""

    message = bot.chat_post_message(
        channel,
        "<!everyone> What do you want to eat today?\n" +
        "\n".join([
            f"{info['desc']}: :{label}:"
            for label, info in ALL_REACTIONS.items()
        ])
    )

    if 'ts' not in message:
        print(message)
        raise RuntimeError("Invalid response")

    for reaction in ALL_REACTIONS:
        bot.reactions_add(message['channel'], message['ts'], reaction)

    c = bot.conn.cursor()
    c.execute(
        f'INSERT INTO {TABLE_VOTES} '
        f'({VOTES_CHANNEL}, {VOTES_TIMESTAMP}) '
        f'VALUES (?, ?)',
        (message['channel'], message['ts'],)
    )

    bot.conn.commit()


def create_wbw_session():
    """Logs in to wiebetaaltwat.nl and returns the requests session"""
    session = requests.Session()
    payload = {
        'user': {
            'email': WBW_EMAIL,
            'password': WBW_PASSWORD,
        }
    }
    response = session.post('https://api.wiebetaaltwat.nl/api/users/sign_in',
                            json=payload,
                            headers={'Accept-Version': '6'})
    return session, response


def wbw_get_lowest_member(voted):
    """Looks up the wiebetaaltwat balance and returns
    the slack name of the lowest standing balance holder

    If there is a tied lowest member, a random one is chosen.

    :param voted: the slack names of the people that should be considered
    """
    session, response = create_wbw_session()

    response = session.get(
        f'https://api.wiebetaaltwat.nl/api/lists/{WBW_LIST}/balance',
        headers={'Accept-Version': '6'},
        cookies=response.cookies
    )

    data = response.json()
    joining_members = []
    for member in reversed(data['balance']['member_totals']):
        wbw_id = member['member_total']['member']['id']
        name = member['member_total']['member']['nickname']
        balance = member['member_total']['balance_total']['fractional']
        try:
            if SLACK_MAPPING[wbw_id] in voted:
                joining_members.append({'name': name, 'balance': balance})
        except KeyError:
            print(f"User not found in slack mapping: {name} ({wbw_id})",
                  file=sys.stderr)

    lowest_balance = min(joining_members,
                         key=lambda i: i['balance'])['balance']
    return random.choice(list(filter(lambda i: i['balance'] == lowest_balance,
                                     joining_members)))['name']


def check(bot, remind=False):
    """Tallies the last sent vote and sends
    the result plus the appointed courier
    """

    c = bot.conn.cursor()
    row = c.execute(
        f'SELECT {VOTES_ID}, {VOTES_CHANNEL}, {VOTES_TIMESTAMP}, '
        f'{VOTES_CHOICE} '
        f'FROM {TABLE_VOTES} '
        f'ORDER BY {VOTES_TIMESTAMP} '
        f'DESC LIMIT 1'
    ).fetchone()

    if row is None:
        raise RuntimeError("No messages found at checking time")
    votes_id = row[0]
    channel = row[1]
    timestamp = row[2]
    choice = row[3]
    if float(timestamp) < time.time() - ONE_DAY:
        raise RuntimeError("Last vote was too long ago")

    reactions = bot.reactions_get(channel, timestamp)
    for reaction in reactions['message']['reactions']:
        if reaction['name'] == 'bomb':
            return
    filter_list = EAT_REACTIONS.keys()

    voted_slack_ids = set()
    for reaction in reactions['message']['reactions']:
        if reaction['name'] in filter_list:
            voted_slack_ids = voted_slack_ids.union(reaction['users'])

    try:
        votes = [
            {'reaction': reaction['name'], 'count': reaction['count']}
            for reaction in reactions['message']['reactions']
            if reaction['name'] in filter_list and reaction['count'] > 1
        ]

        try:
            # Get lowest member may raise a ValueError when nobody voted
            lowest = wbw_get_lowest_member(voted_slack_ids)

            # Choose a food, if the votes are tied a random food is chosen.
            # Max throws ValueError if the list is empty
            highest_vote = max(votes, key=lambda i: i['count'])['count']
            if not choice:
                # choice throws an IndexError if the list is empty
                choice = random.choice(
                    list(filter(lambda i: i['count'] == highest_vote, votes))
                )['reaction']

        except (IndexError, ValueError):
            bot.chat_post_message(channel, "No technicie this week? :(")
            return

        if not remind:
            c.execute(
                f'UPDATE {TABLE_VOTES} '
                f'SET {VOTES_CHOICE} = ? '
                f'WHERE {VOTES_ID} = ?',
                (choice, votes_id)
            )
            bot.conn.commit()

        reminder = "Reminder: " if remind else ""

        info = EAT_REACTIONS[choice]
        message = (f"<!everyone> {reminder}We're eating {info['desc']}! "
                   f"{info['instr']}")

        if info['type'] == DeliveryType.bike:
            message += f"\n{lowest} has the honour to :bike: today"
        elif info['type'] == DeliveryType.delivery:
            message += (f"\n{lowest} has the honour to pay for "
                        f"this :money_with_wings:")

        bot.chat_post_message(
            channel,
            message
        )

    except KeyError as e:
        bot.chat_post_message(
            channel, "Oh no something went wrong. "
                     "Back to the manual method, @pingiun handle this!"
        )
        raise e


def usage():
    """Prints usage"""
    print(f"Usage: {sys.argv[0]} [ post | check | remind ]", file=sys.stderr)
    sys.exit(1)


def main():
    global WBW_EMAIL
    global WBW_PASSWORD
    global WBW_LIST

    if len(sys.argv) != 2:
        usage()

    WBW_EMAIL = os.environ['DJANGO_WBW_EMAIL']
    WBW_PASSWORD = os.environ['DJANGO_WBW_PASSWORD']
    WBW_LIST = os.getenv('WBW_LIST', 'e52ec42b-3d9a-4a2e-8c40-93c3a2ec85b0')

    base_url = os.getenv('SLACK_BASE_URL', 'https://slack.com/api/')
    token = os.environ['SLACK_TOKEN']
    db_name = os.getenv('DB_NAME', 'db.sqlite3')
    channel = os.getenv('SLACK_CHANNEL', '#general')
    bot = Bot(base_url, token, db_name)

    if sys.argv[1] == 'post':
        post_vote(bot, channel)
    elif sys.argv[1] == 'check':
        check(bot)
    elif sys.argv[1] == 'remind':
        check(bot, remind=True)
    else:
        usage()


if __name__ == '__main__':
    main()
