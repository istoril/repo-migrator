import logging
import logging.config
from sys import argv, exit
import os

from urllib3 import disable_warnings
import yaml

from config_loader import MigrationConfig
from gitlab_connection import GitlabConnection
from repository_cloner import RepositoryCloner


def get_logger_and_prepare_run_environment(is_gitlab_migrate_works_in_docker: bool):
    """
    Prepares OS for running Gitlab Migration Utility. Needed to be done if run in k8s.
    :param is_gitlab_migrate_works_in_docker: flag
    :return: logger object
    """
    # no need for preps if not in docker
    logger_level = logging.DEBUG if os.getenv("GIT_MIGRATION_LOG_LEVEL") == "DEBUG" else logging.INFO
    if not is_gitlab_migrate_works_in_docker:
        logger = logging.getLogger('local')
        logger.setLevel(logger_level)
        logger.info('Running not in pod, no preparations needed...')
        return logger
    logger = logging.getLogger('k8s')
    logger.setLevel(logger_level)
    s_home_user = os.getenv("home_user")
    s_home_dir = os.getenv("s_home_dir")
    s_ssh_privatekey = os.environ.get("ssh-privatekey")
    s_ssh_pub_key = os.getenv("s_ssh_pub_key")
    s_known_hosts = os.getenv("s_known_hosts")
    # check env variables
    # home dir has to be
    if s_home_user is None:
        logger.critical('No env variable "home_user"!')
        exit(1)
    if s_home_dir is None:
        logger.critical('No env variable "home_dir"!')
        exit(1)
    # check and make private ssh key
    if s_ssh_privatekey is None:
        logger.critical('No env variable "ssh-privatekey"!')
        exit(1)
    else:
        os.system(f'echo "{s_ssh_privatekey}" > ${{home_dir}}/.ssh/id_rsa')
        os.system('chmod 600 ${home_dir}/.ssh/id_rsa')
    # check and make public ssh key
    if s_ssh_pub_key is None:
        logger.critical('No env variable "ssh_pub_key"!')
        exit(1)
    else:
        os.system('echo "${ssh_pub_key}" > ${home_dir}/.ssh/id_rsa.pub')
        os.system('chmod 600 ${home_dir}/.ssh/id_rsa.pub')
    # check and make known_hosts for ssh client
    if s_known_hosts is None:
        logger.critical('No env variable "known_hosts"!')
        exit(1)
    else:
        os.system('echo "${known_hosts}" > ${home_dir}/.ssh/known_hosts')
    return logger


def main():
    ssl_verify = True if os.getenv("GIT_MIGRATION_SSL_VERIFY", 1) == 1 else False
    os.system("clear")
    with open('logging_conf.yaml', 'r') as f:
        logging_cfg = yaml.safe_load(f.read())
    logging.config.dictConfig(logging_cfg)
    # get env variables
    is_gitlab_migrate_works_in_docker = True if os.getenv("gitlab_migrate_docker") == 1 else False
    logger = get_logger_and_prepare_run_environment(is_gitlab_migrate_works_in_docker)
    if not ssl_verify:
        disable_warnings()  # urllib3
    config_yaml_file = None
    config_json_schema_file = None
    if len(argv) == 3:
        config_yaml_file = argv[1]
        config_json_schema_file = argv[2]
    elif len(argv) == 2:
        config_yaml_file = argv[1]
    migration_properties = MigrationConfig(config_yaml_file, config_json_schema_file, logger)
    with GitlabConnection(migration_properties.gitlab_api_base_url,
                          migration_properties.gitlab_token, logger, ssl_verify) as gl_connection:
        for repo in migration_properties.repos:
            for gl_project in gl_connection.get_projects_from_group(repo.gitlab_group_name, repo.gitlab_project_name):
                logger.info(f'=== Starting work with repo [{repo.gitlab_group_name}/{gl_project.path}] ===')
                with RepositoryCloner(repo, gl_project, logger, ssl_verify) as repo_cloner:
                    repo_cloner.delete_bitbucket_repo()
                    repo_cloner.create_bitbucket_repo()
                    repo_cloner.archive_gitlab_project()
                    repo_cloner.clone_repo()
                    repo_cloner.enable_mirroring()
                    repo_cloner.copy_merge_requests_from_gl_to_bb()
                    repo_cloner.change_jenkins_jobs()
                    repo_cloner.enable_webhook_for_bb_repo()
                    repo_cloner.clear_tmp()
                logger.info(f'=== Finished work with repo [{repo.gitlab_group_name}/{gl_project.path}] ===')


if __name__ == '__main__':
    main()
