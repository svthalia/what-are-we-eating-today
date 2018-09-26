#!/usr/bin/env python3

import os
import random
import sqlite3
import sys
import time

import requests

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
WBW_LIST = os.getenv('WBW_LIST', 'e52ec42b-3d9a-4a2e-8c40-93c3a2ec85b0')

# Mapping from WBW names to Slack names:
SLACK_MAPPING = {
    'Thom Wiggers': 'Thom Wiggers',
    'Joren Vrancken': 'Joren Vranken',
    'Freek': 'Freek van de Ven',
    'Luko': 'Luko van der Maas',
    'Yannick': 'Yannick Hogewind',
    'Wietse K': 'Wietse Kuipers',
    'Sébastiaan': 'Sébastiaan Versteeg',
    'Joost Rijneveld': 'Joost Rijneveld',
    'Bram': 'Bram in \'t Zandt',
    'Gijs': 'Gijs Hendriksen',
    'Gerdriaan Mulder': 'Gerdriaan Mulder',
    'Tom van Bussel': 'Tom van Bussel',
    'Erik Barendsen': None,
    'Simone': None,
    'Jelle': 'Jelle Besseling',
    'Jen': 'Jen',
    'Thalia Technicie': None,
    'Nienke': 'Nienke Wessel',
    'Dion': 'Dion Scheper',
}


class Bot:
    def __init__(self, base_url, token, db_name):
        self.base_url = base_url
        self.token = token
        if not os.path.isfile(db_name):
            self.init_db(db_name)
        self.conn = sqlite3.connect(db_name)

    @staticmethod
    def init_db(db_name):
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
        return self.run_method('chat.postMessage', {'channel': channel, 'text': text})

    def reactions_get(self, channel, timestamp, full=True):
        return self.run_method('reactions.get', {'channel': channel, 'timestamp': timestamp, 'full': full})

    def reactions_add(self, channel, timestamp, name):
        return self.run_method('reactions.add', {'channel': channel, 'timestamp': timestamp, 'name': name})

    def users_profile_get(self, user, include_labels=False):
        return self.run_method('users.profile.get', {'user': user, 'include_labels': include_labels})

    def lookup_profile(self, user_id):
        c = self.conn.cursor()
        name = c.execute(f'''SELECT {PROFILE_SLACK_DISPLAY_NAME} FROM {TABLE_PROFILES} WHERE {PROFILE_SLACK_UID} = ?''',
                         (user_id,)).fetchone()
        if name is not None:
            return name

        profile = self.users_profile_get(user_id)
        try:
            c.execute(
                f'''INSERT INTO {TABLE_PROFILES} ({PROFILE_SLACK_UID}, {PROFILE_SLACK_DISPLAY_NAME}) VALUES (?, ?)''',
                (user_id, profile['profile']['real_name_normalized']))
            self.conn.commit()
        except KeyError:
            print(profile)

        return profile['profile']['real_name_normalized']

    def run_method(self, method, arguments: dict):
        arguments['token'] = self.token
        r = requests.post(self.base_url + method, data=arguments)
        return r.json()


def post_vote(bot, channel):
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
    if key is None:
        key = lambda x: x

    maximum = []
    for thing in iterable:
        if len(maximum) == 0:
            maximum = [thing]
            continue
        if key(thing) > maximum[0]:
            maximum = [thing]
        elif key(thing) == maximum[0]:
            maximum.append(thing)
    return maximum


def create_wbw_session():
    session = requests.Session()
    payload = {
        'user': {
            'email': os.environ['WBW_EMAIL'],
            'password': os.environ['WBW_PASSWORD'],
        }
    }
    response = session.post('https://api.wiebetaaltwat.nl/api/users/sign_in',
                            json=payload,
                            headers={'Accept-Version': '3'})
    return session, response


def wbw_get_lowest_member(voted):
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
    user_ids = set()
    for reaction in reactions:
        user_ids = user_ids.union(reaction['users'])

    slack_names = list()
    for user_id in user_ids:
        name = bot.lookup_profile(user_id)
        slack_names.append(name)
    return slack_names


def check(bot):
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
    voted = get_slack_names(bot, reactions['message']['reactions'])
    lowest = wbw_get_lowest_member(voted)
    try:
        votes = [(reaction['name'], reaction['count']) for reaction in reactions['message']['reactions']
                 if reaction['name'] in ['ramen', 'fries', 'ah', 'sandwhich']]
        # Filter out our own reactions
        votes = filter(lambda x: x[1] != 1, votes)
        # The multiple max allows us to make a random choice when the vote is tied
        choice = random.choice(multiple_max(votes, key=lambda x: x[1]))[0]

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
        else:
            bot.chat_post_message(channel, "No technicie this week? :(")
    except KeyError:
        bot.chat_post_message(channel, "Oh no something went wrong. Back to the manual method, @pingiun handle this!")


def usage():
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
