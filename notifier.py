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
from urllib import request
from xml.etree.ElementTree import ElementTree

from dateutil import tz
from dateutil.parser import parser
from github import Github, Repository

local_timezone = tz.gettz("Asia/Shanghai")


class Notifier:
    def __init__(self, task_id, access_token: str, email_context: dict, orgs: []):
        self.__start_time = datetime.datetime.now(tz.tzlocal()).astimezone(local_timezone)

        self.logger = logging.getLogger("Notifier")
        self.logger.info("start at %s", self.__start_time.isoformat())

        self.__github = Github(access_token)
        self.__email_context = email_context
        self.__orgs = orgs

        self.__task_id = task_id

    def run(self):
        self.__log_rate()

        self.logger.info("start searching repos")
        repos = self.__get_starred_repos()
        for org in self.__orgs:
            repos.update(
                self.__get_org_repos(org)
            )
        self.logger.info("find total %d repos", len(repos))

        task = queue.Queue()
        for repo in repos.values():
            task.put(repo)

        slavers = []
        result = {}
        for i in range(32):
            slavers.append(Slaver(task, result))
        for slave in slavers:
            slave.start()
        for slave in slavers:
            slave.join()
            if slave.exception() is not None:
                raise RuntimeError("thead exit with exception: %s", slave.exception())

        for release in result.values():
            if release is not None and (self.__start_time - release["release_time"]).total_seconds() <= 24 * 60 * 60:
                self.__send_email(release)

        self.__log_rate()

    def __log_rate(self):
        rage = self.__github.get_rate_limit().rate
        self.logger.info("rate: limit %d, remain %d, reset %s",
                         rage.limit,
                         rage.remaining,
                         rage.reset.replace(tzinfo=tz.tzutc()).astimezone(local_timezone))

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

    def __send_email(self, release: dict):
        mail_msg = """
                <h2><a href="%s">%s</a></h1>
                <h3><a href="%s">%s / %s</a></h3>
                <p><strong>%s&nbsp;&nbsp;%s ago</strong></p>
                <hr>
                <p>%s</p>
                <br/>
                <br/>
                <p><i>%s</i></p>
                """ % (release["repo_url"], release["repo_name"],
                       release["release_url"], release["release_name"], release["release_title"],
                       release["release_time"].isoformat(),
                       (self.__start_time - release["release_time"]),
                       release["release_content"],
                       self.__task_id)
        message = MIMEText(mail_msg, 'html', 'utf-8')

        message['From'] = Header(self.__email_context["user"], 'utf-8')
        message['To'] = Header(self.__email_context["receiver"], 'utf-8')
        message['Subject'] = Header(release["repo_name"], 'utf-8')

        self.logger.info("start send email of %s %s", release["repo_name"], release["release_name"])
        while True:
            try:
                client = smtplib.SMTP_SSL(host=self.__email_context["host"], timeout=10)
                client.login(self.__email_context["user"], self.__email_context["pass"])
                client.sendmail(self.__email_context["user"], [self.__email_context["receiver"]], message.as_string())
                client.close()
                self.logger.info("finish send email of %s %s", release["repo_name"], release["release_name"])
            except smtplib.SMTPException as e:
                self.logger.info("fail to send email of %s %s: %s", release["repo_name"], release["release_name"], e)
                time.sleep(1)
                continue
            break


class Slaver (threading.Thread):
    def __init__(self, task: queue.Queue, result: dict):
        threading.Thread.__init__(self)
        self.__task = task
        self.__result = result
        self.__exception = None
        self.__opener = request.build_opener()
        self.logger = logging.getLogger("Slaver")

    def run(self):
        try:
            self.__run()
        except Exception as e:
            self.__exception = e
            return

    def __run(self):
        self.logger.info("slaver with thread %s started", _thread.get_ident())
        while True:
            try:
                repo = self.__task.get_nowait()
            except queue.Empty:
                break
            self.__result[repo.id] = self.__get_latest_release(repo)

        self.__done = True
        self.logger.info("slaver with thread %s exited", _thread.get_ident())

    def exception(self) -> Exception:
        return self.__exception

    def __get_latest_release(self, repo: Repository) -> dict:
        # by visiting releases.atom page
        self.logger.info("start get latest release of %s", repo.full_name)

        atom_url = "%s/releases.atom" % repo.html_url
        while True:
            try:
                xml = ElementTree(file=self.__opener.open(atom_url, timeout=30))
                break
            except Exception as e:
                logging.error("failed to visit %s: %s", atom_url, e)

        latest_release = None
        for elem in xml.iter("{http://www.w3.org/2005/Atom}entry"):
            release = {
                "repo_name": repo.full_name,
                "repo_url": repo.html_url,
                "release_name": elem.find("{http://www.w3.org/2005/Atom}id").text.split("/")[-1],
                "release_time": parser().parse(elem.find("{http://www.w3.org/2005/Atom}updated").text).astimezone(local_timezone),
                "release_url": elem.find("{http://www.w3.org/2005/Atom}link").attrib["href"],
                "release_title": elem.find("{http://www.w3.org/2005/Atom}title").text,
                "release_content": elem.find("{http://www.w3.org/2005/Atom}content").text,
            }
            if latest_release is not None:
                if latest_release["release_time"] < release["release_time"]:
                    latest_release = release
            else:
                latest_release = release

        if latest_release is None:
            self.logger.info("%s has no release", repo.full_name)
            return None

        self.logger.info("%s's latest release: %s, %s, %s",
                         repo.full_name,
                         latest_release["release_name"], latest_release["release_title"],
                         latest_release["release_time"].isoformat())
        return latest_release
