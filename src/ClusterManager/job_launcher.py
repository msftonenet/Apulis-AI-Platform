#!/usr/bin/env python

import json
import yaml
import os
import logging
import logging.config
import timeit
import functools
import time
import datetime
import base64
import multiprocessing
import hashlib

from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream
from kubernetes.stream.ws_client import ERROR_CHANNEL, STDERR_CHANNEL, STDOUT_CHANNEL

from prometheus_client import Histogram

import k8sUtils
from DataHandler import DataHandler
from job import Job, JobSchema
from pod_template import PodTemplate
from dist_pod_template import DistPodTemplate
from config import config

from cluster_manager import record
import jwt_authorization

logger = logging.getLogger(__name__)

# The config will be loaded from default location.
k8s_config.load_kube_config()
k8s_CoreAPI = client.CoreV1Api()
k8s_AppsAPI = client.AppsV1Api()

class DictToInstance:
    def __init__(self,dicts):
        self.dicts = dicts
    def __getattr__(self, item):
        res = self.dicts.get(item)
        if isinstance(res,dict):
            res = DictToInstance(res)
        return res

class JobDeployer:
    def __init__(self):
        self.k8s_CoreAPI = k8s_CoreAPI
        self.k8s_AppsAPI = k8s_AppsAPI
        self.namespace = "default"
        self.pretty = "pretty_example"

    @record
    def _create_pod(self, body):
        api_response = self.k8s_CoreAPI.create_namespaced_pod(
            namespace=self.namespace,
            body=body,
            pretty=self.pretty,
        )
        return api_response

    @record
    def _create_inferenceService(self, body):
        api_response = client.CustomObjectsApi().create_namespaced_custom_object(
            group="serving.kubeflow.org",
            version="v1alpha2",
            namespace="kfserving-pod",
            plural="inferenceservices",
            body=body)
        if isinstance(api_response,dict):
            return DictToInstance(api_response)
        return api_response

    @record
    def _delete_pod(self, name, grace_period_seconds=None):
        body = client.V1DeleteOptions()
        body.grace_period_seconds = grace_period_seconds
        api_response = self.k8s_CoreAPI.delete_namespaced_pod(
            name=name,
            namespace=self.namespace,
            pretty=self.pretty,
            body=body,
            grace_period_seconds=grace_period_seconds,
        )
        return api_response

    @record
    def _delete_inferenceService(self, name, grace_period_seconds=None):
        body = client.V1DeleteOptions()
        body.grace_period_seconds = grace_period_seconds
        api_response = client.CustomObjectsApi().delete_namespaced_custom_object(
            group="serving.kubeflow.org",
            version="v1alpha2",
            name=name,
            namespace=self.namespace,
            plural="inferenceservices",
            body=body)
        return api_response

    @record
    def _cleanup_pods_with_labels(self, label_selector):
        errors = []
        try:
            self.k8s_CoreAPI.delete_collection_namespaced_pod(
                self.namespace,
                pretty=self.pretty,
                label_selector=label_selector,
                )
        except ApiException as e:
            message = "Delete pods failed: {}".format(label_selector)
            logger.warning(message, exc_info=True)
            errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_configmap(self, label_selector):
        errors = []
        try:
            api_response = self.k8s_CoreAPI.delete_collection_namespaced_config_map(
                self.namespace,
                pretty=self.pretty,
                label_selector=label_selector,
                )
        except ApiException as e:
            message = "Delete configmap failed: {}".format(label_selector)
            logger.warning(message, exc_info=True)
            errors.append({"message": message, "exception": e})
        return errors

    @record
    def _create_deployment(self, body):
        api_response = self.k8s_AppsAPI.create_namespaced_deployment(
            namespace=self.namespace,
            body=body,
            pretty=self.pretty,
        )
        return api_response

    @record
    def _delete_deployment(self, name, grace_period_seconds=None):
        body = client.V1DeleteOptions()
        body.grace_period_seconds = grace_period_seconds
        api_response = self.k8s_AppsAPI.delete_namespaced_deployment(
            name=name,
            namespace=self.namespace,
            pretty=self.pretty,
            body=body,
            grace_period_seconds=grace_period_seconds,
        )
        return api_response

    @record
    def _create_service(self, body):
        api_response = self.k8s_CoreAPI.create_namespaced_service(
            namespace=self.namespace,
            body=body,
            pretty=self.pretty,
        )
        return api_response

    @record
    def _delete_service(self, name):
        api_response = self.k8s_CoreAPI.delete_namespaced_service(
            name=name,
            namespace=self.namespace,
            pretty=self.pretty,
            body=client.V1DeleteOptions(),
        )
        return api_response

    @record
    def _create_secret(self, body):
        api_response = self.k8s_CoreAPI.create_namespaced_secret(
            namespace=self.namespace,
            body=body,
            pretty=self.pretty,
        )
        return api_response

    @record
    def _delete_secret(self, name, grace_period_seconds=None):
        body = client.V1DeleteOptions()
        body.grace_period_seconds = grace_period_seconds
        api_response = self.k8s_CoreAPI.delete_namespaced_secret(
            name=name,
            namespace=self.namespace,
            pretty=self.pretty,
            body=body,
            grace_period_seconds=grace_period_seconds
        )
        return api_response

    @record
    def _cleanup_pods(self, pod_names, force=False):
        errors = []
        grace_period_seconds = 0 if force else None
        for pod_name in pod_names:
            try:
                self._delete_pod(pod_name, grace_period_seconds)
            except Exception as e:
                if isinstance(e, ApiException) and 404 == e.status:
                    return []
                message = "Delete pod failed: {}".format(pod_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_inferenceServices(self, inferenceService_names, force=False):
        errors = []
        grace_period_seconds = 0 if force else None
        for inferenceService_name in inferenceService_names:
            try:
                self._delete_inferenceService(inferenceService_name, grace_period_seconds)
            except Exception as e:
                if isinstance(e, ApiException) and 404 == e.status:
                    return []
                message = "Delete inferenceService failed: {}".format(inferenceService_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_services(self, services):
        errors = []
        for service in services:
            assert(isinstance(service, client.V1Service))
            try:
                service_name = service.metadata.name
                self._delete_service(service_name)
            except ApiException as e:
                message = "Delete service failed: {}".format(service_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_deployment(self, deployment_names, force=False):
        errors = []
        grace_period_seconds = 0 if force else None
        for deployment_name in deployment_names:
            try:
                self._delete_deployment(deployment_name, grace_period_seconds)
            except Exception as e:
                if isinstance(e, ApiException) and 404 == e.status:
                    return []
                message = "Delete pod failed: {}".format(deployment_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_secrets(self, secret_names, force=False):
        errors = []
        grace_period_seconds = 0 if force else None
        for secret_name in secret_names:
            try:
                self._delete_secret(secret_name, grace_period_seconds)
            except Exception as e:
                if isinstance(e, ApiException) and 404 == e.status:
                    return []
                message = "Deleting secret failed: {}".format(secret_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_secrets_with_labels(self, label_selector):
        errors = []
        try:
            self.k8s_CoreAPI.delete_collection_namespaced_secret(
                self.namespace,
                pretty=self.pretty,
                label_selector=label_selector
            )
        except ApiException as e:
            message = "Delete secrets failed: {}".format(label_selector)
            logging.warning(message, exc_info=True)
            errors.append({"message": message, "exception": e})
        return errors

    @record
    def create_pods(self, pods):
        # TODO instead of delete, we could check update existiong ones. During refactoring, keeping the old way.
        pod_names = [pod["metadata"]["name"] for pod in pods if pod["kind"] == "Pod"]
        self._cleanup_pods(pod_names)
        deployment_names = [pod["metadata"]["name"] for pod in pods if pod["kind"] == "Deployment"]
        self._cleanup_deployment(deployment_names)
        inferenceService_names = [pod["metadata"]["name"] for pod in pods if pod["kind"] == "InferenceService"]
        self._cleanup_inferenceServices(inferenceService_names)
        created = []
        for pod in pods:
            if pod["kind"] == "Pod":
                created_pod = self._create_pod(pod)
            elif pod["kind"] == "Deployment":
                created_pod = self._create_deployment(pod)
            elif pod["kind"] == "InferenceService":
                created_pod = self._create_inferenceService(pod)
            created.append(created_pod)
            logger.info("Create pod succeed: %s" % created_pod.metadata.name)
        return created

    @record
    def create_secrets(self, secrets):
        # Clean up secrets first
        secret_names = [secret["metadata"]["name"] for secret in secrets if secret["kind"] == "Secret"]
        logger.info("Trying to delete secrets %s" % secret_names)
        self._cleanup_secrets(secret_names)

        created = []
        for secret in secrets:
            created_secret = self._create_secret(secret)
            created.append(created_secret)
            logger.info("Creating secret succeeded: %s" % created_secret.metadata.name)
        return created

    @record
    def get_pods(self, field_selector="", label_selector=""):
        api_response = self.k8s_CoreAPI.list_namespaced_pod(
            namespace=self.namespace,
            pretty=self.pretty,
            field_selector=field_selector,
            label_selector=label_selector,
        )
        logger.debug("Get pods: {}".format(api_response))
        return api_response.items

    @record
    def _get_deployments(self, field_selector="", label_selector=""):
        api_response = self.k8s_AppsAPI.list_namespaced_deployment(
            namespace=self.namespace,
            pretty=self.pretty,
            field_selector=field_selector,
            label_selector=label_selector,
        )
        logger.debug("Get pods: {}".format(api_response))
        return api_response.items

    @record
    def _get_services_by_label(self, label_selector):
        api_response = self.k8s_CoreAPI.list_namespaced_service(
            namespace=self.namespace,
            pretty=self.pretty,
            label_selector=label_selector,
        )
        return api_response.items

    @record
    def get_secrets(self, field_selector="", label_selector=""):
        api_response = self.k8s_CoreAPI.list_namespaced_secret(
            namespace=self.namespace,
            pretty=self.pretty,
            field_selector=field_selector,
            label_selector=label_selector,
        )
        logger.debug("Get secrets: {}".format(api_response))
        return api_response.items

    @record
    def delete_job(self, job_id, force=False):
        label_selector = "run={}".format(job_id)

        # query inferenceservice
        dataHandler = DataHandler()
        job = dataHandler.GetInferenceJob(job_id)[0]
        inferenceService_names = [job["jobName"]]
        inferenceservice_errors = self._cleanup_inferenceServices(inferenceService_names)
        logger.info("deleting inferenceservices %s" % job_id)

        # query pods then delete
        pod_errors = self._cleanup_pods_with_labels(label_selector)
        logger.info("deleting pods %s" % label_selector)
        # query services then delete
        services = self._get_services_by_label(label_selector)
        service_errors = self._cleanup_services(services)

        deployments = self._get_deployments(label_selector=label_selector)
        deployment_names = [deployment.metadata.name for deployment in deployments]
        deployment_errors = self._cleanup_deployment(deployment_names, force)

        logger.info("deleting deployments %s" % ",".join(deployment_names))

        # query and delete secrets
        secrets = self.get_secrets(label_selector=label_selector)
        secret_names = [secret.metadata.name for secret in secrets]
        secret_errors = self._cleanup_secrets_with_labels(label_selector)
        logger.info("deleting secrets for %s" % label_selector)

        configmap_errors = self._cleanup_configmap(label_selector)

        errors = pod_errors + service_errors + deployment_errors + secret_errors + \
                configmap_errors + inferenceservice_errors
        return errors

    @record
    def pod_exec(self, pod_name, exec_command, timeout=60):
        """work as the command (with timeout): kubectl exec 'pod_name' 'exec_command'"""
        try:
            logger.info("Exec on pod {}: {}".format(pod_name, exec_command))
            client = stream(
                self.k8s_CoreAPI.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,
            )
            client.run_forever(timeout=timeout)

            err = yaml.full_load(client.read_channel(ERROR_CHANNEL))
            if err is None:
                return [-1, "Timeout"]

            if err["status"] == "Success":
                status_code = 0
            else:
                logger.debug("Exec on pod {} failed. cmd: {}, err: {}.".format(pod_name, exec_command, err))
                status_code = int(err["details"]["causes"][0]["message"])
            output = client.read_all()
            logger.info("Exec on pod {}, status: {}, cmd: {}, output: {}".format(pod_name, status_code, exec_command, output))
            return [status_code, output]
        except ApiException as err:
            logger.error("Exec on pod {} error. cmd: {}, err: {}.".format(pod_name, exec_command, err), exc_info=True)
            return [-1, err.message]


class InferenceServiceJobDeployer:
    def __init__(self):
        self.k8s_CoreAPI = k8s_CoreAPI
        self.k8s_AppsAPI = k8s_AppsAPI
        self.namespace = "kfserving-pod"
        self.pretty = "pretty_example"

    @record
    def _create_inferenceService(self, body):
        api_response = client.CustomObjectsApi().create_namespaced_custom_object(
            group="serving.kubeflow.org",
            version="v1alpha2",
            namespace=self.namespace,
            plural="inferenceservices",
            body=body)
        if isinstance(api_response,dict):
            return DictToInstance(api_response)
        return api_response

    @record
    def _delete_pod(self, name, grace_period_seconds=None):
        body = client.V1DeleteOptions()
        body.grace_period_seconds = grace_period_seconds
        api_response = self.k8s_CoreAPI.delete_namespaced_pod(
            name=name,
            namespace=self.namespace,
            pretty=self.pretty,
            body=body,
            grace_period_seconds=grace_period_seconds,
        )
        return api_response

    @record
    def _delete_inferenceService(self, name, grace_period_seconds=None):
        body = client.V1DeleteOptions()
        body.grace_period_seconds = grace_period_seconds
        api_response = client.CustomObjectsApi().delete_namespaced_custom_object(
            group="serving.kubeflow.org",
            version="v1alpha2",
            name=name,
            namespace=self.namespace,
            plural="inferenceservices",
            body=body)
        return api_response

    @record
    def _cleanup_pods_with_labels(self, label_selector):
        errors = []
        try:
            self.k8s_CoreAPI.delete_collection_namespaced_pod(
                self.namespace,
                pretty=self.pretty,
                label_selector=label_selector,
                )
        except ApiException as e:
            message = "Delete pods failed: {}".format(label_selector)
            logger.warning(message, exc_info=True)
            errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_configmap(self, label_selector):
        errors = []
        try:
            api_response = self.k8s_CoreAPI.delete_collection_namespaced_config_map(
                self.namespace,
                pretty=self.pretty,
                label_selector=label_selector,
                )
        except ApiException as e:
            message = "Delete configmap failed: {}".format(label_selector)
            logger.warning(message, exc_info=True)
            errors.append({"message": message, "exception": e})
        return errors

    @record
    def _create_deployment(self, body):
        api_response = self.k8s_AppsAPI.create_namespaced_deployment(
            namespace=self.namespace,
            body=body,
            pretty=self.pretty,
        )
        return api_response

    @record
    def _delete_deployment(self, name, grace_period_seconds=None):
        body = client.V1DeleteOptions()
        body.grace_period_seconds = grace_period_seconds
        api_response = self.k8s_AppsAPI.delete_namespaced_deployment(
            name=name,
            namespace=self.namespace,
            pretty=self.pretty,
            body=body,
            grace_period_seconds=grace_period_seconds,
        )
        return api_response

    @record
    def _create_service(self, body):
        api_response = self.k8s_CoreAPI.create_namespaced_service(
            namespace=self.namespace,
            body=body,
            pretty=self.pretty,
        )
        return api_response

    @record
    def _delete_service(self, name):
        api_response = self.k8s_CoreAPI.delete_namespaced_service(
            name=name,
            namespace=self.namespace,
            pretty=self.pretty,
            body=client.V1DeleteOptions(),
        )
        return api_response

    @record
    def _create_secret(self, body):
        api_response = self.k8s_CoreAPI.create_namespaced_secret(
            namespace=self.namespace,
            body=body,
            pretty=self.pretty,
        )
        return api_response

    @record
    def _delete_secret(self, name, grace_period_seconds=None):
        body = client.V1DeleteOptions()
        body.grace_period_seconds = grace_period_seconds
        api_response = self.k8s_CoreAPI.delete_namespaced_secret(
            name=name,
            namespace=self.namespace,
            pretty=self.pretty,
            body=body,
            grace_period_seconds=grace_period_seconds
        )
        return api_response

    @record
    def _cleanup_pods(self, pod_names, force=False):
        errors = []
        grace_period_seconds = 0 if force else None
        for pod_name in pod_names:
            try:
                self._delete_pod(pod_name, grace_period_seconds)
            except Exception as e:
                if isinstance(e, ApiException) and 404 == e.status:
                    return []
                message = "Delete pod failed: {}".format(pod_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_inferenceServices(self, inferenceService_names, force=False):
        errors = []
        grace_period_seconds = 0 if force else None
        for inferenceService_name in inferenceService_names:
            try:
                self._delete_inferenceService(inferenceService_name, grace_period_seconds)
            except Exception as e:
                if isinstance(e, ApiException) and 404 == e.status:
                    return []
                message = "Delete inferenceService failed: {}".format(inferenceService_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_services(self, services):
        errors = []
        for service in services:
            assert(isinstance(service, client.V1Service))
            try:
                service_name = service.metadata.name
                self._delete_service(service_name)
            except ApiException as e:
                message = "Delete service failed: {}".format(service_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_deployment(self, deployment_names, force=False):
        errors = []
        grace_period_seconds = 0 if force else None
        for deployment_name in deployment_names:
            try:
                self._delete_deployment(deployment_name, grace_period_seconds)
            except Exception as e:
                if isinstance(e, ApiException) and 404 == e.status:
                    return []
                message = "Delete pod failed: {}".format(deployment_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_secrets(self, secret_names, force=False):
        errors = []
        grace_period_seconds = 0 if force else None
        for secret_name in secret_names:
            try:
                self._delete_secret(secret_name, grace_period_seconds)
            except Exception as e:
                if isinstance(e, ApiException) and 404 == e.status:
                    return []
                message = "Deleting secret failed: {}".format(secret_name)
                logger.warning(message, exc_info=True)
                errors.append({"message": message, "exception": e})
        return errors

    @record
    def _cleanup_secrets_with_labels(self, label_selector):
        errors = []
        try:
            self.k8s_CoreAPI.delete_collection_namespaced_secret(
                self.namespace,
                pretty=self.pretty,
                label_selector=label_selector
            )
        except ApiException as e:
            message = "Delete secrets failed: {}".format(label_selector)
            logging.warning(message, exc_info=True)
            errors.append({"message": message, "exception": e})
        return errors

    @record
    def create_pods(self, pods):
        # TODO instead of delete, we could check update existiong ones. During refactoring, keeping the old way.
        pod_names = [pod["metadata"]["name"] for pod in pods if pod["kind"] == "Pod"]
        self._cleanup_pods(pod_names)
        deployment_names = [pod["metadata"]["name"] for pod in pods if pod["kind"] == "Deployment"]
        self._cleanup_deployment(deployment_names)
        inferenceService_names = [pod["metadata"]["name"] for pod in pods if pod["kind"] == "InferenceService"]
        self._cleanup_inferenceServices(inferenceService_names)
        created = []
        for pod in pods:
            if pod["kind"] == "Pod":
                created_pod = self._create_pod(pod)
            elif pod["kind"] == "Deployment":
                created_pod = self._create_deployment(pod)
            elif pod["kind"] == "InferenceService":
                created_pod = self._create_inferenceService(pod)
            created.append(created_pod)
            logger.info("Create pod succeed: %s" % created_pod.metadata.name)
        return created

    @record
    def create_secrets(self, secrets):
        # Clean up secrets first
        secret_names = [secret["metadata"]["name"] for secret in secrets if secret["kind"] == "Secret"]
        logger.info("Trying to delete secrets %s" % secret_names)
        self._cleanup_secrets(secret_names)

        created = []
        for secret in secrets:
            created_secret = self._create_secret(secret)
            created.append(created_secret)
            logger.info("Creating secret succeeded: %s" % created_secret.metadata.name)
        return created

    @record
    def get_pods(self, field_selector="", label_selector=""):
        api_response = self.k8s_CoreAPI.list_namespaced_pod(
            namespace=self.namespace,
            pretty=self.pretty,
            field_selector=field_selector,
            label_selector=label_selector,
        )
        logger.debug("Get pods: {}".format(api_response))
        return api_response.items

    @record
    def _get_deployments(self, field_selector="", label_selector=""):
        api_response = self.k8s_AppsAPI.list_namespaced_deployment(
            namespace=self.namespace,
            pretty=self.pretty,
            field_selector=field_selector,
            label_selector=label_selector,
        )
        logger.debug("Get pods: {}".format(api_response))
        return api_response.items

    @record
    def _get_services_by_label(self, label_selector):
        api_response = self.k8s_CoreAPI.list_namespaced_service(
            namespace=self.namespace,
            pretty=self.pretty,
            label_selector=label_selector,
        )
        return api_response.items

    @record
    def get_secrets(self, field_selector="", label_selector=""):
        api_response = self.k8s_CoreAPI.list_namespaced_secret(
            namespace=self.namespace,
            pretty=self.pretty,
            field_selector=field_selector,
            label_selector=label_selector,
        )
        logger.debug("Get secrets: {}".format(api_response))
        return api_response.items

    @record
    def delete_job(self, job_id, force=False):
        label_selector = "run={}".format(job_id)

        # query inferenceservice
        dataHandler = DataHandler()
        job = dataHandler.GetInferenceJob(job_id)[0]
        inferenceService_names = ["ifs-"+job["jobId"]]
        inferenceservice_errors = self._cleanup_inferenceServices(inferenceService_names)
        logger.info("deleting inferenceservices %s" % job_id)

        # query pods then delete
        pod_errors = self._cleanup_pods_with_labels(label_selector)
        logger.info("deleting pods %s" % label_selector)
        # query services then delete
        services = self._get_services_by_label(label_selector)
        service_errors = self._cleanup_services(services)

        deployments = self._get_deployments(label_selector=label_selector)
        deployment_names = [deployment.metadata.name for deployment in deployments]
        deployment_errors = self._cleanup_deployment(deployment_names, force)

        logger.info("deleting deployments %s" % ",".join(deployment_names))

        # query and delete secrets
        secrets = self.get_secrets(label_selector=label_selector)
        secret_names = [secret.metadata.name for secret in secrets]
        secret_errors = self._cleanup_secrets_with_labels(label_selector)
        logger.info("deleting secrets for %s" % label_selector)

        configmap_errors = self._cleanup_configmap(label_selector)

        errors = pod_errors + service_errors + deployment_errors + secret_errors + \
                configmap_errors + inferenceservice_errors
        return errors

    @record
    def pod_exec(self, pod_name, exec_command, timeout=60):
        """work as the command (with timeout): kubectl exec 'pod_name' 'exec_command'"""
        try:
            logger.info("Exec on pod {}: {}".format(pod_name, exec_command))
            client = stream(
                self.k8s_CoreAPI.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,
            )
            client.run_forever(timeout=timeout)

            err = yaml.full_load(client.read_channel(ERROR_CHANNEL))
            if err is None:
                return [-1, "Timeout"]

            if err["status"] == "Success":
                status_code = 0
            else:
                logger.debug("Exec on pod {} failed. cmd: {}, err: {}.".format(pod_name, exec_command, err))
                status_code = int(err["details"]["causes"][0]["message"])
            output = client.read_all()
            logger.info("Exec on pod {}, status: {}, cmd: {}, output: {}".format(pod_name, status_code, exec_command, output))
            return [status_code, output]
        except ApiException as err:
            logger.error("Exec on pod {} error. cmd: {}, err: {}.".format(pod_name, exec_command, err), exc_info=True)
            return [-1, err.message]

class JobRole(object):
    MARK_ROLE_READY_FILE = "/pod/running/ROLE_READY"

    @staticmethod
    def get_job_roles(job_id):
        dataHandler = DataHandler()
        jobType = dataHandler.GetJobTextField(job_id, "jobType")
        if jobType == "InferenceJob":
            job_deployer = InferenceServiceJobDeployer()
        else:
            job_deployer = JobDeployer()
        pods = job_deployer.get_pods(label_selector="run={}".format(job_id))

        job_roles = []
        for pod in pods:
            pod_name = pod.metadata.name
            if "distRole" in pod.metadata.labels:
                role = pod.metadata.labels["distRole"]
            else:
                role = "master"
            job_role = JobRole(role, pod_name, pod)
            job_roles.append(job_role)
        return job_roles

    def __init__(self, role_name, pod_name, pod):
        self.role_name = role_name
        self.pod_name = pod_name
        self.pod = pod

    # will query api server if refresh is True
    def status(self, refresh=False):
        """
        Return role status in ["NotFound", "Pending", "Running", "Succeeded", "Failed", "Unknown"]
        It's slightly different from pod phase, when pod is running:
            CONTAINER_READY -> WORKER_READY -> JOB_READY (then the job finally in "Running" status.)
        """
        # pod-phase: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-phase
        # node condition: https://kubernetes.io/docs/concepts/architecture/nodes/#condition
        if refresh:
            deployer = JobDeployer()
            pods = deployer.get_pods(field_selector="metadata.name={}".format(self.pod_name))
            logger.debug("Pods: {}".format(pods))
            if len(pods) < 1:
                return "NotFound"

            assert(len(pods) == 1)
            self.pod = pods[0]

        phase = self.pod.status.phase

        # !!! Pod is running, doesn't mean "Role" is ready and running.
        if phase == "Running":
            # Found that phase won't turn into "Unkonwn" even when we get 'unknown' from kubectl
            if self.pod.status.reason == "NodeLost":
                return "Unknown"

            # Starting from v1.13, TaintBasedEvictions are enabled by default. NodeLost no longer
            # exists. Use deletionTimstamp to signal node lost.
            # See below for details:
            # https://github.com/kubernetes/kubernetes/issues/72226
            # https://kubernetes.io/docs/concepts/configuration/taint-and-toleration/
            if self.pod.metadata.deletion_timestamp is not None and self.pod.metadata.labels["type"] != "InferenceService":
                logger.info("pod %s has deletion_timestamp %s. Marking pod as Unknown." %
                            (self.pod_name, self.pod.metadata.deletion_timestamp))
                return "Unknown"

            # Check if the user command had been ran.
            if not self._is_role_ready():
                return "Pending"

        elif phase == "Failed":
            if self.pod.status.reason == "UnexpectedAdmissionError":
                return "Restart"

        return phase

    def pod_restricted_details(self):
        detail = {
            "node_name": self.pod.spec.node_name,
            "host_ip": self.pod.status.host_ip,
            "pod_ip": self.pod.status.pod_ip
        }
        return detail

    def pod_details(self):
        return self.pod

    def _is_file_exist(self, file):
        deployer = JobDeployer()
        status_code, _ = deployer.pod_exec(self.pod_name, ["/bin/sh", "-c", "ls -lrt {}".format(file)])
        return status_code == 0

    def _is_role_ready(self):
        if self.pod.metadata.labels["type"] == "InferenceService":
            for status in self.pod.status.container_statuses:
                if not status.ready:
                    return False
            return True

        for container in self.pod.spec.containers:
            if container.name == self.pod_name and container.readiness_probe is not None:
                for status in self.pod.status.container_statuses:
                    if status.name == self.pod_name:
                        logger.info("pod %s have readiness_probe result", self.pod_name)
                        return status.ready
        # no readiness_probe defined, fallback to old way
        return self._is_file_exist(JobRole.MARK_ROLE_READY_FILE)


# Interface class for managing life time of job
class Launcher(object):
    def __init__(self):
        pass

    def start(self):
        pass

    def submit_job(self, job_desc):
        pass

    def kill_job(self, job_id, desired_state="killed"):
        pass

def get_job_status_detail(job):
    if "jobStatusDetail" not in job:
        return None

    job_status_detail = job["jobStatusDetail"]
    if job_status_detail is None:
        return job_status_detail

    if not isinstance(job_status_detail, list):
        job_status_detail = base64.b64decode(job_status_detail)
        job_status_detail = json.loads(job_status_detail)
    return job_status_detail


def job_status_detail_with_finished_time(job_status_detail, status, msg=""):
    # This method is called when a job succeeds/fails/is killed/has an error

    # job_status_detail must be None or a list
    if (job_status_detail is not None) and (not isinstance(job_status_detail, list)):
        return job_status_detail

    # Force adding an item for empty detail
    if (job_status_detail is None) or (len(job_status_detail) == 0):
        job_status_detail = [{}]

    finished_at = k8sUtils.localize_time(datetime.datetime.now())
    new_job_status_detail = []
    # Override finishedAt for all pods if absent
    for pod_status_detail in job_status_detail:
        # Mark started time the same as finished time for a fast finishing job
        if "startedAt" not in pod_status_detail:
            pod_status_detail["startedAt"] = finished_at

        if "finishedAt" not in pod_status_detail:
            pod_status_detail["finishedAt"] = finished_at

        pod_status_detail["message"] = "{} at {}. {}".format(status, finished_at, msg)
        new_job_status_detail.append(pod_status_detail)

    return new_job_status_detail


class PythonLauncher(Launcher):
    def __init__(self, pool_size=3):
        self.processes = []
        self.queue = None
        self.pool_size = pool_size
        # items in queue should be tuple of 3 elements: (function name, args, kwargs)

    def start(self):
        if len(self.processes) == 0:
            self.queue = multiprocessing.JoinableQueue()

            for i in range(self.pool_size):
                p = multiprocessing.Process(target=self.run,
                        args=(self.queue,), name="py-launcher-" + str(i))
                self.processes.append(p)
                p.start()

    def wait_tasks_done(self):
        self.queue.join()

    def _all_pods_not_existing(self, job_id):
        job_deployer = JobDeployer()
        job_roles = JobRole.get_job_roles(job_id)
        statuses = [job_role.status() for job_role in job_roles]
        logger.info("Job: {}, status: {}".format(job_id, statuses))
        return all([status == "NotFound" for status in statuses])

    def submit_job(self, job):
        self.queue.put(("submit_job", (job,), {}))

    def submit_job_impl(self, job):
        
        # check if existing any pod with label: run=job_id
        assert("jobId" in job)
        job_id = job["jobId"]

        job["cluster"] = config
        job_object, errors = JobSchema().load(job)

        # TODO assert job_object is a Job
        assert isinstance(job_object, Job), "job_object is not of Job, but " + str(type(job_object))
        job_object.params = json.loads(base64.b64decode(job["jobParams"]))

        if not self._all_pods_not_existing(job_id):
            logger.warning("Waiting until previously pods are cleaned up! Job {}".format(job_id))
            if  job_object.params["jobtrainingtype"] == "InferenceJob":
                job_deployer = InferenceServiceJobDeployer()
            else:
                job_deployer = JobDeployer()
            errors = job_deployer.delete_job(job_id, force=True)
            if errors:
                logger.warning("Force delete job {}: {}".format(job_id, errors))
            return

        ret = {}
        dataHandler = DataHandler()

        try:
            # TODO refine later
            # before resubmit the job, reset the endpoints
            # update all endpoint to status 'pending', so it would restart when job is ready
            endpoints = dataHandler.GetJobEndpoints(job_id)
            for endpoint_id, endpoint in endpoints.items():
                endpoint["status"] = "pending"
                logger.info("Reset endpoint status to 'pending': {}".format(endpoint_id))
                dataHandler.UpdateEndpoint(endpoint)

            # inject gid, uid and user
            # TODO it should return only one entry
            user_info = dataHandler.GetIdentityInfo(job_object.params["userName"])[0]
            job_object.params["gid"] = user_info["gid"]
            job_object.params["uid"] = user_info["uid"]
            job_object.params["user"] = job_object.get_alias()

            if "job_token" not in job_object.params:
                if "master_token" in config and config["master_token"] is not None and "userName" in job_object.params:
                    job_object.params["job_token"] = hashlib.md5(job_object.params["userName"]+":"+config["master_token"]).hexdigest()
                else:
                    job_object.params["job_token"] = "tryme2017"

            if "env" in job_object.params:
                job_object.params["envs"]=job_object.params["env"]

            if "envs" not in job_object.params:
                job_object.params["envs"] =[]

            if "codePath" in job_object.params:
                job_object.params["envs"].append({"name": "CODE_PATH", "value": job_object.params["codePath"]})  
            else:
                pass    

            if "outputPath" in job_object.params:
                job_object.params["envs"].append({"name": "OUTPUT_PATH", "value": job_object.params["outputPath"]})  
            else:
                pass    

            job_object.params["envs"].append({"name": "DLTS_JOB_TOKEN", "value": job_object.params["job_token"]})              
            job_object.params["envs"].append({"name": "IDENTITY_TOKEN", "value": jwt_authorization.create_jwt_token_with_message(
                                              {"userName":job_object.params["userName"],"uid":user_info["uid"]}
            )})

            ### add support for job group
            if "jobGroup" in job:
               job_object.params["envs"].append({"name":"DLWS_JOB_GROUP","value":job["jobGroup"]})

            ### add support for job tracking
            if "track" in job_object.params and int(job_object.params["track"]) == 1:
               job_object.params["envs"].append({"name":"DLWS_JOB_TRACK","value":"1"})
               job_object.params["envs"].append({"name":"MLFLOW_TRACKING_URI","value":"http://mlflow.default:9010"})
               job_object.params["envs"].append({"name":"MLFLOW_EXPERIMENT_NAME","value": "ai_arts_" + job["jobGroup"]})
               job_object.params["envs"].append({"name":"MLFLOW_RUN_ID","value":job_id})


            enable_custom_scheduler = job_object.is_custom_scheduler_enabled()
            blobfuse_secret_template = job_object.get_blobfuse_secret_template()
            image_pull_secret_template = job_object.get_image_pull_secret_template()
            secret_templates = {
                "blobfuse": blobfuse_secret_template,
                "imagePull": image_pull_secret_template
            }
            
            if job_object.params["jobtrainingtype"] == "RegularJob":
                pod_template = PodTemplate(job_object.get_template(),
                                           enable_custom_scheduler=enable_custom_scheduler,
                                           secret_templates=secret_templates)
            elif job_object.params["jobtrainingtype"] == "PSDistJob":
                pod_template = DistPodTemplate(job_object.get_template(),
                                               secret_templates=secret_templates)
            elif job_object.params["jobtrainingtype"] == "InferenceJob":
                pod_template = PodTemplate(job_object.get_inference_pod_template(),
                                           deployment_template=job_object.get_deployment_template(),
                                           enable_custom_scheduler=False,
                                           secret_templates=secret_templates)
            else:
                dataHandler.SetJobError(job_object.job_id, "ERROR: invalid jobtrainingtype: %s" % job_object.params["jobtrainingtype"])
                dataHandler.Close()
                return False

            pods, error = pod_template.generate_pods(job_object)
            if error:
                logger.error("submit job error %s" % error)
                dataHandler.SetJobError(job_object.job_id, "ERROR: %s" % error)
                dataHandler.Close()
                return False

            job_description = "\n---\n".join([yaml.dump(pod) for pod in pods])
            job_description_path = "jobfiles/" + time.strftime("%y%m%d") + "/" + job_object.job_id + "/" + job_object.job_id + ".yaml"
            local_jobDescriptionPath = os.path.realpath(os.path.join(config["storage-mount-path"], job_description_path))

            if not os.path.exists(os.path.dirname(local_jobDescriptionPath)):
                os.makedirs(os.path.dirname(local_jobDescriptionPath))

            with open(local_jobDescriptionPath, 'w') as f:
                f.write(job_description)

            secrets = pod_template.generate_secrets(job_object)

            if job_object.params["jobtrainingtype"] == "InferenceJob":
                job_deployer = InferenceServiceJobDeployer()
            else:
                job_deployer = JobDeployer()

            secrets = job_deployer.create_secrets(secrets)
            ret["output"] = "Created secrets: {}. ".format([secret.metadata.name for secret in secrets])
            pods = job_deployer.create_pods(pods)
            ret["output"] += "Created pods: {}".format([pod.metadata.name for pod in pods])


            ret["jobId"] = job_object.job_id

            jobMeta = {}
            jobMeta["jobDescriptionPath"] = job_description_path
            jobMeta["jobPath"] = job_object.job_path
            jobMeta["workPath"] = job_object.work_path
            # the command of the first container
            if pods[0].kind == "Pod":
                jobMeta["LaunchCMD"] = pods[0].spec.containers[0].command

            jobMetaStr = base64.b64encode(json.dumps(jobMeta))

            dataFields = {
                "jobStatus": "scheduling",
                "jobDescriptionPath": job_description_path,
                "jobDescription": base64.b64encode(job_description),
                "lastUpdated": datetime.datetime.now().isoformat(),
                "jobMeta": jobMetaStr
            }
            conditionFields = {"jobId": job_object.job_id}
            dataHandler.UpdateJobTextFields(conditionFields, dataFields)

        except Exception as e:
            logger.error("Submit job failed: %s" % job, exc_info=True)
            ret["error"] = str(e)
            retries = dataHandler.AddandGetJobRetries(job["jobId"])

            if retries >= 5:
                detail = get_job_status_detail(job)
                detail = job_status_detail_with_finished_time(detail, "error", "Server error in job submission,"+str(e))

                dataFields = {
                    "jobStatus": "error",
                    "errorMsg": "Cannot submit job!" + str(e),
                    "jobStatusDetail": base64.b64encode(json.dumps(detail))
                }
                conditionFields = {"jobId": job["jobId"]}
                dataHandler.UpdateJobTextFields(conditionFields, dataFields)
                # Try to clean up the job
                try:
                    job_deployer = JobDeployer()
                    job_deployer.delete_job(job_id, force=True)
                    logger.info("Cleaning up job %s succeeded after %d retries of job submission" % (job["jobId"], retries))
                except:
                    logger.warning("Cleaning up job %s failed after %d retries of job submission" % (job["jobId"], retries))

        dataHandler.Close()
        return ret

    def kill_job(self, job_id, desired_state="killed"):
        self.queue.put(("kill_job", (job_id,), {"desired_state": desired_state}))

    def kill_job_impl(self, job_id, desired_state="killed", dataHandlerOri=None):
        if dataHandlerOri is None:
            dataHandler = DataHandler()
        else:
            dataHandler = dataHandlerOri

        # TODO: Use JobDeployer?
        result, detail = k8sUtils.GetJobStatus(job_id)
        # sync start time
        runningDetail = dataHandler.GetJobTextField(job_id, "jobStatusDetail")

        if runningDetail is None:
            runningDetail = {}
        else:
            runningDetail = json.loads(base64.b64decode(runningDetail))
        if len(runningDetail)>0 and "startedAt" in runningDetail[0]:
            if len(detail)>0:
                detail[0]["startedAt"] = runningDetail[0]["startedAt"]
        detail = job_status_detail_with_finished_time(detail, desired_state)
        dataHandler.UpdateJobTextField(job_id, "jobStatusDetail", base64.b64encode(json.dumps(detail)))
        logger.info("Killing job %s, with status %s, %s" % (job_id, result, detail))

        jobType = dataHandler.GetJobTextField(job_id, "jobType")
        if jobType == "InferenceJob":
            job_deployer = InferenceServiceJobDeployer()
            errors = job_deployer.delete_job(job_id, force=True)
        else:
            job_deployer = JobDeployer()
            errors = job_deployer.delete_job(job_id, force=True)

        dataFields = {
            "jobStatusDetail": base64.b64encode(json.dumps(detail)),
            "lastUpdated": datetime.datetime.now().isoformat()
        }
        conditionFields = {"jobId": job_id}
        if len(errors) == 0:
            dataFields["jobStatus"] = desired_state
            dataHandler.UpdateJobTextFields(conditionFields, dataFields)
            if dataHandlerOri is None:
                dataHandler.Close()
            return True
        else:
            dataFields["jobStatus"] = "error"
            dataFields["jobStatusDetail"] = base64.b64encode(errors)
            dataHandler.UpdateJobTextFields(conditionFields, dataFields)
            if dataHandlerOri is None:
                dataHandler.Close()
            logger.error("Kill job failed with errors: {}".format(errors))
            return False

    def run(self, queue):
        # TODO maintain a data_handler so do not need to init it every time
        while True:
            func_name, args, kwargs = queue.get(True)

            try:
                if func_name == "submit_job":
                    self.submit_job_impl(*args, **kwargs)
                elif func_name == "kill_job":
                    self.kill_job_impl(*args, **kwargs)
                else:
                    logger.error("unknown func_name %s, with args %s %s",
                            func_name, args, kwargs)
            except Exception:
                logger.exception("processing job failed")
            finally:
                queue.task_done()
