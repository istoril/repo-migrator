# TODO: переделать у RepoConfig main_params и defaults так, чтобы данные были доступны как атрибуты (через точку)

import json
from os import getenv

import jsonschema
import yaml

CONF_FILE_PATH = 'migration_config.yaml'
JSON_SCHEMA_FILE_PATH = 'conf_schema.json'


class RepoConfig:
    def __init__(self, repo_params: dict, defaults: dict, main_params: dict):
        """
        Parses repo's migration config
        :param repo_params: single repo params
        :param defaults: default values from main config
        """
        self.__repo = repo_params
        self.__defaults = defaults
        self.__main_params = main_params

    @property
    def main_params(self):
        return self.__main_params

    @property
    def bitbucket_project(self):
        return self.__repo["sBitbucketProject"]

    @property
    def bitbucket_repo_name_prefix(self):
        return self.__repo["sBitbucketPrefix"]

    @property
    def gitlab_group_name(self):
        return self.__repo["sGitlabGroup"]

    @property
    def gitlab_project_name(self):
        return self.__repo.get("sGitlabProject")

    @property
    def webhook_name(self):
        return self.__repo.get("sWebhookName", self.__main_params["webhook_name"])

    @property
    def webhook_url(self):
        return self.__repo.get("sWebhookUrl", self.__main_params["webhook_url"])

    @property
    def webhook_url_parameter(self):
        return self.__repo.get("sWebhookUrlParameter", '')

    @property
    def webhook_full_url(self):
        if self.webhook_url is None:
            return None
        return self.webhook_url + self.webhook_url_parameter

    @property
    def will_gitlab_repo_be_cloned(self):
        return self.__repo.get("bClone", self.__defaults["will_gitlab_repo_be_cloned"])

    @property
    def will_bitbucket_repo_be_deleted_at_start_if_exists(self):
        return self.__repo.get("bDeleteBBRepo", self.__defaults["will_bitbucket_repo_be_deleted_at_start_if_exists"])

    @property
    def will_mirroring_be_enabled_for_gitlab_repo(self):
        return self.__repo.get("bMirroring", self.__defaults["will_mirroring_be_enabled_for_gitlab_repo"])

    @property
    def will_gitlab_repo_become_readonly(self):
        return self.__repo.get("bMakeGitlabRepoReadonly", self.__defaults["will_gitlab_repo_become_readonly"])

    @property
    def will_mrs_will_be_cloned(self):
        return self.__repo.get("bDuplicateMRs", self.__defaults["will_MRs_will_be_cloned"])

    @property
    def will_local_tmp_be_deleted(self):
        return self.__repo.get("bClear", self.__defaults["will_local_tmp_be_deleted"])

    @property
    def will_jenkins_jobs_will_be_changed(self):
        return self.__repo.get("bChangeJenkinsJobs", self.__defaults["will_jenkins_jobs_will_be_changed"])

    @property
    def will_jenkins_jobs_be_backed_up(self):
        return self.__repo.get("bBackupJenkinsJobs", self.__defaults["will_jenkins_jobs_be_backed_up"])

    @property
    def will_webhook_be_enabled(self):
        return self.webhook_url is not None and self.webhook_url is not None


class MigrationConfig:
    def __init__(self, config_file_path: str, json_schema_file_path: str, logger):
        """
        Checks, loads and parses migration config from YAML file
        :param config_file_path: migration config filename
        :param json_schema_file_path: json schema for config file
        """
        self.__logger = logger
        if config_file_path is None:
            config_file_path = CONF_FILE_PATH
        if json_schema_file_path is None:
            json_schema_file_path = JSON_SCHEMA_FILE_PATH
        self.__config_file_path = config_file_path
        with open(config_file_path, "r") as yaml_file:
            self.__yaml_conf = dict(yaml.safe_load(yaml_file))
        self.__check_config_file(json_schema_file_path)
        self.__defaults = {
            'will_gitlab_repo_be_cloned': self.__yaml_conf.get('bDefaultCloning', False),
            'will_bitbucket_repo_be_deleted_at_start_if_exists': self.__yaml_conf.get('bDefaultDeleteBBRepo', False),
            'will_mirroring_be_enabled_for_gitlab_repo': self.__yaml_conf.get('bDefaultMirroring', False),
            'will_gitlab_repo_become_readonly': self.__yaml_conf.get('bDefaultGitlabReadonly', False),
            'will_MRs_will_be_cloned': self.__yaml_conf.get('bDefaultDuplicateMRs', False),
            'will_local_tmp_be_deleted': self.__yaml_conf.get('bDefaultClear', True),
            'will_jenkins_jobs_will_be_changed': self.__yaml_conf.get('bDefaultChangeJenkinsJobs', False),
            'will_jenkins_jobs_be_backed_up': self.__yaml_conf.get('bDefaultBackupJenkinsJobs', True)
        }
        self.__main_params = {
            "bitbucket_api_url": self.bitbucket_base_url,
            "bitbucket_username": self.bitbucket_user,
            "bitbucket_token": self.bitbucket_token,
            "gitlab_api_url": self.gitlab_api_base_url,
            "gitlab_ssh_url": self.gitlab_ssh_base_url,
            "gitlab_username": self.gitlab_user,
            "gitlab_token": self.gitlab_token,
            "jenkins_url": self.jenkins_base_url,
            "jenkins_username": self.jenkins_user,
            "jenkins_token": self.jenkins_token,
            "jenkins_backup_path": self.jenkins_backup_path,
            "tmp_folder": self.tmp_folder,
            'webhook_name': self.webhook_name,
            'webhook_url': self.webhook_url
        }
        self.__repos = []
        for repo in self.__yaml_conf["repos"]:
            self.__repos.append(RepoConfig(repo, self.__defaults, self.__main_params))

    @property
    def yaml_conf(self):
        return self.__yaml_conf

    @property
    def gitlab_api_base_url(self):
        url = str(self.__yaml_conf['sGitlabApiUrl'])
        if not url.startswith('http'):
            url = 'https://' + url
        if not url.endswith('/'):
            url += '/'
        return url

    @property
    def gitlab_ssh_base_url(self):
        url = self.__yaml_conf["sGitlabRepoUrl"]
        if not url.startswith('ssh://'):
            url = 'ssh://' + url
        if not url.endswith('/'):
            url += '/'
        return url

    @property
    def bitbucket_base_url(self):
        url = self.__yaml_conf["sBitbucketUrl"]
        if not url.startswith('http'):
            url = 'https://' + url
        if not url.endswith('/'):
            url += '/'
        return url

    @property
    def jenkins_base_url(self):
        url = self.__yaml_conf.get("sJenkinsUrl", "")
        if url:
            if not url.startswith('http'):
                url = 'https://' + url
            if not url.endswith('/'):
                url += '/'
        return url

    @property
    def tmp_folder(self):
        path = self.__yaml_conf["sLocalRootPath"]
        if path.startswith("~"):
            path = getenv("HOME") + path[1:]
        if not path.endswith('/'):
            path += '/'
        return path

    @property
    def __username(self):
        return self.__yaml_conf.get("sUser", "")

    @property
    def gitlab_user(self):
        return self.__yaml_conf.get("sGitlabUser", self.__username)

    @property
    def gitlab_token(self):
        return getenv("GITLAB_TOKEN")

    @property
    def bitbucket_user(self):
        return self.__yaml_conf.get("sBBUser", self.__username)

    @property
    def bitbucket_token(self):
        return getenv("BITBUCKET_TOKEN")

    @property
    def jenkins_user(self):
        return self.__yaml_conf.get("sJenkinsUser", self.__username)

    @property
    def jenkins_token(self):
        return getenv("JENKINS_TOKEN", "")

    @property
    def jenkins_backup_path(self):
        path = self.__yaml_conf.get("sJenkinsJobsBkpPath", "")
        if path.startswith("~"):
            path = getenv("HOME") + path[1:]
        if len(path) and not path.endswith('/'):
            path += '/'
        return path

    @property
    def webhook_name(self):
        return self.__yaml_conf.get('sDefaultWebhookName')

    @property
    def webhook_url(self):
        return self.__yaml_conf.get('sDefaultWebhookUrl')

    @property
    def repos(self):
        return self.__repos

    @property
    def main_params(self):
        return self.__main_params

    @property
    def defaults(self):
        return self.__defaults

    def __enter__(self):
        return self

    def __check_config_file(self, json_schema_file_path: str):
        """
        Checks if config file is made correctly (by json schema)
        :param json_schema_file_path: path to json schema
        :return:
        """
        with open(json_schema_file_path) as schema_file:
            schema = json.load(schema_file)
        jsonschema.validate(instance=self.__yaml_conf, schema=schema)
        self.__logger.info(f"File {self.__config_file_path} is valid according to schema {json_schema_file_path}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
