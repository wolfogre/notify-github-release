# -*- coding: utf-8 -*-
import datetime
import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText

import markdown
import pytz
from github import Github, UnknownObjectException, Rate, GitRelease, Repository


class Notifier:
    def __init__(self, access_token: str, email_context: dict, orgs: []):
        self.__local_timezone = pytz.timezone("Asia/Shanghai")
        self.__start_time = self.__local_timezone.localize(datetime.datetime.now())

        self.logger = logging.getLogger("Notifier")
        self.logger.info("start at %s", self.__start_time.isoformat())

        self.__github = Github(access_token)
        self.__email_context = email_context
        self.__orgs = orgs

    def run(self):
        self.__log_rate()
        self.logger.info("check starred repos")
        result = self.__check_starred()
        for org in self.__orgs:
            self.logger.info("check repos in org")
            result.update(self.__check_org(org))
        for i in result:
            v = result[i]
            self.__send_email(v["repo"], v["release"])
        self.__log_rate()

    def __log_rate(self):
        self.logger.info("rate: limit %d, remain %d, reset %s",
                         self.__github.get_rate_limit().rate.limit,
                         self.__github.get_rate_limit().rate.remaining,
                         pytz.utc.localize(
                             self.__github.get_rate_limit().rate.reset).astimezone(self.__local_timezone))

    def __check_starred(self) -> dict:
        result = {}
        repos = self.__github.get_user().get_starred()
        for repo in repos:
            try:
                release = repo.get_latest_release()
            except UnknownObjectException:
                self.logger.info("%s has no release", repo.full_name)
                continue
            published_at = pytz.utc.localize(release.published_at).astimezone(self.__local_timezone)
            self.logger.info("%s's latest release: %s %s %s",
                             repo.full_name,
                             release.id, release.title, published_at.isoformat())
            if (self.__start_time - published_at).total_seconds() <= 24 * 60 * 60:
                result["%d-%d" % (repo.id, release.id)] = {
                    "repo": repo,
                    "release": release,
                }

        return result

    def __check_org(self, name: str) -> dict:
        result = {}
        repos = self.__github.get_organization(name).get_repos()
        for repo in repos:
            if repo.fork:
                repo = repo.source
            try:
                release = repo.get_latest_release()
            except UnknownObjectException:
                self.logger.info("%s has no release", repo.full_name)
                continue
            published_at = pytz.utc.localize(release.published_at).astimezone(self.__local_timezone)
            self.logger.info("%s's latest release: %s %s %s",
                             repo.full_name,
                             release.id, release.title, published_at.isoformat())
            if (self.__start_time - published_at).total_seconds() <= 24 * 60 * 60:
                result["%d-%d" % (repo.id, release.id)] = {
                    "repo": repo,
                    "release": release,
                }

        return result

    def __send_email(self, repo: Repository, release: GitRelease):
        published_at = pytz.utc.localize(release.published_at).astimezone(self.__local_timezone)
        mail_msg = """
                <h2>%s</h1>
                <h3>%s / %s</h3>
                <p><strong>%s</strong>&nbsp;&nbsp;&nbsp;<a href="%s">%s</a></p>
                <hr>
                <p>%s</p>
                """ % (repo.full_name,
                       release.tag_name, release.title,
                       published_at.isoformat(), release.html_url, release.html_url,
                       markdown.markdown(release.body))
        message = MIMEText(mail_msg, 'html', 'utf-8')

        message['From'] = Header(self.__email_context["user"], 'utf-8')
        message['To'] = Header(self.__email_context["receiver"], 'utf-8')
        message['Subject'] = Header(repo.full_name, 'utf-8')

        self.logger.info("start send email of %s", release.id)
        try:
            client = smtplib.SMTP_SSL(timeout=10)
            client.connect(self.__email_context["host"], 465)
            client.login(self.__email_context["user"], self.__email_context["pass"])
            client.sendmail(self.__email_context["user"], [self.__email_context["receiver"]], message.as_string())
            client.close()
            self.logger.info("finish send email of %s", release.id)
        except smtplib.SMTPException as e:
            self.logger.error("faild to send email of %s: %s", release.id, e)
            raise e

