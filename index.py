# -*- coding: utf-8 -*-
import logging
import os
import uuid

import notifier


def handler(event, context):
    logger = logging.getLogger()
    logger.info("start")

    logger.info("event: %s", event)
    logger.info("context: %s", context)

    task_id = context.request_id
    access_token = os.environ["ACCESS_TOKEN"]
    email_context = {
        "host": os.environ["EMAIL_HOST"],
        "user": os.environ["EMAIL_USER"],
        "pass": os.environ["EMAIL_PASS"],
        "receiver": os.environ["EMAIL_RECEIVER"],
    }
    orgs = [os.environ["ORG"]]

    notifier.Notifier(task_id, access_token, email_context, orgs).run()

    logger.info("exit")

    return "ok"


# just only for debug
class FCContext(dict):
    __getattr__, __setattr__ = dict.get, dict.__setitem__


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    handler(None, FCContext({"request_id": "debug-%s" % uuid.uuid1()}))



