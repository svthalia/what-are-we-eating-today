-- :name set_choice :affected
UPDATE vote_message
SET choice = :choice
WHERE id = :vote_id