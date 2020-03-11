# What Are We Eating Today Slack Bot

This is a Slack bot that the Technicie uses to select what type of food they
are going to eat every week. The bot is deployed on AWS lambda and should run
at least at the times the bot checks (9:00, 16:00 and 16:45). The GitHub
Action automatically deploys new versions of the timer and the /addwbwuser
Slack command, some manual setup is needed for the lambda itself.

The bot can be tested locally, for this you should have pytz avaiable in your
Python installation. You can run the bot.py script with a first argument that
overrides what action should be taken.

The slash command can be used to add new users to the bot, as WBW (splitser)
users should be mapped to Slack users in the database. You can find the WBW
UUID by going to their member page on the "Balance" tab on the site.
