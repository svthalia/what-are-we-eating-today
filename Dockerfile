FROM python:3

WORKDIR /usr/src/app

RUN pip install --no-cache-dir pipenv

COPY . .

RUN pipenv install --system --deploy --ignore-pipfile

RUN touch settings.py

ENTRYPOINT [ "python", "./bot.py" ]