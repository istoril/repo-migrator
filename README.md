# Repo Migrator

Utility for repositories migration from Gitlab to Bitbucket

## Description
Utility for full migration of repos from Gitlab to Bitbucket. For that purpose utility does:
1. Creates repo in BitBucket
2. Makes Gitlab repo readonly (archives)
3. Clones repo from Gitlab to Bitbucket
4. Enables mirroring from Gitlab to Bitbucket
5. Copies MRs from Gitlab to BitBucket (with discussions and labels)
6. Changes repo link in Jenkins jobs
7. Clears local traces of using utility

Each step can be turned on/off in config

### Structure
main.py - entrypoint
config_loader.py - validates and parses config
gitlab_connector.py - connects to Gitlab and gets required projects 
repository_cloner.py - the class that migrates repos from Gitlab to BitBucket
migration_config.yaml - config example
conf_schema.json - json schema for config validation
logging_conf.yaml - config for Logger
Dockerfile - for running this tool as k8s cronjob, not tested as just docker container
Makefile - wrapper for not entering full commands every time you need to rebuild image, etc
manifests - folder with k8s-cronjob manifests

## Makefile
1. make build - build docker image
1. make push - push docker image to docker hub
1. make all - build and push docker image to hub
1. make apply - kubectl apply *.yaml files from "manifests" folder

## ENV params
GITLAB_TOKEN
BITBUCKET_TOKEN
JENKINS_TOKEN
GIT_MIGRATION_SSL_VERIFY - 1 or not set for True, anything else for False 
GIT_MIGRATION_LOG_LEVEL - DEBUG for debug level, anything else for info level
gitlab_migrate_docker - 1 if runs in Docker/k8s/etc, anything else for not

### Docker env params
home_user - username to run utility
s_home_dir - home dir for user
ssh-privatekey - private key for Gitlab and Bitbucket repos (same for both)
s_ssh_pub_key - public key for Gitlab and Bitbucket repos (same for both)
s_known_hosts - known_hosts file content

## Config file description
Utility gets passwords, tokens, etc from env params 

```yaml
# main properties
sGitlabApiUrl: 'https://gitlab.slurm.io/' # Gitlab API URL
sGitlabRepoUrl: 'ssh://git@gitlab.slurm.io:22/' # Gitlab ssh base url 
sBitbucketUrl: 'http://172.23.63.138:7990/' # BitBucket API URL
sLocalRootPath: '~/_git/_migration/' # path to folder with local repo clones
sUser: 'some_user' # default login
sBBUser: 'bb_user' # BitBucket login (sUser if not present)
sGitlabUser: 'gl_user' # Gitlab login (sUser if not present)
sJenkinsUser: 'jenkins_user' # Jenkins login (sUser if not present)
# default flags
bDefaultDeleteBBRepo: True # will BitBucket repo be deleted at start, if it already exists
bDefaultMirroring: True # enable Mirroring from Gitlab to BitBucket (default value for bMirroring)
bDefaultGitlabReadonly: False # Archive Gitlab repo (default value for bMakeGitlabRepoReadonly)
bDefaultChangeJenkinsJobs: False # change Jenkins jobs? (default value for bChangeJenkinsJobs)
bDefaultBackupJenkinsJobs: False # backup Jenkins jobs config? (default value for bBackupJenkinsJobs)
bDefaultCloning: True # will repo be cloned (default value for bClone)
bDefaultClear: True # delete local repo folder (default value for bClear)
bDefaultDuplicateMRs: True # will MRs will be copied (default value for bDuplicateMRs)
sDefaultWebhookName: 'tst-webhook' # name for BitBucket repo webhook (default value for sWebhookName)
sDefaultWebhookUrl: 'http://tst.org/tst_webhook' # BitBucket repo webhook URL (default value for sWebhookUrl)

# repos
repos:
  - sGitlabGroup: 'SomeGitlabGroup' # Gitlab group
    sGitlabProject: 'SomeGitlabProject' # Gitlab project
    sBitbucketProject: 'SomeBitbucketProject' # Bitbucket project
    sBitbucketPrefix: 'repo.name.prefix' # Bitbucket repo name prefix
    bMakeGitlabRepoReadonly: False # will Gitlab repo be archived
    bMirroring: False # will Mirroring from Gitlab to BitBucket be enabled
    bClone: True #  no clone (f.e. if Mirroring is enabled already)
    bClear: True # delete local folder with repo clones
    bChangeJenkinsJobs: False # will repo url in Jenkins jobs be changed
    bBackupJenkinsJobs: True # will Jenkins jobs config will be backed up
    bDuplicateMRs: False # will Merge Requests be copied to new repo in BitBucket
    sWebhookName: 'tst-webhook' # if webhook for BitBucket is needed, name for that webhook
    sWebhookUrl: 'http://some.webhook.url/webhook?some_id=' # if webhook for BitBucket is needed, url for that webhook
    sWebhookUrlParameter: 'some_params' # if webhook for BitBucket is needed, additional params for that webhook
```
