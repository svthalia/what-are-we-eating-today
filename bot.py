#!/usr/bin/env python3

import os
import random
import sqlite3
import sys
import time

import requests

# Mapping from WBW names to Slack names:
from settings import SLACK_MAPPING

TABLE_VOTES = 'vote_message'
TABLE_PROFILES = 'profile'
VOTES_ID = 'id'
VOTES_CHANNEL = 'channel'
VOTES_TIMESTAMP = 'timestamp'
PROFILE_ID = 'id'
PROFILE_SLACK_UID = 'slack_uid'
PROFILE_SLACK_DISPLAY_NAME = 'display_name'
ONE_DAY = 60 * 60 * 24
REACTIONS = ['ramen', 'fries', 'ah', 'sandwich', 'house', 'x']
WBW_EMAIL = os.environ['WBW_EMAIL']
WBW_PASSWORD = os.environ['WBW_PASSWORD']
WBW_LIST = os.getenv('WBW_LIST', 'e52ec42b-3d9a-4a2e-8c40-93c3a2ec85b0')
# How many times a failing Slack API call should be retried
MAX_RETRIES = 5


class Bot:
    """A minimal wrapper for the Slack API, this class also manages the database"""

    def __init__(self, base_url, token, db_name):
        self.base_url = base_url
        self.token = token
        if not os.path.isfile(db_name):
            self.init_db(db_name)
        self.conn = sqlite3.connect(db_name)

    @staticmethod
    def init_db(db_name):
        """Create the required tables for the database"""
        conn = sqlite3.connect(db_name)
        c = conn.cursor()
        c.execute(f'''CREATE TABLE `{TABLE_VOTES}` 
                         (`{VOTES_ID}` INTEGER,
                         `{VOTES_CHANNEL}` TEXT,
                         `{VOTES_TIMESTAMP}` TEXT,
                         PRIMARY KEY(`{VOTES_ID}`));''')
        c.execute(f'''CREATE TABLE `{TABLE_PROFILES}`
                        (`{PROFILE_ID}` INTEGER,
                        `{PROFILE_SLACK_UID}` TEXT,
                        `{PROFILE_SLACK_DISPLAY_NAME}` TEXT,
                        PRIMARY KEY(`{PROFILE_ID}`));''')
        conn.commit()

    def chat_post_message(self, channel, text):
        """https://api.slack.com/methods/chat.post.message"""
        return self.run_method('chat.postMessage', {'channel': channel, 'text': text})

    def reactions_get(self, channel, timestamp, full=True):
        """https://api.slack.com/methods/reactions.get"""
        return self.run_method('reactions.get', {'channel': channel, 'timestamp': timestamp, 'full': full})

    def reactions_add(self, channel, timestamp, name):
        """https://api.slack.com/methods/reactions.add"""
        return self.run_method('reactions.add', {'channel': channel, 'timestamp': timestamp, 'name': name})

    def users_profile_get(self, user, include_labels=False):
        """https://api.slack.com/methods/users.profile.get"""
        return self.run_method('users.profile.get', {'user': user, 'include_labels': include_labels})

    def lookup_profile(self, user_id):
        """Wrapper with database lookup for user_profile_get because the API call has a low rate limit"""
        c = self.conn.cursor()
        name = c.execute(f'''SELECT {PROFILE_SLACK_DISPLAY_NAME} FROM {TABLE_PROFILES} WHERE {PROFILE_SLACK_UID} = ?''',
                         (user_id,)).fetchone()
        if name is not None:
            # Rows are tuples, but we only selected one column
            return name[0]

        profile = self.users_profile_get(user_id)
        c.execute(
            f'''INSERT INTO {TABLE_PROFILES} ({PROFILE_SLACK_UID}, {PROFILE_SLACK_DISPLAY_NAME}) VALUES (?, ?)''',
            (user_id, profile['profile']['real_name_normalized']))
        self.conn.commit()

        return profile['profile']['real_name_normalized']

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
    message = bot.chat_post_message(channel, "<!everyone> What do you want to eat today?\n"
                                             "Chinese: :ramen:\n"
                                             "Fest: :fries:\n"
                                             "Appie: :ah:\n"
                                             "Subway: :sandwich:\n"
                                             "I'm eating at home: :house:\n"
                                             "I'm not going today: :x:")
    if 'ts' not in message:
        print(message)
        raise RuntimeError("Invalid response")

    for reaction in REACTIONS:
        bot.reactions_add(message['channel'], message['ts'], reaction)

    c = bot.conn.cursor()
    c.execute(f'''INSERT INTO {TABLE_VOTES} ({VOTES_CHANNEL}, {VOTES_TIMESTAMP}) VALUES (?, ?)''',
              (message['channel'], message['ts'],))
    bot.conn.commit()


def multiple_max(iterable, key=None):
    """Returns the list of all values in iterable that are the highest

    :param iterable: The iterable to operate on
    :param key: The key selecting function

    :Example:

    >>> multiple_max([('a',2), ('b', 4), ('c', 3), ('d', 4)], lambda x: x[1])
    [('b', 4), ('d', 4)]
    """
    if key is None:
        key = lambda x: x

    maximum = []
    for thing in iterable:
        if len(maximum) == 0:
            maximum = [thing]
            continue
        if key(thing) > key(maximum[0]):
            maximum = [thing]
        elif key(thing) == key(maximum[0]):
            maximum.append(thing)
    return maximum


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
                            headers={'Accept-Version': '3'})
    return session, response


def wbw_get_lowest_member(voted):
    """Looks up the wiebetaaltwat balance and returns the slack name of the lowest standing balance holder

    :param voted: the slack names of the people that should be considered
    """
    session, response = create_wbw_session()
    response = session.get(f'https://api.wiebetaaltwat.nl/api/lists/{WBW_LIST}/balance',
                           headers={'Accept-Version': '3'},
                           cookies=response.cookies)
    data = response.json()
    for member in reversed(data['balance']['member_totals']):
        nickname = member['member_total']['member']['nickname']
        if SLACK_MAPPING[nickname] in voted:
            return nickname


def get_slack_names(bot, reactions):
    """Returns actual slack names based on the slack uids from a reactions list"""
    user_ids = set()
    for reaction in reactions:
        user_ids = user_ids.union(reaction['users'])

    slack_names = list()
    for user_id in user_ids:
        name = bot.lookup_profile(user_id)
        slack_names.append(name)
    return slack_names


def check(bot):
    """Tallies the last sent vote and sends the result plus the appointed courier"""
    c = bot.conn.cursor()
    row = c.execute(f'''SELECT {VOTES_CHANNEL}, {VOTES_TIMESTAMP}
                         FROM {TABLE_VOTES} ORDER BY {VOTES_TIMESTAMP} DESC LIMIT 1''').fetchone()
    if row is None:
        raise RuntimeError("No messages found at checking time")
    channel = row[0]
    timestamp = row[1]
    if float(timestamp) < time.time() - ONE_DAY:
        raise RuntimeError("Last vote was too long ago")

    reactions = bot.reactions_get(channel, timestamp)
    filter_list = ['ramen', 'fries', 'ah', 'sandwhich']

    voted = get_slack_names(bot, [reaction for reaction in reactions['message']['reactions']
                                  if reaction['name'] in filter_list])
    lowest = wbw_get_lowest_member(voted)
    try:
        votes = [(reaction['name'], reaction['count']) for reaction in reactions['message']['reactions']
                 if reaction['name'] in filter_list]
        # Filter out our own reactions
        votes = filter(lambda x: x[1] != 1, votes)
        # The multiple max allows us to make a random choice when the vote is tied
        try:
            choice = random.choice(multiple_max(votes, key=lambda x: x[1]))[0]
        except IndexError:
            bot.chat_post_message(channel, "No technicie this week? :(")
            return

        delivery = f"\n{lowest} has the honour to :bike: today"

        if choice == 'ramen':
            bot.chat_post_message(channel,
                                  "<!everyone> We're eating chinese! https://eetvoudig.technicie.nl" + delivery)
        elif choice == 'fries':
            bot.chat_post_message(channel,
                                  "<!everyone> We're eating fastfood! https://eetfestijn.technicie.nl" + delivery)
        elif choice == 'ah':
            bot.chat_post_message(channel,
                                  "<!everyone> Albert Heijn! Idk how does this work? Login to ah.nl and make a list?" + delivery)
        elif choice == 'sandwhich':
            bot.chat_post_message(channel, "<!everyone> Subway!" + delivery)

    except KeyError:
        bot.chat_post_message(channel, "Oh no something went wrong. Back to the manual method, @pingiun handle this!")


def usage():
    """Prints usage"""
    print(f"Usage: {sys.argv[0]} [ post | check ]", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        usage()

    base_url = os.getenv('SLACK_BASE_URL', 'https://slack.com/api/')
    token = os.environ['SLACK_TOKEN']
    db_name = os.getenv('DB_NAME', 'db.sqlite3')
    channel = os.getenv('SLACK_CHANNEL', '#general')
    bot = Bot(base_url, token, db_name)

    if sys.argv[1] == 'post':
        post_vote(bot, channel)
    elif sys.argv[1] == 'check':
        check(bot)
    else:
        usage()


if __name__ == '__main__':
    main()
