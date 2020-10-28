FROM python:3.9

WORKDIR /usr/src/app

RUN apt-get update && \
    apt-get install -y locales && \
    echo "nl_NL.UTF-8 UTF-8" >> /etc/locale.gen && \
    locale-gen && \
    pip install --no-cache-dir poetry

COPY . .

RUN poetry install --no-dev

RUN touch settings.py

ENTRYPOINT [ "poetry", "run", "./bot.py" ]
