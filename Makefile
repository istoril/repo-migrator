CONTAINER_NAME := gitlab-migrate
DOCKER_REGISTRY := docker.artifactory.efr.open.ru
MKFILE_PATH := $(abspath $(lastword $(MAKEFILE_LIST)))
CURRENT_DIR := $(shell pwd)
IMG_VER := $(shell cat ${CURRENT_DIR}/VERSION)
DOCKERFILE := ${CURRENT_DIR}/Dockerfile
K8S := ${CURRENT_DIR}/manifests/
NAMESPACE := gitlab-migrate

.DEFAULT_GOAL: usage

.PHONY: usage

usage:
	@echo "Use one of following commands:"
	@echo "\tmake all - build and push Gitlab-Migrate Utility image"
	@echo "\tmake build - build Gitlab-Migrate Utility image"
	@echo "\tmake push - push Gitlab-Migrate Utility image"
	@echo "\tmake apply - deploy Gitlab-Migrate Utility to k8s cluster"
	@echo "\tmake delete - delete Gitlab-Migrate Utility from k8s cluster"
	@echo "\tmake debug - using configuration:"

.PHONY: debug

debug:
	@echo "Using following configuration:"
	@echo "\tMKFILE_PATH: ${CONTAINER_NAME}"
	@echo "\tDOCKER_REGISTRY: ${DOCKER_REGISTRY}"
	@echo "\tMKFILE_PATH: ${MKFILE_PATH}"
	@echo "\tCURRENT_DIR: ${CURRENT_DIR}"
	@echo "\tIMG_VER: ${IMG_VER}"
	@echo "\tDOCKERFILE: ${DOCKERFILE}"
	@echo "\tK8S: ${K8S}"
	@echo "\tNAMESPACE: ${NAMESPACE}"

all: build push

build:
	docker build --pull -f ${DOCKERFILE} . -t ${DOCKER_REGISTRY}/${CONTAINER_NAME}:${IMG_VER}

push:
	docker push ${DOCKER_REGISTRY}/${CONTAINER_NAME}:${IMG_VER}

apply:
	kubectl -n ${NAMESPACE} apply -R -f ${K8S}

delete:
	kubectl delete namespaces ${NAMESPACE}
