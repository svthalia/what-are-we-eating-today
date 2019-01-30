# What Are We Eating Today Slack Bot [![Build Status](https://travis-ci.org/thaliawww/what-are-we-eating-today.svg?branch=master)](https://travis-ci.org/thaliawww/what-are-we-eating-today)

## Developing
This project uses [poetry](https://github.com/sdispater/poetry) for dependency management and test running. You should follow the [installation instructions](https://github.com/sdispater/poetry#installation) for poetry first. Then you can install all the dependencies with this command:

```bash
poetry install
```

The tests can be run with poetry:

```bash
poetry run pytest --cov=bot --cov-report=term-missing .
```

To be able to run the online tests, you need to set up the following environment variables:
- SLACK_TOKEN=a slack api token
- SLACK_CHANNEL=@yourname
- DJANGO_WBW_PASSWORD=the password for your wiebetaaltwat user
- DJANGO_WBW_EMAIL=your wiebetaaltwat user
