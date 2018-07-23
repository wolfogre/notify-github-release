# -*- coding: utf-8 -*-
import datetime
import gzip
import logging
import re
import smtplib
from _socket import timeout
from email.header import Header
from email.mime.text import MIMEText
from urllib import request
from urllib.error import HTTPError, URLError

import markdown
import pytz
from github import Github, GitRelease, Repository


class Notifier:
    def __init__(self, access_token: str, email_context: dict, orgs: []):
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        self.__local_timezone = pytz.timezone("Asia/Shanghai")
        self.__start_time = self.__local_timezone.fromutc(now)

        self.logger = logging.getLogger("Notifier")
        self.logger.info("start at %s", self.__start_time.isoformat())

        self.__github = Github(access_token)
        self.__email_context = email_context
        self.__orgs = orgs

    def run(self):
        self.__log_rate()

        self.logger.info("start searching repos")
        repos = self.__get_starred_repos()
        for org in self.__orgs:
            repos.update(
                self.__get_org_repos(org)
            )
        self.logger.info("find total %d repos", len(repos))

        result = self.__check_repos(repos.values())
        self.logger.info("find %d repos have update", len(result))
        for i in result:
            v = result[i]
            if "release" in v:
                self.__send_email_with_release(v["repo"], v["release"])
            if "tag" in v:
                self.__send_email_with_tag(v["repo"], v["tag"])
        self.__log_rate()

    def __log_rate(self):
        self.logger.info("rate: limit %d, remain %d, reset %s",
                         self.__github.get_rate_limit().rate.limit,
                         self.__github.get_rate_limit().rate.remaining,
                         pytz.utc.localize(
                             self.__github.get_rate_limit().rate.reset).astimezone(self.__local_timezone))

    def __check_repos(self, repos: []) -> dict:
        result = {}
        for repo in repos:
            while True:
                try:
                    release, check_tag = self.__get_latest_release_within_one_day(repo)
                    if release is not None:
                        result[repo.id] = {
                            "repo": repo,
                            "release": release,
                        }
                    elif check_tag:
                        tag = self.__get_latest_tag_within_one_day(repo)
                        if tag is not None:
                            result[repo.id] = {
                                "repo": repo,
                                "tag": tag,
                            }
                except (HTTPError, URLError, timeout) as e:
                    self.logger.error("visit tag page %s failed: %s", repo.html_url + "/tags", e)
                    continue
                break
        return result

    def __get_starred_repos(self) -> dict:
        result = {}
        repos = self.__github.get_user().get_starred()
        for repo in repos:
            result[repo.id] = repo
        return result

    def __get_org_repos(self, name: str) -> dict:
        result = {}
        repos = self.__github.get_organization(name).get_repos()
        for repo in repos:
            if repo.fork:
                repo = repo.source
            result[repo.id] = repo
        return result

    def __get_latest_release_within_one_day(self, repo: Repository) -> (GitRelease, bool):
        # Draft releases and prereleases are not returned repo.get_latest_release(), so use get_releases()
        self.logger.info("start get latest release of %s", repo.full_name)
        release = None
        for r in repo.get_releases():
            if r.draft:
                continue
            release = r
            break

        if release is None:
            self.logger.info("%s has no release", repo.full_name)
            return None, True

        published_at = pytz.utc.localize(release.published_at).astimezone(self.__local_timezone)
        self.logger.info("%s's latest release: %s %s %s, %s ago",
                         repo.full_name,
                         release.id, release.title, published_at.isoformat(),
                         (self.__start_time - published_at))
        if (self.__start_time - published_at).total_seconds() <= 24 * 60 * 60:
            return release, False
        return None, False

    def __get_latest_tag_within_one_day(self, repo: Repository) -> dict:
        # visiting the html page is the only way to get the latest tag
        self.logger.info("start get latest tag of %s", repo.full_name)
        resp = request.urlopen(repo.html_url + "/tags", timeout=5)
        buffer = resp.read()
        body = str(buffer, encoding="utf-8")

        pattern = re.compile('<span class="tag-name">.*?</span>')
        tag_names = pattern.findall(body)
        if len(tag_names) == 0:
            self.logger.info("%s has no tag", repo.full_name)
            return None

        latest_tag_name = tag_names[0].replace('<span class="tag-name">', '').replace('</span>', '')

        git_object = repo.get_git_ref("tags/" + latest_tag_name).object
        date = None
        if git_object.type == "commit":
            date = repo.get_git_commit(git_object.sha).committer.date
        if git_object.type == "tag":
            date = repo.get_git_tag(git_object.sha).tagger.date
        if date is None:
            raise RuntimeError("wrong git object type: %s, %s" % (git_object.type, git_object.url))

        published_at = pytz.utc.localize(date).astimezone(self.__local_timezone)
        self.logger.info("%s's latest tag: %s %s %s, %s ago",
                         repo.full_name,
                         git_object.sha, latest_tag_name, published_at.isoformat(),
                         (self.__start_time - published_at))

        if (self.__start_time - published_at).total_seconds() <= 24 * 60 * 60:
            return {
                "name": latest_tag_name,
                "html_url": "%s/releases/tag/%s" % (repo.html_url, latest_tag_name),
                "published_at": published_at,
                "id": git_object.sha,
            }
        return None

    def __send_email_with_release(self, repo: Repository, release: GitRelease):
        published_at = pytz.utc.localize(release.published_at).astimezone(self.__local_timezone)
        mail_msg = """
                <h2><a href="%s">%s</a></h1>
                <h3><a href="%s">%s / %s</a></h3>
                <p><strong>%s&nbsp;&nbsp;%s ago</strong></p>
                <hr>
                <p>%s</p>
                """ % (repo.html_url, repo.full_name,
                       release.html_url, release.tag_name, release.title,
                       published_at.isoformat(), (self.__start_time - published_at),
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

    def __send_email_with_tag(self, repo: Repository, tag: dict):
        published_at = tag["published_at"]
        mail_msg = """
                <h2><a href="%s">%s</a></h1>
                <h3><a href="%s">%s</a></h3>
                <p><strong>%s&nbsp;&nbsp;%s ago</strong></p>
                <hr>
                <p><i>This is a regular Git tag that have not been associated with a release</i></p>
                """ % (repo.html_url, repo.full_name,
                       tag["html_url"], tag["name"],
                       published_at.isoformat(), (self.__start_time - published_at))
        message = MIMEText(mail_msg, 'html', 'utf-8')

        message['From'] = Header(self.__email_context["user"], 'utf-8')
        message['To'] = Header(self.__email_context["receiver"], 'utf-8')
        message['Subject'] = Header(repo.full_name, 'utf-8')

        self.logger.info("start send email of %s", tag["id"])
        try:
            client = smtplib.SMTP_SSL(timeout=10)
            client.connect(self.__email_context["host"], 465)
            client.login(self.__email_context["user"], self.__email_context["pass"])
            client.sendmail(self.__email_context["user"], [self.__email_context["receiver"]], message.as_string())
            client.close()
            self.logger.info("finish send email of %s", tag["id"])
        except smtplib.SMTPException as e:
            self.logger.error("faild to send email of %s: %s", tag["id"], e)
            raise e

