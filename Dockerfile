# Image to run Repo.Migrate utility in k8s
FROM python:3.9-alpine

ARG GIT_MIGRATION_SSL_VERIFY=false
ARG ARTIFACTORY_URL="http://artifactory.efr.open.ru/api/pypi/pypi/simple"
ARG home_user="runuser"
ENV home_dir="/home/${home_user}"
ENV gitlab_migrate_docker=1

# Installing tools required for migrate repos
RUN apk add --no-cache git openssh

# PREPS
# Switching home dir
WORKDIR ${home_dir}
# Adding user
RUN adduser --disabled-password -s /bin/sh ${home_user}
# Switching to user
USER ${home_user}
# Make git ignore self-signed/etc SSL-certificates
RUN git config --global http.sslVerify ${GIT_MIGRATION_SSL_VERIFY}
# Making dir for ssh
RUN mkdir -p ${home_dir}/.ssh

# Installing packages required
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url ${ARTIFACTORY_URL} \
    --trusted-host artifactory.efr.open.ru -r requirements.txt

# Copying script and config
COPY *.py .
COPY conf_schema.json .
COPY migration_config.yaml .
COPY logging_conf.yaml .

# Running script
CMD ["python", "./main.py"]
# If we need container to stay
# CMD exec /bin/sh -c "trap : TERM INT; sleep 9999999999d & wait"
