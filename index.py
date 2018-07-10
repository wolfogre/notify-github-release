# -*- coding: utf-8 -*-
import datetime
import logging
import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText

import markdown

from github import Github
from github.GithubException import UnknownObjectException
from github.GitRelease import GitRelease


def check_github(access_token: str) -> []:
    logger = logging.getLogger()
    result = []
    g = Github(access_token)
    repos = g.get_user().get_starred()
    for repo in repos:
        try:
            latest_release = repo.get_latest_release()
        except UnknownObjectException:
            logging.info("%s has no release", repo.full_name)
            continue
        logger.info("%s's latest release: %s %s %s",
                    repo.full_name,
                    latest_release.id, latest_release.title, latest_release.published_at.strftime('%Y-%m-%d %H:%M:%S'))
        if (datetime.datetime.now() - latest_release.published_at).total_seconds() <= 7 * 24 * 60 * 60:
            result.append({
                "full_name": repo.full_name,
                "latest_release": latest_release,
            })
        else:
            logger.info("ignore %s because it is too old", latest_release.id)

    return result


def send_email(email_context: dict, full_name: str, release: GitRelease):
    logger = logging.getLogger()
    mail_msg = """
        <h2>%s</h1>
        <h3>%s / %s</h3>
        <p><strong>%s</strong> <a href="%s">%s</a></p>
        <br/>
        <p>%s</p>
        """ % (full_name,
               release.tag_name, release.title,
               release.published_at.strftime('%Y-%m-%d %H:%M:%S'), release.html_url, release.html_url,
               markdown.markdown(release.body))
    message = MIMEText(mail_msg, 'html', 'utf-8')

    message['From'] = Header(email_context["user"], 'utf-8')
    message['To'] = Header(email_context["receiver"], 'utf-8')
    message['Subject'] = Header("GitHub New Release", 'utf-8')

    logger.info("start send email of %s", release.id)
    try:
        client = smtplib.SMTP_SSL(timeout=10)
        client.connect(email_context["host"], 465)
        client.login(email_context["user"], email_context["pass"])
        client.sendmail(email_context["user"], [email_context["receiver"]], message.as_string())
        logger.info("finish send email of %s", release.id)
    except smtplib.SMTPException as e:
        logger.error("faild to send email of %s: %s", release.id, e)
        raise e


def handler(event, context):
    logger = logging.getLogger()
    logger.info("start")

    result = check_github(os.environ["ACCESS_TOKEN"])
    logger.info("get %d new releases", len(result))

    if len(result) > 0:
        email_context = {
            "host": os.environ["EMAIL_HOST"],
            "user": os.environ["EMAIL_USER"],
            "pass": os.environ["EMAIL_PASS"],
            "receiver": os.environ["EMAIL_RECEIVER"],
        }
        for r in result:
            send_email(email_context, r["full_name"], r["latest_release"])

    logger.info("exit")
    return "ok"


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    handler(None, None)


