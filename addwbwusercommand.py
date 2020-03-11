import boto3
import json
import logging
import os
import re

from urllib.parse import parse_qs
from base64 import b64decode

dynamodb = boto3.client("dynamodb")

expected_token = os.environ["SLACK_TOKEN"]

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def respond(res):
    return {
        "statusCode": "200",
        "body": json.dumps(res),
        "headers": {"Content-Type": "application/json",},
    }


def lambda_handler(event, context):
    params = parse_qs(b64decode(event["body"]).decode("utf-8"))
    print(params)
    token = params["token"][0]
    if token != expected_token:
        logger.error("Request token (%s) does not match expected", token)
        return {"statusCode": "400"}

    if "text" not in params:
        return respond("Usage: /addwbwuser <uuid> <user> [comment]")
    text = params["text"][0]

    try:
        uuid, user, *comment = text.split(" ")
        if not re.match(
            r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", uuid
        ):
            return respond("First argument must be a uuid")
        if m := re.match(r"<@([A-Z0-9]+)\|.*>", user):
            if m.group(1).startswith("U"):
                user = m.group(1)
                comment = " ".join(comment)
                dynamodb.put_item(
                    TableName="SlackMapping",
                    Item={
                        "WbwUUID": {"S": uuid},
                        "Name": {"S": comment},
                        "SlackId": {"S": user},
                    },
                )
                return respond(
                    f"Saved uuid {uuid}, userid {user} in the database with comment {comment}"
                )
        return respond(f"User should be an @ mention of a slack user")
    except ValueError:
        return respond("Usage: /addwbwuser <uuid> <user> [comment]")
