# -*- coding: utf-8 -*-
import logging
import os

from github import Github
from github.GithubException import UnknownObjectException


def handler(event, context):
    logger = logging.getLogger()
    logger.info("start")
    if "ACCESS_TOKEN" not in os.environ:
        raise RuntimeError("can not read ACCESS_TOKEN")
    g = Github(os.environ["ACCESS_TOKEN"])
    repos = g.get_user().get_starred()
    for repo in repos:
        try:
            latest_release = repo.get_latest_release()
        except UnknownObjectException:
            latest_release = None
        if latest_release is not None:
            logger.info("%s %s", repo.full_name,
                        [latest_release.id, latest_release.title, latest_release.tag_name,
                         latest_release.published_at,
                         latest_release.url])

    logger.info("exit")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    handler(None, None)
