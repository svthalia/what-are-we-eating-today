-- :name init_db :affected
CREATE TABLE vote_message(
  id INTEGER,
  channel TEXT,
  timestamp TEXT,
  choice TEXT,
  PRIMARY KEY (id)
)