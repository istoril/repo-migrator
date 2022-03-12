import gitlab


class GitlabConnection:
    def __init__(self, api_url: str, token: str, logger, ssl_verify: bool = True):
        """
        Connection to Gitlab API and getting data
        :param api_url: base gitlab url (w/o api/v4)
        :param token: gitlab user's access token
        :param ssl_verify: if SSL cert needs to be verified (for example, False if self-signed)
        """
        self.__logger = logger
        self.__url = api_url
        self.__token = token
        try:
            self.__connection = gitlab.Gitlab(api_url, ssl_verify=ssl_verify, private_token=token)
        except Exception as err:
            self.__logger.critical(f"Problem connecting to Gitlab: {err}")
            exit(1)
        self.__connection.auth()

    def __enter__(self):
        return self

    def get_projects_from_group(self, group_name: str, project_name: str = None) -> list:
        """
        Get list of Gitlab projects in group by name (case-insensitive)
        :param group_name: name of Gitlab group
        :param project_name: name of Gitlab project
        :return: list of projects (properties example: project.path, project.id)
        """
        # Had to get all groups and then select one with name needed because method that returns group works with ID.
        # ".list" method has "search" param, but using it on prod Gitlab with many groups and projects got wrong results
        all_groups = self.__connection.groups.list(all=True)
        for group in all_groups:
            if group.full_path.lower() == group_name.lower():
                found_group = group
                break
        else:
            self.__logger.warning(f"Group {group_name} not found in Gitlab")
            return []
        if project_name is None:
            projects = []
            for project in found_group.projects.list(all=True):
                projects.append(self.__connection.projects.get(project.id))
            self.__logger.info(f"Gitlab group {group_name} projects info successfully collected")
            return projects
        self.__logger.info(f"Gitlab project {group_name}/{project_name} info successfully collected")
        return [self.__connection.projects.get(f'{group_name}/{project_name}')]

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __del__(self):
        del self.__connection

# class GitlabProject:
#     """Wrapper for Gitlab Project object to simplify some calls"""
#     def __init__(self, project):
#         self.__project = project
