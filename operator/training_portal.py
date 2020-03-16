import os
import random
import string

import kopf
import kubernetes
import kubernetes.client
import kubernetes.utils

__all__ = ["training_portal_create", "training_portal_delete"]


@kopf.on.create("training.eduk8s.io", "v1alpha1", "trainingportals", id="eduk8s")
def training_portal_create(name, spec, logger, **_):
    apps_api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()
    custom_objects_api = kubernetes.client.CustomObjectsApi()
    extensions_api = kubernetes.client.ExtensionsV1beta1Api()
    rbac_authorization_api = kubernetes.client.RbacAuthorizationV1Api()

    # Use the name of the custom resource with prefix "eduk8s-" as the
    # name of the portal namespace.

    portal_name = name
    portal_namespace = f"{portal_name}-ui"

    # Determine URL to be used for accessing the portal web interface.

    domain = os.environ.get("INGRESS_DOMAIN", "training.eduk8s.io")
    domain = spec.get("portal", {}).get("domain", domain)

    portal_hostname = f"{portal_name}-ui.{domain}"

    # Generate an admin password for portal management.

    characters = string.ascii_letters + string.digits
    admin_password = "".join(random.sample(characters, 32))

    # Create the namespace for holding the web interface for the portal.

    namespace_body = {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": portal_namespace},
    }

    # Make the namespace for the portal a child of the custom resource
    # for the training portal. This way the namespace will be
    # automatically deleted when the resource definition for the
    # training portal is deleted and we don't have to clean up anything
    # explicitly.

    kopf.adopt(namespace_body)

    namespace_instance = core_api.create_namespace(body=namespace_body)

    # Delete any limit ranges applied to the namespace so they don't
    # cause issues with deploying the training portal.

    limit_ranges = core_api.list_namespaced_limit_range(namespace=portal_namespace)

    for limit_range in limit_ranges.items:
        core_api.delete_namespaced_limit_range(
            namespace=portal_namespace, name=limit_range["metadata"]["name"]
        )

    # Delete any resource quotas applied to the namespace so they don't
    # cause issues with deploying the training portal.

    resource_quotas = core_api.list_namespaced_resource_quota(
        namespace=portal_namespace
    )

    for resource_quota in resource_quotas.items:
        core_api.delete_namespaced_resource_quota(
            namespace=portal_namespace, name=resource_quota["metadata"]["name"]
        )

    # Now need to loop over the list of the workshops and create the
    # workshop environment and required number of sessions for each.

    workshops = []
    environments = []

    default_capacity = spec.get("portal", {}).get("capacity", 0)
    default_reserved = spec.get("portal", {}).get("reserved", default_capacity)

    for n, workshop in enumerate(spec.get("workshops", [])):
        # Use the name of the custom resource as the name of the workshop
        # environment.

        workshop_name = workshop["name"]
        environment_name = f"{portal_name}-w{n+1:02}"

        # Verify that the workshop definition exists.

        try:
            workshop_instance = custom_objects_api.get_cluster_custom_object(
                "training.eduk8s.io", "v1alpha1", "workshops", workshop_name
            )
        except kubernetes.client.rest.ApiException as e:
            if e.status == 404:
                raise kopf.TemporaryError(f"Workshop {workshop_name} is not available.")

        workshop_details = {
            "name": workshop_name,
            "vendor": workshop_instance.get("spec", {}).get("vendor", ""),
            "title": workshop_instance.get("spec", {}).get("title", ""),
            "description": workshop_instance.get("spec", {}).get("description", ""),
            "url": workshop_instance.get("spec", {}).get("url", ""),
        }

        workshops.append(workshop_details)

        # Defined the body of the workshop environment to be created.

        env = workshop.get("env", [])

        environment_body = {
            "apiVersion": "training.eduk8s.io/v1alpha1",
            "kind": "WorkshopEnvironment",
            "metadata": {"name": environment_name,},
            "spec": {
                "workshop": {"name": workshop_name},
                "request": {"namespaces": ["--requests-disabled--"]},
                "session": {"domain": domain, "env": env,},
                "environment": {"objects": [],},
            },
        }

        # Make the workshop environment a child of the custom resource for
        # the training portal. This way the whole workshop environment will be
        # automatically deleted when the resource definition for the
        # training portal is deleted and we don't have to clean up anything
        # explicitly.

        kopf.adopt(environment_body)

        custom_objects_api.create_cluster_custom_object(
            "training.eduk8s.io", "v1alpha1", "workshopenvironments", environment_body,
        )

        if workshop.get("capacity") is not None:
            workshop_capacity = workshop.get("capacity", default_capacity)
            workshop_reserved = workshop.get("reserved", workshop_capacity)
        else:
            workshop_capacity = default_capacity
            workshop_reserved = default_reserved

        workshop_capacity = max(0, workshop_capacity)
        workshop_reserved = max(0, min(workshop_reserved, workshop_capacity))

        environments.append(
            {
                "name": environment_name,
                "workshop": {"name": workshop_name},
                "capacity": workshop_capacity,
                "reserved": workshop_reserved,
            }
        )

    # Deploy the training portal web interface. First up need to create a
    # service account and binding required roles to it.

    service_account_body = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": "eduk8s-portal"},
    }

    core_api.create_namespaced_service_account(
        namespace=portal_namespace, body=service_account_body
    )

    cluster_role_body = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRole",
        "metadata": {"name": f"eduk8s-portal-{portal_name}"},
        "rules": [
            {
                "apiGroups": ["training.eduk8s.io"],
                "resources": [
                    "workshops",
                    "workshopenvironments",
                    "workshopsessions",
                    "workshoprequests",
                    "trainingportals",
                ],
                "verbs": ["get", "list"],
            },
            {
                "apiGroups": ["training.eduk8s.io"],
                "resources": ["workshopsessions",],
                "verbs": ["create", "delete"],
            },
        ],
    }

    kopf.adopt(cluster_role_body)

    rbac_authorization_api.create_cluster_role(body=cluster_role_body)

    cluster_role_binding_body = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRoleBinding",
        "metadata": {"name": f"eduk8s-portal-{portal_name}"},
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": f"eduk8s-portal-{portal_name}",
        },
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": "eduk8s-portal",
                "namespace": portal_namespace,
            }
        ],
    }

    kopf.adopt(cluster_role_binding_body)

    rbac_authorization_api.create_cluster_role_binding(body=cluster_role_binding_body)

    # Allocate a persistent volume for storage of the database.

    persistent_volume_claim_body = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": "eduk8s-portal"},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
        },
    }

    core_api.create_namespaced_persistent_volume_claim(
        namespace=portal_namespace, body=persistent_volume_claim_body
    )

    # Next create the deployment for the portal web interface.

    deployment_body = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "eduk8s-portal"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"deployment": "eduk8s-portal"}},
            "strategy": {"type": "Recreate"},
            "template": {
                "metadata": {"labels": {"deployment": "eduk8s-portal"}},
                "spec": {
                    "serviceAccountName": "eduk8s-portal",
                    "containers": [
                        {
                            "name": "portal",
                            "image": "quay.io/eduk8s/eduk8s-portal:master",
                            "imagePullPolicy": "Always",
                            "resources": {
                                "requests": {"memory": "256Mi"},
                                "limits": {"memory": "256Mi"},
                            },
                            "ports": [{"containerPort": 8080, "protocol": "TCP"}],
                            "env": [
                                {"name": "TRAINING_PORTAL", "value": portal_name,},
                                {"name": "ADMIN_PASSWORD", "value": admin_password,},
                                {"name": "INGRESS_DOMAIN", "value": domain,},
                                {"name": "INGRESS_PROTOCOL", "value": "http",},
                            ],
                            "volumeMounts": [
                                {"name": "data", "mountPath": "/var/run/eduk8s"}
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "data",
                            "persistentVolumeClaim": {"claimName": "eduk8s-portal"},
                        }
                    ],
                },
            },
        },
    }

    apps_api.create_namespaced_deployment(
        namespace=portal_namespace, body=deployment_body
    )

    # Finally expose the deployment via a service and ingress route.

    service_body = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "eduk8s-portal"},
        "spec": {
            "type": "ClusterIP",
            "ports": [{"port": 8080, "protocol": "TCP", "targetPort": 8080}],
            "selector": {"deployment": "eduk8s-portal"},
        },
    }

    core_api.create_namespaced_service(namespace=portal_namespace, body=service_body)

    ingress_body = {
        "apiVersion": "extensions/v1beta1",
        "kind": "Ingress",
        "metadata": {"name": "eduk8s-portal"},
        "spec": {
            "rules": [
                {
                    "host": portal_hostname,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "backend": {
                                    "serviceName": "eduk8s-portal",
                                    "servicePort": 8080,
                                },
                            }
                        ]
                    },
                }
            ]
        },
    }

    extensions_api.create_namespaced_ingress(
        namespace=portal_namespace, body=ingress_body
    )

    # Save away the details of the portal which was created in status.

    return {
        "url": f"http://{portal_hostname}",
        "credentials": {"administrator": admin_password},
        "workshops": workshops,
        "environments": environments,
    }


@kopf.on.delete("training.eduk8s.io", "v1alpha1", "trainingportals", optional=True)
def training_portal_delete(name, spec, logger, **_):
    # Nothing to do here at this point because the owner references will
    # ensure that everything is cleaned up appropriately.

    pass