# -*- coding: utf-8 -*-
import _thread
import datetime
import logging
import queue
import smtplib
import threading
import time
from email.header import Header
from email.mime.text import MIMEText
from os import path

import git
import markdown
import pytz
from github import Github, GitRelease, Repository


class Notifier:
    def __init__(self, task_id, access_token: str, email_context: dict, orgs: [], tmp_dir: str):
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        self.__local_timezone = pytz.timezone("Asia/Shanghai")
        self.__start_time = self.__local_timezone.fromutc(now)

        self.logger = logging.getLogger("Notifier")
        self.logger.info("start at %s", self.__start_time.isoformat())

        self.__github = Github(access_token)
        self.__email_context = email_context
        self.__orgs = orgs

        self.__task_id = task_id

        self.queue = queue.Queue()

        self.__tmp_dir = tmp_dir

    def run(self):
        self.__log_rate()

        self.logger.info("start searching repos")
        repos = self.__get_starred_repos()
        for org in self.__orgs:
            repos.update(
                self.__get_org_repos(org)
            )
        self.logger.info("find total %d repos", len(repos))

        for repo in repos.values():
            self.queue.put(repo)
        slavers = []
        for i in range(16):
            slavers.append(Slaver(self))
        for slave in slavers:
            slave.start()
        for slave in slavers:
            slave.join()
            if slave.exception() is not None:
                raise RuntimeError("thead exit with exception: %s", slave.exception())

        self.__log_rate()

    def __log_rate(self):
        self.logger.info("rate: limit %d, remain %d, reset %s",
                         self.__github.get_rate_limit().rate.limit,
                         self.__github.get_rate_limit().rate.remaining,
                         pytz.utc.localize(
                             self.__github.get_rate_limit().rate.reset).astimezone(self.__local_timezone))

    def check_repo(self, repo: Repository) -> dict:
        release = self.__get_latest_release_within_one_day(repo)
        if release is not None:
            return {
                "repo": repo,
                "release": release,
            }
        else:
            tag = self.__get_latest_tag_within_one_day(repo)
            if tag is not None:
                return {
                    "repo": repo,
                    "tag": tag,
                }
        return {}

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

    def __get_latest_release_within_one_day(self, repo: Repository) -> GitRelease:
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
            return None

        published_at = pytz.utc.localize(release.published_at).astimezone(self.__local_timezone)
        self.logger.info("%s's latest release: %s %s %s, %s ago",
                         repo.full_name,
                         release.id, release.title, published_at.isoformat(),
                         (self.__start_time - published_at))
        if (self.__start_time - published_at).total_seconds() <= 24 * 60 * 60:
            return release
        return None

    def __get_latest_tag_within_one_day(self, repo: Repository) -> dict:
        # scan all tags to find the latest tag
        # if tags is to much, clone the repo to local host to find the latest tag
        self.logger.info("start get latest tag of %s", repo.full_name)

        tags = repo.get_tags()
        tag_list = []

        for t in tags:
            tag_list.append(t)

        latest_tag = None

        if len(tag_list) > 100:
            latest_tag = self.__get_latest_tag_by_local_git(repo)
        else:
            for t in tag_list:
                git_object = repo.get_git_ref("tags/" + t.name).object
                date = None
                if git_object.type == "commit":
                    date = repo.get_git_commit(git_object.sha).committer.date
                if git_object.type == "tag":
                    date = repo.get_git_tag(git_object.sha).tagger.date
                if date is None:
                    raise RuntimeError("wrong git object type: %s, %s" % (git_object.type, git_object.url))
                published_at = pytz.utc.localize(date).astimezone(self.__local_timezone)

                if latest_tag is None or latest_tag["published_at"] < published_at:
                    latest_tag = {
                        "name": t.name,
                        "html_url": "%s/releases/tag/%s" % (repo.html_url, t.name),
                        "published_at": published_at,
                        "id": git_object.sha,
                    }

        self.logger.info("%s has %s tags", repo.full_name, len(tag_list))

        if latest_tag is None:
            self.logger.info("%s has no tag", repo.full_name)
            return None

        self.logger.info("%s's latest tag: %s %s %s, %s ago",
                         repo.full_name,
                         latest_tag["id"], latest_tag["name"], latest_tag["published_at"].isoformat(),
                         (self.__start_time - latest_tag["published_at"]))

        if (self.__start_time - latest_tag["published_at"]).total_seconds() <= 24 * 60 * 60:
            return latest_tag
        return None

    def __get_latest_tag_by_local_git(self, repo: Repository) -> dict:
        self.logger.info("start clone %s to local", repo.full_name)
        local_repo = git.Repo.clone_from(repo.clone_url, path.join(self.__tmp_dir, repo.full_name))
        self.logger.info("finish clone %s to local", repo.full_name)

        latest_tag = None
        for t in local_repo.tags:
            date = t.commit.committed_datetime
            published_at = pytz.utc.localize(date).astimezone(self.__local_timezone)
            if latest_tag is None or latest_tag["published_at"] < published_at:
                latest_tag = {
                    "name": t.name,
                    "html_url": "%s/releases/tag/%s" % (repo.html_url, t.name),
                    "published_at": published_at,
                    "id": t.commit.hexsha,
                }

    def send_email_with_release(self, repo: Repository, release: GitRelease):
        published_at = pytz.utc.localize(release.published_at).astimezone(self.__local_timezone)
        mail_msg = """
                <h2><a href="%s">%s</a></h1>
                <h3><a href="%s">%s / %s</a></h3>
                <p><strong>%s&nbsp;&nbsp;%s ago</strong></p>
                <hr>
                <p>%s</p>
                <br/>
                <br/>
                <p><i>%s</i></p>
                """ % (repo.html_url, repo.full_name,
                       release.html_url, release.tag_name, release.title,
                       published_at.isoformat(), (self.__start_time - published_at),
                       markdown.markdown(release.body),
                       self.__task_id)
        message = MIMEText(mail_msg, 'html', 'utf-8')

        message['From'] = Header(self.__email_context["user"], 'utf-8')
        message['To'] = Header(self.__email_context["receiver"], 'utf-8')
        message['Subject'] = Header(repo.full_name, 'utf-8')
        self.__send_email(release.id, message)

    def send_email_with_tag(self, repo: Repository, tag: dict):
        published_at = tag["published_at"]
        mail_msg = """
                <h2><a href="%s">%s</a></h1>
                <h3><a href="%s">%s</a></h3>
                <p><strong>%s&nbsp;&nbsp;%s ago</strong></p>
                <hr>
                <p><i>This is a regular Git tag that has not been associated with a release</i></p>
                <br/>
                <br/>
                <p><i>%s</i></p>
                """ % (repo.html_url, repo.full_name,
                       tag["html_url"], tag["name"],
                       published_at.isoformat(), (self.__start_time - published_at),
                       self.__task_id)
        message = MIMEText(mail_msg, 'html', 'utf-8')

        message['From'] = Header(self.__email_context["user"], 'utf-8')
        message['To'] = Header(self.__email_context["receiver"], 'utf-8')
        message['Subject'] = Header(repo.full_name, 'utf-8')
        self.__send_email(tag["id"], message)

    def __send_email(self, _id: str, message: MIMEText):
        self.logger.info("start send email of %s", _id)
        while True:
            try:
                client = smtplib.SMTP_SSL(host=self.__email_context["host"], timeout=10)
                client.login(self.__email_context["user"], self.__email_context["pass"])
                client.sendmail(self.__email_context["user"], [self.__email_context["receiver"]], message.as_string())
                client.close()
                self.logger.info("finish send email of %s", _id)
            except smtplib.SMTPException as e:
                self.logger.error("faild to send email of %s: %s", _id, e)
                time.sleep(1)
                continue
            break


class Slaver (threading.Thread):
    def __init__(self, master: Notifier):
        threading.Thread.__init__(self)
        self.__master = master
        self.__exception = None

    def run(self):
        try:
            self.__run()
        except Exception as e:
            self.__exception = e
            return

    def __run(self):
        self.__master.logger.info("slaver with thread %s started", _thread.get_ident())
        while True:
            try:
                repo = self.__master.queue.get_nowait()
            except queue.Empty:
                break
            result = self.__master.check_repo(repo)
            if "release" in result:
                self.__master.send_email_with_release(result["repo"], result["release"])
            if "tag" in result:
                self.__master.send_email_with_tag(result["repo"], result["tag"])

        self.__done = True
        self.__master.logger.info("slaver with thread %s exited", _thread.get_ident())

    def exception(self) -> Exception:
        return self.__exception
