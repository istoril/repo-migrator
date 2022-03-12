from sys import exit
import json
import os
import subprocess
import xml.etree.ElementTree as ElT

from atlassian import Bitbucket
from dateutil.parser import parse  # for datetime parsing
from requests.auth import HTTPBasicAuth
import jenkins
import requests

from gitlab.v4.objects import Project as GitlabProject
from config_loader import RepoConfig

JENKINS_JOB_NAME_PATTERN_ADDON = '_'
JENKINS_FOLDER_NAME_PATTERN = 'backend'


class RepositoryCloner:
    __bb_api_requests_headers = {
        "Content-Type": "application/json",
        'X-Atlassian-Token': 'no-check'
    }
    __bb_rest_requests_headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        'X-Atlassian-Token': 'no-check'
    }

    def __init__(self, properties: RepoConfig, gitlab_project: GitlabProject, logger, ssl_verify: bool = True):
        """
        Class making repository migration
        :param properties: repository migration parameters
        :param gitlab_project: Gitlab Project Object
        :param ssl_verify: if SSL cert will be verified
        """
        self.__logger = logger
        self.__repo_properties = properties
        self.__gitlab_project = gitlab_project
        self.__ssl_verify = ssl_verify
        try:
            self.__bitbucket_connection = Bitbucket(url=self.__repo_properties.main_params["bitbucket_api_url"],
                                                    username=self.__repo_properties.main_params["bitbucket_username"],
                                                    password=self.__repo_properties.main_params["bitbucket_token"],
                                                    verify_ssl=ssl_verify)
        except Exception as err:
            self.__logger.critical(f"Problem connecting to BitBucket: {err}")
            exit(1)
        jenkins_url = self.__repo_properties.main_params["jenkins_url"]
        jenkins_username = self.__repo_properties.main_params["jenkins_username"]
        jenkins_token = self.__repo_properties.main_params["jenkins_token"]
        if jenkins_url and jenkins_username and jenkins_token:
            try:
                self.__jenkins_connection = jenkins.Jenkins(url=jenkins_url, username=jenkins_username,
                                                            password=jenkins_token)
                self.__jenkins_connection._session.verify = ssl_verify
            except Exception as err:
                self.__logger.error(f"Problem connecting to Jenkins: {err}")
                if self.__repo_properties.will_jenkins_jobs_will_be_changed:
                    exit(1)
        self.__bitbucket_repo_urls = {}
        self.__bitbucket_repo = None
        self.__bb_requests_auth = HTTPBasicAuth(
            self.__repo_properties.main_params["bitbucket_username"],
            self.__repo_properties.main_params["bitbucket_token"]
        )

    def __enter__(self):
        return self

    @property
    def __bitbucket_repo_name(self):
        return f'{self.__repo_properties.bitbucket_repo_name_prefix}.{self.__gitlab_project.path}'

    @property
    def _bitbucket_repo(self):
        if self.__bitbucket_repo is None:
            self.__bitbucket_repo = self.__get_bitbucket_repo()
        return self.__bitbucket_repo

    def __get_bitbucket_repo(self):
        """"""
        try:
            bb_repo = self.__bitbucket_connection.get_repo(self.__repo_properties.bitbucket_project,
                                                           self.__bitbucket_repo_name)
            for url in bb_repo['links']['clone']:
                if url['name'] == 'http':
                    self.__bitbucket_repo_urls["http"] = url['href']
                elif url['name'] == 'ssh':
                    self.__bitbucket_repo_urls["ssh"] = url['href']
            return bb_repo
        except Exception as err:
            self.__logger.critical(f'Connecting to BitBucket API problem: {err}, stopping!')
            exit(1)

    def delete_bitbucket_repo(self) -> bool:
        """
        Delete BitBucket repository
        :return: Was repository deleted
        """
        if not self.__repo_properties.will_bitbucket_repo_be_deleted_at_start_if_exists:
            return False
        self.__logger.info('- Deleting Bitbucket repo')
        try:
            self.__bitbucket_connection.delete_repo(self.__repo_properties.bitbucket_project,
                                                    self.__bitbucket_repo_name)
        except Exception as err:
            self.__logger.warning(f"Error while deleting BitBucket repo: {err}")
        return True

    def create_bitbucket_repo(self) -> bool:
        """
        Creates BitBucket repository and sets default branch
        :return: Was repo created
        """
        if not self.__repo_properties.will_gitlab_repo_be_cloned:
            return False
        self.__logger.info('- Creating Bitbucket repo')
        bb_repo_name = self.__bitbucket_repo_name
        try:
            self.__bitbucket_connection.create_repo(self.__repo_properties.bitbucket_project,
                                                    bb_repo_name, forkable=True, is_private=True)
        except Exception as err:
            self.__logger.warning(f'- Bitbucket Repo was not created - already exists? --- {err}')
            try:
                self.__bitbucket_connection.get_repo(self.__repo_properties.bitbucket_project, bb_repo_name)
            except Exception as err:
                self.__logger.critical(f'Connecting to BitBucket API problem: {err}, stopping!')
                exit(1)
        else:
            self.__logger.info('- Bitbucket Repo created')
            try:
                default_branch = self.__gitlab_project.default_branch
                self.__bitbucket_connection.set_default_branch(self.__repo_properties.bitbucket_project,
                                                               bb_repo_name, default_branch)
                self.__logger.info(f"-- Default branch in repo [{bb_repo_name}] is set to '{default_branch}'")
            except Exception as error:
                self.__logger.warning(f"-- Default branch in repo [{bb_repo_name}] wasn't set: {error}")
        # This check looks like doing nothing, but it fills self.__bitbucket_repo if it is None,
        # just look into property realisation
        if self._bitbucket_repo is None:
            pass
        return True

    def archive_gitlab_project(self) -> bool:
        """
        Archive (make readonly) Gitlab project
        :return: Was repo archived
        """
        if not self.__repo_properties.will_gitlab_repo_become_readonly:
            return False
        self.__logger.info('- Putting source repo in readonly state...')
        try:
            self.__gitlab_project.archive()
        except Exception as err:
            self.__logger.critical(f"Error while putting source repo in r/o state: {err}")
            exit(1)
        return True

    def __delete_bb_repo_branch(self, branch_name):
        """
        Deletes branch in BitBucket repo
        :param branch_name: branch name
        :return: deletion result
        """
        return self.__bitbucket_connection.delete_branch(self.__repo_properties.bitbucket_project,
                                                         self.__bitbucket_repo_name, branch_name)

    def __check_git_push_output_for_failed_branches(self, cmd_output: str) -> bool:
        """
        Checks if all branches were pushed and deletes failed branches
        :param cmd_output:
        :return: Was any branch failed to push to remote (True) or all branches ok (False)
        """
        self.__logger.debug(">>> Checking if all branches successfully pushed...")
        # get list fof failed branch names
        failed_branches = []
        # some logic
        for line in cmd_output.splitlines():
            if '[rejected]' in line:
                line_elements = [s.strip() for s in line.split()]
                failed_branches.append(line_elements[line_elements.index('->') + 1])
        # delete failed branches in BitBucket
        for branch in failed_branches:
            self.__logger.debug(self.__delete_bb_repo_branch(branch))
        # if list is not empty, return True
        return False if len(failed_branches) == 0 else True

    def __exec_os_cmd(self, cmd: str, workdir: str = os.getcwd()):
        """
        Executes os command
        :param cmd: command to execute
        :param workdir: directory to execute command in
        :return:
        """
        self.__logger.info(f'Executing "{cmd}" in directory "{workdir}"')
        cmd_process = subprocess.Popen(cmd.split(), stdin=subprocess.PIPE, cwd=workdir,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # print the stdout/stderr as it comes in
        cmd_result = ""
        while True:
            # The readline() will block until...
            # it reads and returns a string that ends in a '\n',
            # or until the process has ended which will result in '' string
            cmd_result_line = cmd_process.stdout.readline().decode()
            if cmd_result_line:
                cmd_result += f'{cmd_result_line.strip()}\n'
            elif cmd_process.poll() is not None:
                break
        cmd_result = cmd_result.strip()
        # get the return code
        cmd_result_code = cmd_process.wait()
        return cmd_result, cmd_result_code

    def clone_repo(self) -> bool:
        """
        Clones repo from Gitlab to BitBucket
        :return: Was repo cloned
        """
        if not self.__repo_properties.will_gitlab_repo_be_cloned:
            return False
        # This check looks like doing nothing, but it fills self.__bitbucket_repo if it is None,
        # just look into property realisation
        # if self._bitbucket_repo is None:
        #     pass
        self.__logger.info('- Cloning...')
        gl_group = self.__repo_properties.gitlab_group_name
        gl_project = self.__gitlab_project.path
        src_url = f'{self.__repo_properties.main_params["gitlab_ssh_url"]}{gl_group}/{gl_project}.git'
        # src_url = self.__gitlab_project.ssh_url_to_repo
        dst_url = self.__bitbucket_repo_urls.get('ssh')
        if dst_url is None:
            self.__logger.critical('No Bitbucket repo ssh url!')
            # exit(1)
        local_path = f'{self.__repo_properties.main_params["tmp_folder"]}{gl_group}/{gl_project}'
        # clone gitlab repo to local path
        cmd_result, _ = self.__exec_os_cmd(f'rm -rfv {local_path}')
        self.__logger.debug(cmd_result)
        cmd_result, _ = self.__exec_os_cmd(f'mkdir -p {local_path}')
        self.__logger.debug(cmd_result)
        cmd = f'git --no-pager clone --progress --mirror {src_url} {local_path}'
        try:
            cmd_result, cmd_result_code = self.__exec_os_cmd(cmd)
            if cmd_result_code != 0:
                self.__logger.error(f"{cmd_result}")
                self.__logger.error(f"Result code: {cmd_result_code}")
                raise RuntimeError(f'Command "{cmd}" exited with error {cmd_result_code}')
        except Exception as err:
            self.__logger.critical(err)
            exit(1)
        self.__logger.debug(cmd_result)
        cmd_result, _ = self.__exec_os_cmd(f'git remote rm origin', local_path)
        self.__logger.debug(cmd_result)
        # push local repo to bitbucket
        self.__logger.info('Adding new remote...')
        cmd_result, _ = self.__exec_os_cmd(f'git remote add origin {dst_url}', local_path)
        self.__logger.debug(cmd_result)
        self.__logger.info('Pushing branches...')
        is_some_branch_failed = True
        while is_some_branch_failed:
            cmd_result, cmd_result_code = self.__exec_os_cmd(f'git push origin --all', local_path)
            self.__logger.debug(cmd_result)
            is_some_branch_failed = self.__check_git_push_output_for_failed_branches(cmd_result)
        self.__logger.info('Pushing tags...')
        cmd_result = self.__exec_os_cmd(f'git push --tags', local_path)
        self.__logger.debug(cmd_result)
        return True

    def enable_mirroring(self) -> bool:
        """
        Enables mirroring from GL to BB repo
        :return: was mirroring enabled
        """
        if not self.__repo_properties.will_mirroring_be_enabled_for_gitlab_repo:
            return False
        # This check looks like doing nothing, but it fills self.__bitbucket_repo if it is None,
        # just look into property realisation
        if self._bitbucket_repo is None:
            pass
        self.__logger.info('- Enabling mirroring...')
        # making target mirroring url
        bb_repo_url = self.__bitbucket_repo_urls.get('http')
        domain_name_position = bb_repo_url.find('://') + 3
        bb_user = self.__repo_properties.main_params["bitbucket_username"]
        bb_pass = self.__repo_properties.main_params["bitbucket_token"]
        mirror_url = f'{bb_repo_url[:domain_name_position]}{bb_user}:{bb_pass}@{bb_repo_url[domain_name_position:]}'
        # creating new repo mirror in Gitlab
        try:
            new_mirror = self.__gitlab_project.remote_mirrors.create({'url': mirror_url, 'enabled': True})
            new_mirror.only_protected_branches = False
            new_mirror.keep_divergent_refs = False
            new_mirror.save()
        except Exception as err:
            self.__logger.critical(f"Error while enabling mirroring: {err}")
            exit(1)
        return True

    def enable_webhook_for_bb_repo(self) -> bool:
        """
        Creates and enables webhook for BitBucket repository
        :return: was webhook enabled
        """
        if not self.__repo_properties.will_webhook_be_enabled:
            return False
        # This check looks like doing nothing, but it fills self.__bitbucket_repo if it is None,
        # just look into property realisation
        if self._bitbucket_repo is None:
            pass
        self.__logger.info("- Enabling webhook for BitBucket repo...")
        bb_url = self.__repo_properties.main_params["bitbucket_api_url"]
        bb_project = self.__repo_properties.bitbucket_project
        bb_repo_name = self.__bitbucket_repo_name
        webhook_api_url = f'{bb_url}rest/api/latest/projects/{bb_project}/repos/{bb_repo_name}/webhooks'
        webhook_creation_data = json.dumps({
            "active": True,
            "events": ["pr:opened", "pr:from_ref_updated", "pr:modified"],
            "configuration": {
                "createdBy": "bitbucket"
            },
            "name": self.__repo_properties.webhook_name,
            "url": self.__repo_properties.webhook_full_url
        })
        new_webhook = requests.post(webhook_api_url, verify=False, data=webhook_creation_data,
                                    headers=self.__bb_api_requests_headers, auth=self.__bb_requests_auth)
        return 200 <= new_webhook.status_code < 300

    def __get_pr_creation_request_data(self, gl_mr, bb_pr_description) -> dict:
        """
        Returns data for pull request creation
        Method is unused but saved to store knowledge: full request body to create PR in BitBucket
        :param gl_mr: Gitlab repository's merge request
        :param bb_pr_description: PR description
        :return: dict with data for pull request creation
        """
        return {
            "title": gl_mr.title,
            "description": bb_pr_description,
            "state": "OPEN",
            "open": True,
            "closed": False,
            "fromRef": {
                "id": gl_mr.source_branch,
                "repository": {
                    "slug": self.__bitbucket_repo_name,
                    "name": self.__bitbucket_repo_name,
                    "project": {"key": self.__repo_properties.bitbucket_project}
                }
            },
            "toRef": {
                "id": gl_mr.target_branch,
                "repository": {
                    "slug": self.__bitbucket_repo_name,
                    "name": self.__bitbucket_repo_name,
                    "project": {"key": self.__repo_properties.bitbucket_project}
                }
            },
            "locked": False,
            "reviewers": [],
            "links": {
                "self": []
            }
        }

    def __replace_markdown_links(self, text: str) -> str:
        """
        Replaces links with images, etc. in Markdown text
        :param text: text in which links needs replacement
        :return: text with replaced links
        """
        # We need to add full path to images, etc in descriptions, comments and so on.
        # Because of Markdown in Gitlab. Check and insert full path
        # Substring for replacing links to images, etc in PR descriptions
        markdown_replace_string = f']({self.__gitlab_project.web_url}/uploads/'
        # Replaces
        text = text.replace('](/uploads/', markdown_replace_string)
        text = text.replace('](uploads/', markdown_replace_string)
        text = text.replace('] (/uploads/', markdown_replace_string)
        return text.replace('] (uploads/', markdown_replace_string)

    def __create_bitbucket_pull_request(self, gl_mr):
        """
        Creates Pull Request for BitBucket's repository
        :param gl_mr: Gitlab repo's Merge Request
        :return: BitBucket repo's Pull Request
        """
        # BitBucket PullRequests API url
        # bb_pr_api_url = self.__repo_properties.main_params["bitbucket_api_url"]
        # bb_pr_api_url += self.__bitbucket_connection._url_pull_requests(self.__repo_properties.bitbucket_project,
        #                                                                 self.__bitbucket_repo_name)
        # PR description
        bb_pr_description = self.__replace_markdown_links(gl_mr.description)
        try:
            # trying to create PR
            new_pr = self.__bitbucket_connection.open_pull_request(
                source_project=self.__repo_properties.bitbucket_project,
                source_repo=self.__bitbucket_repo_name,
                source_branch=gl_mr.source_branch,
                dest_project=self.__repo_properties.bitbucket_project,
                dest_repo=self.__bitbucket_repo_name,
                destination_branch=gl_mr.target_branch,
                title=gl_mr.title,
                description=bb_pr_description
            )
        except requests.exceptions.HTTPError as err:
            # if error, log it and return None
            self.__logger.error(f'Tried to create PR with parameters:\n{err.request.body}')
            self.__logger.error(f'Got a HTTP error with code {err.response.status_code} and text:\n{err.response.text}')
            return None
        # creating comment in new PR with Gitlab's MR creation date and creator name
        timestamp = parse(gl_mr.created_at).strftime("%d.%m.%Y, %H:%M:%S")
        author = gl_mr.author['name']
        comment_text = f'This pull request was created in Gitlab \non {timestamp} \nby {author}'
        self.__bitbucket_connection.add_pull_request_comment(self.__repo_properties.bitbucket_project,
                                                             self.__bitbucket_repo_name, new_pr['id'], comment_text)
        return new_pr

    def __get_comment_to_codeline_creation_request_data(self, mr_comment_position: dict, comment_text: str) -> dict:
        """
        Returns data for request to create comment to code line in Bitbucket repo's pull request.
        :param mr_comment_position:
        :param comment_text:
        :return: comment to codeline creation request data
        """
        # Determining how and where to put comment
        # does comment has string number in file's new version
        is_newline = mr_comment_position['new_line'] is not None
        # does comment has string number in file's old version
        is_oldline = mr_comment_position['old_line'] is not None
        line_number = 0  # comment's string number in file
        linetype = ''  # comment's string type: deleted, added or not changed
        filetype = ''  # comment's file type: "old" (before commit) or "new" (committed)
        if not is_newline and not is_oldline:
            # comment has no new and no old string number - how is it possible?
            # this print is for debugging, never appeared
            self.__logger.warning('WTF with MR comments?')
        elif not is_newline and is_oldline:
            # has old line but not new - comment to deleted line
            linetype = "REMOVED"
            line_number = int(mr_comment_position['old_line'])
            filetype = "FROM"
        elif is_newline and not is_oldline:
            # has new line but not old - comment to added line
            linetype = "ADDED"
            line_number = int(mr_comment_position['new_line'])
            filetype = "TO"
        elif is_newline and is_oldline:
            # both lines present - comment to remained line
            linetype = "CONTEXT"
            line_number = int(mr_comment_position['old_line'])
            filetype = "FROM"
        # gathering body for request to BB API
        comment_body = {
            "text": comment_text,
            "severity": "NORMAL",
            "anchor": {
                "diffType": "EFFECTIVE",
                "path": mr_comment_position['new_path'],
                "lineType": linetype,
                "line": line_number,
                "fileType": filetype
            }
        }
        # if in GL MR comment old and new file names are not equal,
        # then it is renaming, and we need to send toBB old path
        if mr_comment_position['new_path'] != mr_comment_position['old_path']:
            comment_body["anchor"]["srcPath"] = mr_comment_position['old_path']
        return comment_body

    def __copy_comments_from_mr_to_pr(self, gl_mr, bb_pr_id):
        """
        Copies comments from GL repos' MR to BB repo's PR
        :param gl_mr: GL repo's MR
        :param bb_pr_id: BB repo's PR id
        :return:
        """
        # get discussion list for Gitlab's MR
        gl_mr_discussions = gl_mr.discussions.list(order_by='created_at', sort='asc', all=True)
        # going through discussion list
        for gl_mr_discussion in gl_mr_discussions:
            # nulling parent comment ID in PR for new MR's discussion
            pr_root_comment_id = None
            # going though comments in MR's discussion
            for mr_comment in gl_mr_discussion.attributes['notes']:
                # gathering comment's text
                author = mr_comment['author']['name']
                timestamp = parse(mr_comment['created_at']).strftime("%d.%m.%Y, %H:%M:%S")
                # checking for images, etc in Markdown text
                comment_text = self.__replace_markdown_links(mr_comment['body'])
                comment_text = f"Created by {author} \nOn {timestamp} \n{comment_text}"
                # creating comment in PR
                if pr_root_comment_id is not None:
                    # if comment has parent, then simply creating new comment disregarding it's type
                    self.__bitbucket_connection.add_pull_request_comment(
                        self.__repo_properties.bitbucket_project, self.__bitbucket_repo_name,
                        bb_pr_id, comment_text, pr_root_comment_id
                    )
                    continue
                # MR's comment with "DiffNote" type is comment to code
                if mr_comment['type'] != 'DiffNote':
                    # if not comment to code and has no parent, then just create
                    pr_comment = self.__bitbucket_connection.add_pull_request_comment(
                        self.__repo_properties.bitbucket_project, self.__bitbucket_repo_name,
                        bb_pr_id, comment_text, pr_root_comment_id
                    )
                    # and save new comment's id as PR's comment parent id
                    pr_root_comment_id = pr_comment["id"]
                    continue
                # If has no parent and it's comment to code, then:
                # generating BB API URL
                bb_api_url = self.__bitbucket_connection._url_pull_request_comments(
                    self.__repo_properties.bitbucket_project, self.__bitbucket_repo_name, bb_pr_id
                )
                # generating request body
                post_data = self.__get_comment_to_codeline_creation_request_data(mr_comment['position'], comment_text)
                # sending request
                pr_comment = self.__bitbucket_connection.post(bb_api_url, data=post_data)
                # and save new comment's id as PR's comment parent id
                pr_root_comment_id = pr_comment["id"]

    def __get_pr_label_creation_request_data(self, label_name) -> dict:
        """
        Creates PR label creation request data
        :param label_name: label name
        :return: request body
        """
        # getting list of existing in Gitlab's project labels
        gl_labels = self.__gitlab_project.labels.list(all=True)
        # in MR's labels list label color isn't stored, so it has to be gathered from project's labels list
        label_color = '#FF0000'
        for gl_label_with_info in gl_labels:
            if label_name == gl_label_with_info.name:
                label_color = gl_label_with_info.color
                # BitBucket labels can't be emojis
                # Gitlab labels can be emojis, so label name length will be 1 or 2 symbols
                # If so, using label description as name.
                # If description is empty, set name as "emoji
                if len(gl_label_with_info.name) <= 2:
                    label_name = gl_label_with_info.description if gl_label_with_info.description else 'emoji'
                # Gitlab's label color can be 'strange'. And #FFFFFF looks bad in BB
                if label_color.lower() == '#fff' or label_color.lower() == '#ffffff':
                    label_color = '#f0f0f0'
                break
        return {'name': label_name, 'color': label_color}

    def __copy_labels_from_mr_to_pr(self, gl_mr, bb_pr_id):
        """
        Copies labels (name and color) from Gitlab repo's MR to BitBucket repo's PR
        :param gl_mr: GL repo's MR
        :param bb_pr_id: BB repo's PR id
        :return:
        """
        # BitBucket API URL to Pull Request's labels
        bb_base_url = self.__repo_properties.main_params['bitbucket_api_url']
        bb_pr_labels_base_url = f"{bb_base_url}rest/io.reconquest.bitbucket.labels/1.0"
        bb_project_id = self._bitbucket_repo['project']['id']
        bb_repo_id = self._bitbucket_repo['id']
        bb_pr_labels_url = f"{bb_pr_labels_base_url}/{bb_project_id}/{bb_repo_id}/pull-requests/{bb_pr_id}"
        # getting existing PR's labels
        pr_labels = requests.get(bb_pr_labels_url, auth=self.__bb_requests_auth, verify=self.__ssl_verify,
                                 headers=self.__bb_rest_requests_headers).json()
        pr_labels_names = [pr_label['name'] for pr_label in pr_labels['labels']]
        # going through Gitlab MR's labels
        for gl_label in gl_mr.labels:
            # if label exists, skipping
            if gl_label in pr_labels_names:
                continue
            # if label not found in PR, creating
            bb_pr_new_label = requests.post(bb_pr_labels_url, data=self.__get_pr_label_creation_request_data(gl_label),
                                            auth=self.__bb_requests_auth, verify=self.__ssl_verify,
                                            headers=self.__bb_rest_requests_headers)
            if not 200 <= bb_pr_new_label.status_code < 300:
                log_mgs = "Error creating label for Pull Request! "
                log_mgs += f"BitBucket API response status code: {bb_pr_new_label.status_code}. "
                log_mgs += f"Error: {bb_pr_new_label.text}"
                self.__logger.critical(log_mgs)
                exit(1)

    def copy_merge_requests_from_gl_to_bb(self) -> bool:
        """
        Copies MRs from GL repo to BB repo
        :return: was MRs copied
        """
        if not self.__repo_properties.will_mrs_will_be_cloned:
            return False
        # This check looks like doing nothing, but it fills self.__bitbucket_repo if it is None,
        # just look into property realisation
        if self._bitbucket_repo is None:
            pass
        self.__logger.info('- Duplicating MRs...')
        # BitBucket PullRequests API url
        # bb_pr_api_url = self.__repo_properties.main_params["bitbucket_api_url"]
        # bb_pr_api_url += self.__bitbucket_connection._url_pull_requests(self.__repo_properties.bitbucket_project,
        #                                                                 self.__bitbucket_repo_name)
        # getting Gitlab repo MRs list
        gl_mrs = self.__gitlab_project.mergerequests.list(state='opened', all=True, order_by='created_at', sort='asc')
        # getting BitBucket repo PRs list
        bb_prs = list(self.__bitbucket_connection.get_pull_requests(self.__repo_properties.bitbucket_project,
                                                                    self.__bitbucket_repo_name,
                                                                    state='OPEN', order='newest', limit=0, start=0))
        # going through MRs list
        for gl_mr in gl_mrs:
            # If PR already exists, storing it
            for bb_pr in bb_prs.copy():
                if bb_pr['title'] == gl_mr.title:
                    new_bb_pr = bb_pr
                    break
            # if PR not found, create it and store
            else:
                new_bb_pr = self.__create_bitbucket_pull_request(gl_mr)
                if new_bb_pr is None:
                    continue
                self.__copy_comments_from_mr_to_pr(gl_mr, new_bb_pr['id'])
            # copying labels from MR to PR
            self.__copy_labels_from_mr_to_pr(gl_mr, new_bb_pr['id'])
        return True

    def __backup_jenkins_job(self, job_config, job_folder: str, repo_name: str) -> bool:
        """
        Backs up Jenkins job's config
        :param job_config: Jenkins job config
        :param job_folder: job folder name
        :param repo_name: job name
        :return: was job backed up
        """
        if not self.__repo_properties.will_jenkins_jobs_be_backed_up:
            return False
        if len(self.__repo_properties.main_params['jenkins_backup_path']) == 0:
            self.__logger.critical('Folder for Jenkins jobs backups not set!')
            exit(1)
        self.__logger.info('-- Backing up jobs')
        # getting folder name with target job and getting path to backup folder
        folder_name = job_folder.split('/')[0]
        file_name = f"{repo_name}_config.xml"
        backup_folder = f"{self.__repo_properties.main_params['jenkins_backup_path']}{folder_name}"
        # creating backup folder
        self.__exec_os_cmd(f'mkdir -p {backup_folder}')
        backup_folder = os.popen(f'cd {backup_folder} && pwd').read()[:-1]
        backup_fullpath = f"{backup_folder}/{file_name}"
        # if file with target name exists, delete it
        if os.path.exists(backup_fullpath):
            os.remove(backup_fullpath)
        # writing current config to file
        with open(backup_fullpath, "w+") as text_file:
            text_file.write(job_config)
        return True

    def change_jenkins_jobs(self, bb_repo_url_type: str = 'ssh',
                            jenkins_job_name_pattern_addon: str = JENKINS_JOB_NAME_PATTERN_ADDON,
                            jenkins_folder_name_pattern: str = JENKINS_FOLDER_NAME_PATTERN) -> bool:
        """
        Changes repo url in jenkins jobs.
        This method is highly specific for author's environment!
        :param bb_repo_url_type: url type to BitBucket repo (ssh or http)
        :param jenkins_job_name_pattern_addon: job name has to start with repo name
                                               and this addon - f'{repo_name}{addon}'
        :param jenkins_folder_name_pattern: folder name pattern in which job has to be located
        :return:
        """
        if not self.__repo_properties.will_jenkins_jobs_will_be_changed:
            return False
        self.__logger.info(f'- Changing Jenkins jobs for repo {self.__gitlab_project.path}')
        jenkins_job_name_pattern = f'{self.__gitlab_project.path}{jenkins_job_name_pattern_addon}'
        for job in self.__jenkins_connection.get_jobs(folder_depth=1):
            # checking if job in target folder and job's name starts with repo name
            is_right_job = jenkins_folder_name_pattern.lower() in job['fullname'].lower() and \
                           job['name'].lower().startswith(jenkins_job_name_pattern.lower())
            if not is_right_job:
                continue
            # making job copy, it's backup variant
            # self.__jenkins_connection.copy_job(job['fullname'], jobname_bkp)
            xml_job_config = self.__jenkins_connection.get_job_config(job['fullname'])
            self.__backup_jenkins_job(xml_job_config, job['fullname'], job['name'])
            # parsing XML config
            xml_root = ElT.fromstring(xml_job_config)
            # in string parameters looking for those which has in tag <name> value "PROJECT_GIT"
            for parameter in xml_root.iter('hudson.model.StringParameterDefinition'):
                if parameter.find('name').text == 'PROJECT_GIT':
                    gl_repo_url = parameter.find('defaultValue').text  # storing old URL
                    # creating param's description and putting both old and new URL there
                    desc = f"{self.__bitbucket_repo_urls[bb_repo_url_type]} --- {gl_repo_url}"
                    parameter.find('description').text = desc
                    # changing default value
                    parameter.find('defaultValue').text = self.__bitbucket_repo_urls[bb_repo_url_type]
            # converting XML-object to sting
            new_conf = ElT.tostring(xml_root, encoding='utf8').decode()
            # writing new config to job
            self.__logger.info(f'-- Reconfiguring job {job["fullname"]}')
            self.__jenkins_connection.reconfig_job(job['fullname'], new_conf)  # this method has no return
        return True

    def clear_tmp(self) -> bool:
        """
        Deletes local repo clone
        :return: was local tmp dir cleared
        """
        if not self.__repo_properties.will_local_tmp_be_deleted:
            return False
        self.__logger.info('- Cleaning local traces...')
        self.__exec_os_cmd(f'rm -rf {self.__repo_properties.main_params["tmp_folder"]}')

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
