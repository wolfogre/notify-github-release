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

    task_id = "%s/%s" % (context.request_id, uuid.uuid1())
    access_token = os.environ["ACCESS_TOKEN"]
    email_context = {
        "host": os.environ["EMAIL_HOST"],
        "user": os.environ["EMAIL_USER"],
        "pass": os.environ["EMAIL_PASS"],
        "receiver": os.environ["EMAIL_RECEIVER"],
    }
    orgs = [os.environ["ORG"]]

    tmp_dir = "/tmp"
    if b"tmp_dir" in event:
        tmp_dir = event["tmp_dir"]

    notifier.Notifier(task_id, access_token, email_context, orgs, tmp_dir).run()

    logger.info("exit")

    return "ok"


# just only for debug
class FCContext(dict):
    __getattr__, __setattr__ = dict.get, dict.__setitem__


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    handler({b"tmp_dir": "./tmp"}, FCContext({"request_id": "debug-%s" % uuid.uuid1()}))




