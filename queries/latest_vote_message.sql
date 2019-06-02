-- :name latest_vote_message :one
SELECT id, channel, timestamp, choice
FROM vote_message
ORDER BY timestamp DESC
LIMIT 1