FROM python:3

WORKDIR /usr/src/app

RUN pip install --no-cache-dir poetry

COPY . .

RUN poetry install --no-dev

RUN touch settings.py

ENTRYPOINT [ "python", "./bot.py" ]
