# -*- coding: utf-8 -*-
import logging
import os

import notifier


def handler(event, context):
    logger = logging.getLogger()
    logger.info("start")

    logger.info("event: %s", event)
    logger.info("context: %s", context)

    notifier.Notifier(os.environ["ACCESS_TOKEN"], {
        "host": os.environ["EMAIL_HOST"],
        "user": os.environ["EMAIL_USER"],
        "pass": os.environ["EMAIL_PASS"],
        "receiver": os.environ["EMAIL_RECEIVER"],
    }, [os.environ["ORG"]]).run()

    logger.info("exit")

    return "ok"


if __name__ == '__main__':
    # for debug
    logging.basicConfig(level=logging.INFO)
    handler(None, None)


