-- :name add_vote_message :affected
INSERT INTO vote_message(channel, timestamp)
VALUES (:channel, :timestamp)