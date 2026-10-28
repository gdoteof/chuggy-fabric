#!/usr/bin/env python3
"""Refuse a release pipeline whose manifests are not what its files argue.

usage: release-pipeline.py RENDERED_BUILD_SYSTEM RENDERED_APPS RENDERED_FLUX
           BUILD_SYSTEM_DIRECTORY [RENDERED_LAYER ...]

Every assertion is made against what the layers render, except for the
manifests nothing renders: each run a person creates, BY_HAND below, is read
as a file, and release-run.yaml as the trigger's ConfigMap carries it.

EVERY LAYER GIVEN IS READ AS ONE CLUSTER, because a namespace's policies add
up across whoever applies them, and so do its bindings: what is held of a
namespace here is held of every render this is given, and
tests/release-pipeline.nix lists them. An object two of them render is
refused. Each layer would put its own back at its interval.

NO TASK POD HAS A TOKEN. A run's pods are placed by the run, so every
manifest for one names the `builder` ServiceAccount and a pod template that
mounts no token, `builder` mounts none itself and is bound to no role, and no
Task has a volume that is anything but a ConfigMap or an empty directory.

BUT TWO, EACH GIVEN THE ONE SECRET IT SPEAKS WITH. `report-actions` has the
bearer it reports with, and no step that runs a commit's code is in a pod with
it. `build-two-platform-image` has the certificate and key it speaks to the
Mac's BuildKit daemon with, mounted by its `build` step alone, which
two-platform-image.yaml argues. No other Task has a Secret volume. Each is
optional, because a pod that names a Secret that is not there is never
started, and is mounted read-only and whole: a `subPath` is a copy the kubelet
does not bring up to date.

THE REPORT CANNOT FAIL THE RUN, AND IS TOLD OF EVERY TASK. A `finally` task
that fails, or runs past its bound, fails a run that has already published,
and the trigger builds a failed run again. So the one there is carries
`onError: continue`, which Tekton reads as a failure to ignore and admits only
at `enable-api-fields` `beta`; a `timeout` of its own under the run's, the run
giving `finally` none; and no `retries`, which Tekton refuses beside the
first. Its `statuses` name each task of the pipeline once, beside that task's
own status: a line that paired one task with another's would report the
wrong outcome under a true name.

ONLY THE TRIGGER IS GIVEN A ROUTE TO THE API SERVER. The build namespace's
policies are held exactly: `build-egress` to what it was before the pipeline,
because a rule widened for a task is a route for every task, one rule beside
it for the pods of `publish-release` alone, and one for the pods of
`build-two-platform-image` to the daemon its run names, at that address and
port and nowhere else. The trigger's namespace holds the trigger and nothing
else, its two policies are held exactly, and so are the two Roles its
ServiceAccount is bound to, which are bound to nobody else. A binding counts
when it names the ServiceAccount, or the user or a group its token also is.

WHAT THE TRIGGER'S TOKEN CREATES IS HELD BY ADMISSION, AND THE POLICY IS HELD
TO THE RUN. `create` on PipelineRuns is by itself any pod `chuggy-build`
admits, so two policies admit from the trigger's ServiceAccount only
release-run.yaml, for what the two sources hold. The first is written here
again from release-run.yaml, as the trigger's ConfigMap carries it, and the
two are compared token by token: a field added to the run and not to the
policy is refused here, and not by the API server each minute. The second and
the three bindings are held exactly, and so is whom each is asked about.

NOBODY ELSE IS BOUND IN `chuggy-build`. The release registry admits a pod by a
label, and whoever can create a run or a pod there writes the label, so the
namespace's RoleBindings are the trigger's one. A ClusterRoleBinding is not
read for this: cluster/apps/release-registry.yaml says whom its policy admits.

WHO REACHES A REGISTRY IS WHO CAN WRITE IT, so each is held by everything that
decides who does. Every NetworkPolicy of the namespace that selects its pod,
whatever it is named and however it selects, is the one written here:
`registry` admits task pods; the release registry admits the pods of the Task
`publish-release`, which has no step but a fetch and the publish, and
source-controller; the public front admits Traefik. Its pod carries the one
label, so no other Service routes to it and a build's push through `registry`
cannot land on it. The namespace holds nothing but these: a policy or a
Service this does not know is refused, and so is a second pod behind one.

THE THREE KEEP THEIR STORES ON ONE CLAIM, AND A ROOT IS A PATH INSIDE A MOUNT,
so each is held to both. Its volumes and its mounts are the claim, whole, at
the one path, beside its configuration; and that configuration, taken from
the one file and from no environment, which Distribution reads over the file,
names its root. Releases are kept under a root `registry` and its public
front are not given, and a `subPath`, another mount or another volume is what
would give it to them with every root as written. Deletion stays on in the
release registry: deleting a release is how one is undone.

A RUN STARTED BY FLUX IS A RUN STARTED AT EVERY RECONCILE, so neither run
manifest is rendered. That the two release layers read what a run publishes is
held by tests/flux-layers.py, beside the two sources.

THE TWO-PLATFORM TASK BUILDS LINUX/AMD64 AS `build-image` BUILDS ONE IMAGE.
Its `fetch` is `build-image`'s, and so is its `build` but for the daemon, the
files it is spoken to with, the directory the halves are left in for `index`,
and the Secret's mount; its parameters, results and volumes are
`build-image`'s but for the daemon, which has no default, and the Secret. Its
`index` step reads that directory and writes the result the `build` step
would have. worker-image-run.yaml is the one run of it.

EVERY IMAGE IS PINNED BY DIGEST, and every step names its `command`, without
which Tekton asks the image's registry for the entrypoint.

WHAT A POD MAY DO ON ITS NODE IS HELD EXACTLY, because here the manifest is
the only limit. `chuggy-build` enforces Pod Security `privileged`, which is
what a rootless BuildKit needs of it, so a step written as root or
`privileged` is admitted as written. Each step's `securityContext` is held, and
a Task and a step are held to the fields these have: a `stepTemplate`, a
sidecar or a field of a step this does not know is a second place to say what
a container may do. The trigger's namespace does enforce `restricted`, and that
label is held with the pod: without it nothing refuses the trigger root or the
node's network, and a pod on the node's network is one neither of its policies
binds.

THE TRIGGER'S TIMING IS HELD BECAUSE EACH VALUE IS READ BY ANOTHER. The
schedule is the minute trigger.sh and the alert that announces a trigger that
stopped both count in; the Job's deadline is what `Forbid` waits out before the
next minute may start; a finished Job's time to live is what keeps one failed
minute from being a failed Job for good; a run's timeout is the one thing that
ends a run that hangs, and a run that has not finished is all the trigger
needs to start nothing. `suspend` is held with them: suspended in git, the
trigger starts no release and cluster/apps/release-trigger-alert.yaml is
silent about it, so a stop is written here as well as there.

WHAT ONLY A RUN WOULD OTHERWISE SHOW is held here, because the run that shows
it is a release that is not made: a Task a Pipeline names that is not there, a
parameter passed that is not declared or declared and never passed, a script
that is not in the ConfigMap a step mounts, a reference to a result no task
writes or to the status of a task that is not there, the image a build pushes
under one name and the release overrides
under another path, the source the trigger reads in a namespace where it is
not, and a release pushed to a repository the Flux source does not read, or
to a registry that is not the release registry's Service.

THE IMAGE TRIGGER IS HELD BESIDE THE RELEASE TRIGGER, TO THE SAME THINGS. It
shares the namespace, and the namespace is still held to exactly what is
rendered there: each trigger's ServiceAccount, each CronJob, the ConfigMaps
and one egress policy a trigger. Each CronJob is held to the one timing, the
one pod and the one container shape; each ServiceAccount to its own two Roles,
bound to it alone; `chuggy-build`'s RoleBindings to the two. What the image
trigger creates is a TaskRun, so its two policies are held to that file as the
release trigger's are to release-run.yaml: the spec written from the file as
the trigger's ConfigMap carries it, the four parameters each once, the image
and the Dockerfile the file names, and the source the CronJob reads. Its
source binding says `Allow` where the release's say `Deny`, because a TaskRun
is every build's and a site source that is gone must not hold a release;
image-trigger.yaml argues it.
"""

import json
import re
import sys
from pathlib import Path

import yaml

BUILD_NAMESPACE = "chuggy-build"
TRIGGER_NAMESPACE = "chuggy-release-trigger"
TRIGGER = "release-trigger"
BUILDER = "builder"
PIPELINE = "chuggy-release"
RUN_FILE = "release-run.yaml"
# The TaskRuns a person creates, as files in the directory: the worker
# image's, of the two-platform Task, and Track Record's, of `build-image`.
BY_HAND = ("worker-image-run.yaml", "track-record-image-run.yaml")
BUILD_TASK = "build-image"
PINNED = re.compile(r"[a-z0-9./-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}")
REFERENCE = re.compile(r"\$\(([^)]+)\)")

KUBE_DNS = {
    "to": [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }
    ],
    "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
}
TASK_PODS = {"matchExpressions": [{"key": "tekton.dev/taskRun", "operator": "Exists"}]}
PUBLISH_TASK = "publish-release"
PUBLISH_PODS = {"matchLabels": {"tekton.dev/task": PUBLISH_TASK}}
REGISTRY_NAMESPACE = "chuggy-registry"
RELEASE_REGISTRY = "release-registry"
REGISTRY_PORT = [{"protocol": "TCP", "port": 5000}]
# The claim the namespace's Distribution processes share, and where each
# mounts the whole of it.
STORE_CLAIM = "registry"
STORE = "/var/lib/registry"

BUILD_POLICIES = {
    "build-default-deny": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
    "build-egress": {
        "podSelector": TASK_PODS,
        "policyTypes": ["Egress"],
        "egress": [
            KUBE_DNS,
            {
                "to": [
                    {
                        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "chuggy-registry"}},
                        "podSelector": {"matchLabels": {"app": "registry"}},
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 5000}],
            },
            {
                "to": [
                    {
                        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "chuggy-git"}},
                        "podSelector": {"matchLabels": {"app.kubernetes.io/name": "git"}},
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 8080}],
            },
            {
                "to": [
                    {
                        "ipBlock": {
                            "cidr": "0.0.0.0/0",
                            "except": [
                                "10.0.0.0/8",
                                "100.64.0.0/10",
                                "127.0.0.0/8",
                                "169.254.0.0/16",
                                "172.16.0.0/12",
                                "192.168.0.0/16",
                            ],
                        }
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 443}],
            },
        ],
    },
    "release-publish-egress": {
        "podSelector": PUBLISH_PODS,
        "policyTypes": ["Egress"],
        "egress": [
            {
                "to": [
                    {
                        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": REGISTRY_NAMESPACE}},
                        "podSelector": {"matchLabels": {"app": RELEASE_REGISTRY}},
                    }
                ],
                "ports": REGISTRY_PORT,
            }
        ],
    },
}



def trigger_egress(app):
    """Where a trigger's pod may go: the cluster's DNS and the API server's
    port, selected by that trigger's label."""
    return {
        "podSelector": {"matchLabels": {"app": app}},
        "policyTypes": ["Egress"],
        "egress": [
            KUBE_DNS,
            {
                "to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": ["10.42.0.0/16", "10.43.0.0/16"]}}],
                "ports": [{"protocol": "TCP", "port": 6443}],
            },
        ],
    }


TRIGGER_POLICIES = {
    "release-trigger-default-deny": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
    "release-trigger-egress": trigger_egress(TRIGGER),
    "image-trigger-egress": trigger_egress("image-trigger"),
}

# Each Distribution process of the namespace: who its one policy admits, the
# root it keeps its store under on the claim, whether it may write there, and
# whether its configuration has to leave deletion on. tests/registry-public.py
# holds what keeps the public front from serving unasked.
REGISTRIES = {
    "registry": {
        "admits": [
            {
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": BUILD_NAMESPACE}},
                "podSelector": TASK_PODS,
            }
        ],
        "root": STORE,
        "writes": True,
        "deletes": None,
    },
    "registry-public": {
        "admits": [
            {
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}},
            }
        ],
        "root": STORE,
        "writes": False,
        "deletes": None,
    },
    RELEASE_REGISTRY: {
        "admits": [
            {
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": BUILD_NAMESPACE}},
                "podSelector": PUBLISH_PODS,
            },
            {
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "flux-system"}},
                "podSelector": {"matchLabels": {"app": "source-controller"}},
            },
        ],
        "root": f"{STORE}/release",
        "writes": True,
        "deletes": True,
    },
}
REGISTRY_CONFIGURATION = "/etc/distribution/config.yml"
# What the namespace holds beside each process's Deployment, Service, policy
# and configuration.
REGISTRY_NAMESPACE_ALSO = [
    ("Ingress", "registry-public"),
    ("Middleware", "pool-plane-authorizes-pulls"),
    ("PersistentVolumeClaim", STORE_CLAIM),
]

# The two sources the trigger reads, and the parameters of a run that say
# what each holds.
SOURCES = {
    "chuggy": {"address": "chuggy-url", "commit": "chuggy-commit"},
    "fabric-release": {"address": "manifests-url", "commit": "manifests-commit"},
}
SOURCE_KIND = {"apiVersion": "source.toolkit.fluxcd.io/v1", "kind": "GitRepository"}
TRIGGER_ROLES = {
    "flux-system": [
        {
            "apiGroups": ["source.toolkit.fluxcd.io"],
            "resources": ["gitrepositories"],
            "resourceNames": list(SOURCES),
            "verbs": ["get"],
        }
    ],
    BUILD_NAMESPACE: [
        {"apiGroups": ["tekton.dev"], "resources": ["pipelineruns"], "verbs": ["list", "create", "delete"]}
    ],
}
TRIGGER_RUNS = "release-trigger-runs"

# The image trigger: one ServiceAccount, and a CronJob for each image it
# builds, each named with the source it reads, the run file it creates from and
# the policy that selects its pod.
IMAGE_TRIGGER = "image-trigger"
IMAGE_TRIGGER_RUNS = "image-trigger-runs"
IMAGE_TRIGGERS = {
    "chug-gy-image-trigger": {"source": "chug-gy", "run": "chug-gy-image-run.yaml", "policy": "image-trigger-egress"},
}
IMAGE_SOURCES = {trigger["source"]: {"address": "url", "commit": "commit"} for trigger in IMAGE_TRIGGERS.values()}
IMAGE_TRIGGER_ROLES = {
    "flux-system": [
        {
            "apiGroups": ["source.toolkit.fluxcd.io"],
            "resources": ["gitrepositories"],
            "resourceNames": list(IMAGE_SOURCES),
            "verbs": ["get"],
        }
    ],
    BUILD_NAMESPACE: [{"apiGroups": ["tekton.dev"], "resources": ["taskruns"], "verbs": ["list", "create", "delete"]}],
}
IMAGE_RUN_FIELDS = {"taskRef", "params", "timeout", "serviceAccountName", "podTemplate"}
IMAGE_PARAMS = ["url", "commit", "image", "dockerfile"]
# The one binding a layer renders for everyone who is authenticated, which a
# ServiceAccount's token is: Tekton's release lets each read the ConfigMap
# that says its version.
EVERYONE = {
    "namespace": "tekton-pipelines",
    "name": "tekton-pipelines-info",
    "subjects": [{"apiGroup": "rbac.authorization.k8s.io", "kind": "Group", "name": "system:authenticated"}],
    "role": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "tekton-pipelines-info"},
    "rules": [{"apiGroups": [""], "resourceNames": ["pipelines-info"], "resources": ["configmaps"], "verbs": ["get"]}],
}

CONFINED = {
    "runAsNonRoot": True,
    "allowPrivilegeEscalation": False,
    "capabilities": {"drop": ["ALL"]},
    "readOnlyRootFilesystem": True,
    "seccompProfile": {"type": "RuntimeDefault"},
}
AS_BUILDKIT = {"runAsUser": 1000, "runAsGroup": 1000}
AS_NOBODY = {"runAsUser": 65534, "runAsGroup": 65534}
# What `id` prints in the image `report` runs.
AS_CURL = {"runAsUser": 100, "runAsGroup": 101}
# And in the image `index` runs.
AS_REGCTL = {"runAsUser": 1000, "runAsGroup": 1000}
REPORT_TASK = "report-actions"
TWO_PLATFORM_TASK = "build-two-platform-image"
# The one run of it, and the policy that lets its pods reach the daemon the
# run names.
TWO_PLATFORM_RUN = "worker-image-run.yaml"
BUILDER_EGRESS = "arm64-builder-egress"
BUILDER_ADDRESS = re.compile(r"tcp://(\d{1,3}(?:\.\d{1,3}){3}):(\d+)")
# What the two-platform Task's `build` step has that `build-image`'s does not.
TWO_PLATFORM_ENV = ("ARM64_BUILDER", "ARM64_BUILDER_TLS", "INDEX")
# The Tasks given a Secret: the one each is given, and the steps that mount it.
SECRETS = {
    REPORT_TASK: {"secret": "chuggy-report-build", "steps": ["report"]},
    TWO_PLATFORM_TASK: {"secret": "arm64-builder-client", "steps": ["build"]},
}

BUILD_STEP = {
    "runAsNonRoot": True,
    **AS_BUILDKIT,
    "allowPrivilegeEscalation": True,
    "capabilities": {"add": ["SETGID", "SETUID"], "drop": ["ALL"]},
    "readOnlyRootFilesystem": True,
    "seccompProfile": {"type": "Unconfined"},
    "appArmorProfile": {"type": "Unconfined"},
}
# The steps of each Task, in order, and what each may do.
STEPS = {
    "build-image": {
        "fetch": {**CONFINED, **AS_BUILDKIT},
        "build": BUILD_STEP,
    },
    TWO_PLATFORM_TASK: {
        "fetch": {**CONFINED, **AS_BUILDKIT},
        "build": BUILD_STEP,
        "index": {**CONFINED, **AS_REGCTL},
    },
    "publish-release": {
        "fetch": {**CONFINED, **AS_BUILDKIT},
        "publish": {**CONFINED, **AS_NOBODY},
    },
    REPORT_TASK: {"report": {**CONFINED, **AS_CURL}},
}
TASK_FIELDS = {"params", "results", "volumes", "steps"}
STEP_FIELDS = {
    "name",
    "image",
    "imagePullPolicy",
    "command",
    "env",
    "securityContext",
    "computeResources",
    "volumeMounts",
}

RESTRICTED = {
    "pod-security.kubernetes.io/enforce": "restricted",
    "pod-security.kubernetes.io/audit": "restricted",
    "pod-security.kubernetes.io/warn": "restricted",
}
TRIGGER_TIMING = {
    "suspend": False,
    "schedule": "* * * * *",
    "concurrencyPolicy": "Forbid",
    "startingDeadlineSeconds": 30,
    "successfulJobsHistoryLimit": 1,
    "failedJobsHistoryLimit": 3,
}
TRIGGER_JOB = {"backoffLimit": 0, "activeDeadlineSeconds": 45, "ttlSecondsAfterFinished": 600}
TRIGGER_POD_FIELDS = {
    "serviceAccountName",
    "automountServiceAccountToken",
    "restartPolicy",
    "terminationGracePeriodSeconds",
    "nodeSelector",
    "securityContext",
    "containers",
    "volumes",
}
TRIGGER_POD_SECURITY = {"runAsNonRoot": True, **AS_NOBODY, "seccompProfile": {"type": "RuntimeDefault"}}
TRIGGER_CONTAINER_FIELDS = {
    "name",
    "image",
    "imagePullPolicy",
    "command",
    "env",
    "resources",
    "securityContext",
    "volumeMounts",
}
TRIGGER_CONTAINER_SECURITY = {
    "allowPrivilegeEscalation": False,
    "readOnlyRootFilesystem": True,
    "capabilities": {"drop": ["ALL"]},
}
RUN_FIELDS = {"pipelineRef", "params", "timeouts", "taskRunTemplate"}
RUN_TIMEOUTS = {"pipeline": "1h0m0s"}

# The `finally` tasks, each the Task it is of, and what one carries.
FINALLY = {"report": REPORT_TASK}
FINALLY_FIELDS = {"name", "timeout", "onError", "taskRef", "params"}
# What a `finally` task may read that no task may: each task's status and the
# run's name.
RUN_NAME = "context.pipelineRun.name"
STATUS = re.compile(r"tasks\.([^.]+)\.status")
STATUS_LINE = re.compile(r"(\S+) \$\(tasks\.(\S+)\.status\)")
# The feature gates Tekton admits `onError` at.
ON_ERROR_GATES = ("alpha", "beta")
DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")

# What admission asks of a PipelineRun the trigger's ServiceAccount creates,
# and of a TaskRun the image trigger's does.
RUN_POLICY = "release-trigger-creates-the-release-run"
SOURCE_POLICY = "release-trigger-runs-what-a-source-holds"
IMAGE_RUN_POLICY = "image-trigger-creates-an-image-run"
IMAGE_SOURCE_POLICY = "image-trigger-builds-what-a-source-holds"


def asked_of(resource, account, condition):
    """Whom and what a policy is asked about: one kind of run, created by one
    of the triggers' ServiceAccounts."""
    return {
        "failurePolicy": "Fail",
        "matchConstraints": {
            "resourceRules": [
                {"apiGroups": ["tekton.dev"], "apiVersions": ["*"], "operations": ["CREATE"], "resources": [resource]}
            ]
        },
        "matchConditions": [
            {
                "name": condition,
                "expression": f'request.userInfo.username == "system:serviceaccount:{TRIGGER_NAMESPACE}:{account}"',
            }
        ],
    }


ASKED_OF = asked_of("pipelineruns", TRIGGER, "created-by-the-release-trigger")
IMAGE_ASKED_OF = asked_of("taskruns", IMAGE_TRIGGER, "created-by-the-image-trigger")
# The image and the Dockerfile a run the image trigger creates may name.
BUILDS_WHAT_IS_NAMED = (
    'variables.params.exists(param, param.name == "image" && type(param.value) == string && param.value in variables.images)'
    ' && variables.params.exists(param, param.name == "dockerfile" && type(param.value) == string'
    ' && variables.params.exists(image, image.name == "image" && variables.images[string(image.value)] == param.value))'
)
FOR_A_SOURCE = (
    "has(params.status.artifact) && has(object.spec.params)"
    " && object.spec.params.exists(param, param.name == variables.named.address && param.value == params.spec.url)"
    " && object.spec.params.exists(param, param.name == variables.named.commit && type(param.value) == string"
    ' && params.status.artifact.revision.endsWith("@sha1:" + param.value))'
)

PLACEMENT = {
    "automountServiceAccountToken": False,
    "nodeSelector": {
        "chuggy.dev/node-role": "builder",
        "kubernetes.io/os": "linux",
        "kubernetes.io/arch": "amd64",
    },
    "tolerations": [
        {"key": "chuggy.dev/node-role", "operator": "Equal", "value": "builder", "effect": "NoSchedule"}
    ],
}


def refuse(message):
    raise SystemExit(f"release-pipeline: {message}")


def objects(text):
    return [document for document in yaml.safe_load_all(text) if document]


def layer(path):
    """What one layer applies: a render, or a directory with no
    kustomization.yaml, of which Flux applies every manifest."""
    path = Path(path)
    files = sorted(path.rglob("*.yaml")) + sorted(path.rglob("*.yml")) if path.is_dir() else [path]
    return [document for file in files for document in objects(file.read_text())]


def of(documents, kind, namespace=None):
    return {
        document["metadata"]["name"]: document
        for document in documents
        if document["kind"] == kind
        and (namespace is None or document["metadata"].get("namespace") == namespace)
    }


def exactly(subject, found, expected):
    if found != expected:
        refuse(f"{subject} is {found}, not {expected}")


def answers_to(subject, account, namespace):
    """Whether a binding's subject is the ServiceAccount: by that kind, or by
    the user and the groups its token is as well."""
    kind, name = subject.get("kind"), subject.get("name")
    if kind == "ServiceAccount":
        return name == account and subject.get("namespace") == namespace
    if kind == "User":
        return name == f"system:serviceaccount:{namespace}:{account}"
    return kind == "Group" and name in ("system:authenticated", "system:serviceaccounts", f"system:serviceaccounts:{namespace}")


def selects(selector, labels):
    """Whether a label selector selects a pod with these labels. An empty one
    selects every pod."""
    for key, value in selector.get("matchLabels", {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions", []):
        key, values = expression["key"], expression.get("values", [])
        held = {
            "Exists": key in labels,
            "DoesNotExist": key not in labels,
            "In": labels.get(key) in values,
            "NotIn": labels.get(key) not in values,
        }.get(expression["operator"])
        if held is None:
            refuse(f"a selector uses the operator {expression['operator']}, which this does not evaluate")
        if not held:
            return False
    return True


def registry_is_held(cluster, name, expected):
    """One Distribution process of the namespace: its pod, everything that
    selects the pod, the claim it mounts and the root its configuration names
    there. Returns what of the namespace is its own, and the address a pod
    reaches it by."""
    deployment = of(cluster, "Deployment", REGISTRY_NAMESPACE).get(name)
    if deployment is None:
        refuse(f"no layer renders a Deployment {name} in {REGISTRY_NAMESPACE}")
    labels = {"app": name}
    template = deployment["spec"]["template"]
    exactly(f"the labels of Deployment {name}'s pod", template["metadata"].get("labels"), labels)
    selecting = {
        policy_name: policy["spec"]
        for policy_name, policy in of(cluster, "NetworkPolicy", REGISTRY_NAMESPACE).items()
        if selects(policy["spec"]["podSelector"], labels)
    }
    policy = {
        "podSelector": {"matchLabels": labels},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [{"from": expected["admits"], "ports": REGISTRY_PORT}],
    }
    exactly(f"the NetworkPolicies that select Deployment {name}'s pod", list(selecting.values()), [policy])
    routed = {
        service_name: service
        for service_name, service in of(cluster, "Service", REGISTRY_NAMESPACE).items()
        if service["spec"].get("selector") and selects({"matchLabels": service["spec"]["selector"]}, labels)
    }
    exactly(f"the Services that route to Deployment {name}'s pod", sorted(routed), [name])

    pod = template["spec"]
    if len(pod["containers"]) != 1 or pod.get("initContainers"):
        refuse(f"Deployment {name}'s pod is not one container")
    container = pod["containers"][0]
    exactly(f"what Deployment {name}'s container is started with", container.get("args"), [REGISTRY_CONFIGURATION])
    if "env" in container or "envFrom" in container or "command" in container:
        refuse(f"Deployment {name}'s container is given an environment or a command, and Distribution reads either over its file")
    ports = {port["name"]: port["containerPort"] for port in container["ports"]}
    (port,) = routed[name]["spec"]["ports"]
    exactly(f"the port Service {name} routes to", ports.get(port["targetPort"], port["targetPort"]), REGISTRY_PORT[0]["port"])

    # The store: a root is a path inside a mount, so the two are held
    # together, and so is the volume the mount is of.
    file = REGISTRY_CONFIGURATION.rpartition("/")[2]
    volumes = {volume["name"]: volume for volume in pod.get("volumes", [])}
    configuration = volumes.get("config", {}).get("configMap", {}).get("name")
    config = of(cluster, "ConfigMap", REGISTRY_NAMESPACE).get(configuration)
    if config is None or file not in config["data"]:
        refuse(f"Deployment {name} does not take {REGISTRY_CONFIGURATION} from a ConfigMap rendered in {REGISTRY_NAMESPACE}")
    read_only = {} if expected["writes"] else {"readOnly": True}
    exactly(
        f"the volumes of Deployment {name}'s pod",
        pod["volumes"],
        [
            {"name": "config", "configMap": {"name": configuration}},
            {"name": "storage", "persistentVolumeClaim": {"claimName": STORE_CLAIM, **read_only}},
        ],
    )
    exactly(
        f"what Deployment {name}'s container mounts",
        container.get("volumeMounts"),
        [
            {"name": "config", "mountPath": REGISTRY_CONFIGURATION, "subPath": file, "readOnly": True},
            {"name": "storage", "mountPath": STORE, **read_only},
        ],
    )
    storage = yaml.safe_load(config["data"][file])["storage"]
    exactly(f"the root Deployment {name} keeps its store under", storage["filesystem"]["rootdirectory"], expected["root"])
    if expected["deletes"] is not None:
        exactly(f"whether Deployment {name} deletes", storage.get("delete", {}).get("enabled"), expected["deletes"])
    return {
        "own": [("ConfigMap", configuration), ("Deployment", name), ("Service", name)]
        + [("NetworkPolicy", policy_name) for policy_name in selecting],
        "address": f"{name}.{REGISTRY_NAMESPACE}.svc.cluster.local:{port['port']}/",
    }


def references(value):
    if isinstance(value, str):
        yield from REFERENCE.findall(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def tasks_are_sound(cluster, tasks):
    configs = of(cluster, "ConfigMap", BUILD_NAMESPACE)
    exactly(f"the Tasks of {BUILD_NAMESPACE}", sorted(tasks), sorted(STEPS))
    for name, task in tasks.items():
        spec = task["spec"]
        exactly(f"what Task {name} carries beyond {sorted(TASK_FIELDS)}", sorted(set(spec) - TASK_FIELDS), [])
        exactly(f"the steps of Task {name}", [step["name"] for step in spec["steps"]], list(STEPS[name]))
        params = {param["name"] for param in spec.get("params", [])}
        results = {result["name"] for result in spec.get("results", [])}
        volumes = {}
        secrets = []
        for volume in spec.get("volumes", []):
            kinds = set(volume) - {"name"}
            if kinds == {"secret"} and name in SECRETS:
                secrets.append(volume["name"])
                exactly(f"the Secret Task {name} is given", volume["secret"].get("secretName"), SECRETS[name]["secret"])
                if volume["secret"].get("optional") is not True:
                    refuse(f"Task {name} names the Secret {volume['secret'].get('secretName')} and not as optional, and a pod is not started without one it requires")
            elif not kinds <= {"configMap", "emptyDir"}:
                refuse(f"Task {name} has the volume {volume['name']} of {sorted(kinds)}, and a task pod is given nothing but scripts and scratch")
            volumes[volume["name"]] = volume
        exactly(f"how many Secrets Task {name} is given", len(secrets), 1 if name in SECRETS else 0)
        exactly(
            f"the steps of Task {name} that mount its Secret",
            [step["name"] for step in spec["steps"] if any(mount["name"] in secrets for mount in step.get("volumeMounts", []))],
            SECRETS[name]["steps"] if name in SECRETS else [],
        )
        for step in spec["steps"]:
            subject = f"Task {name} step {step['name']}"
            if not PINNED.fullmatch(step["image"]):
                refuse(f"{subject} runs {step['image']}, which is not a tag pinned by digest")
            command = step.get("command")
            if "script" in step or not command or command[0] != "/bin/sh" or len(command) != 2:
                refuse(f"{subject} does not name a `command` that is /bin/sh over one script file")
            exactly(f"what {subject} carries beyond {sorted(STEP_FIELDS)}", sorted(set(step) - STEP_FIELDS), [])
            exactly(f"what {subject} may do", step.get("securityContext"), STEPS[name][step["name"]])
            for mount in step.get("volumeMounts", []):
                if mount["name"] in secrets and (mount.get("readOnly") is not True or "subPath" in mount):
                    refuse(f"{subject} mounts the Secret at {mount['mountPath']} and not read-only and whole")
            mounts = {mount["mountPath"]: mount["name"] for mount in step.get("volumeMounts", [])}
            directory, _, script = command[1].rpartition("/")
            volume = volumes.get(mounts.get(directory), {})
            config = configs.get(volume.get("configMap", {}).get("name"))
            if config is None or script not in config["data"]:
                refuse(f"{subject} runs {command[1]}, which is not a file of a ConfigMap rendered in {BUILD_NAMESPACE} that the step mounts there")
            for entry in step.get("env", []):
                if set(entry) != {"name", "value"}:
                    refuse(f"{subject} takes {entry['name']} from something other than a value written here")
            for reference in references(step):
                kind, _, rest = reference.partition(".")
                known = (kind == "params" and rest in params) or (
                    kind == "results" and rest.endswith(".path") and rest[: -len(".path")] in results
                )
                if not known:
                    refuse(f"{subject} reads $({reference}), which Task {name} does not declare")


def step_of(task, name):
    (step,) = [step for step in task["spec"]["steps"] if step["name"] == name]
    return step


def two_platforms_are_held(tasks, by_hand):
    """The two-platform Task builds linux/amd64 as `build-image` does, and its
    one run names a daemon by an address. Returns the policy that lets the
    Task's pods reach that daemon and nothing else."""
    one, two = tasks[BUILD_TASK], tasks[TWO_PLATFORM_TASK]
    subject = f"Task {TWO_PLATFORM_TASK}"
    exactly(f"{subject}'s fetch", step_of(two, "fetch"), step_of(one, "fetch"))
    (secret,) = [volume["name"] for volume in two["spec"]["volumes"] if "secret" in volume]
    build = step_of(two, "build")
    environment = {entry["name"]: entry["value"] for entry in build["env"]}
    (mount,) = [mount for mount in build["volumeMounts"] if mount["name"] == secret]
    exactly(f"where {subject}'s build finds its daemon", environment.get("ARM64_BUILDER"), "$(params.arm64-builder)")
    exactly(f"where {subject}'s build reads the files it speaks to its daemon with", environment.get("ARM64_BUILDER_TLS"), mount["mountPath"])
    exactly(
        f"{subject}'s build but for its daemon and its Secret",
        {
            **build,
            "env": [entry for entry in build["env"] if entry["name"] not in TWO_PLATFORM_ENV],
            "volumeMounts": [entry for entry in build["volumeMounts"] if entry is not mount],
        },
        step_of(one, "build"),
    )
    index = {entry["name"]: entry["value"] for entry in step_of(two, "index")["env"]}
    for name in ("IMAGE", "COMMIT", "INDEX", "RESULT_DIGEST"):
        exactly(f"the {name} {subject}'s index reads", index.get(name), environment.get(name))

    def declared(task, field, skip=()):
        return [{key: value for key, value in entry.items() if key != "description"} for entry in task["spec"][field] if entry["name"] not in skip]

    exactly(f"{subject}'s parameters but its daemon", declared(two, "params", ("arm64-builder",)), declared(one, "params"))
    (daemon,) = [entry for entry in two["spec"]["params"] if entry["name"] == "arm64-builder"]
    if "default" in daemon:
        refuse(f"{subject} has a daemon by default, {daemon['default']!r}, and the one its run names is the one its pods may reach")
    exactly(f"{subject}'s results", declared(two, "results"), declared(one, "results"))
    exactly(f"{subject}'s volumes but its Secret", declared(two, "volumes", (secret,)), declared(one, "volumes"))

    runs = sorted(file for file, run in by_hand.items() if run["spec"]["taskRef"]["name"] == TWO_PLATFORM_TASK)
    exactly(f"the runs of {subject}", runs, [TWO_PLATFORM_RUN])
    address = BUILDER_ADDRESS.fullmatch(param_values(by_hand[TWO_PLATFORM_RUN])["arm64-builder"])
    if address is None:
        refuse(f"{TWO_PLATFORM_RUN} names its daemon as {param_values(by_hand[TWO_PLATFORM_RUN])['arm64-builder']}, not tcp://<address>:<port>")
    return {
        "podSelector": {"matchLabels": {"tekton.dev/task": TWO_PLATFORM_TASK}},
        "policyTypes": ["Egress"],
        "egress": [
            {
                "to": [{"ipBlock": {"cidr": f"{address.group(1)}/32"}}],
                "ports": [{"protocol": "TCP", "port": int(address.group(2))}],
            }
        ],
    }


def passes_what_is_declared(subject, passed, task):
    declared = {param["name"]: param for param in task["spec"].get("params", [])}
    for name in passed:
        if name not in declared:
            refuse(f"{subject} passes `{name}`, which Task {task['metadata']['name']} does not declare")
    for name, param in declared.items():
        if "default" not in param and name not in passed:
            refuse(f"{subject} does not pass `{name}`, which Task {task['metadata']['name']} requires")


def seconds(duration):
    """A duration as Tekton writes one, in seconds."""
    match = DURATION.fullmatch(duration or "")
    if not match or not any(match.groups()):
        refuse(f"{duration!r} is not a duration this reads")
    hours, minutes, rest = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + rest


def reported(pipeline):
    """The tasks `report` is told the status of, as `statuses` lists them."""
    (entry,) = [entry for entry in pipeline["spec"]["finally"] if entry["name"] == "report"]
    statuses = {param["name"]: param["value"] for param in entry["params"]}["statuses"]
    lines = [STATUS_LINE.fullmatch(line) for line in statuses.splitlines()]
    if not all(lines) or any(line.group(1) != line.group(2) for line in lines):
        refuse(f"`report` is told {statuses!r}, which is not each task beside its own status")
    return [line.group(1) for line in lines]


def finally_is_sound(cluster, pipeline, tasks, params, run):
    spec = pipeline["spec"]
    named = [entry["name"] for entry in spec["tasks"]]
    exactly(f"the `finally` tasks of Pipeline {PIPELINE}", [entry["name"] for entry in spec.get("finally", [])], list(FINALLY))
    for entry in spec["finally"]:
        subject = f"Pipeline {PIPELINE} `finally` task {entry['name']}"
        exactly(f"what {subject} carries", sorted(entry), sorted(FINALLY_FIELDS))
        exactly(f"the Task {subject} is of", entry["taskRef"], {"name": FINALLY[entry["name"]]})
        exactly(f"what {subject} does to its run when it fails", entry["onError"], "continue")
        if not 0 < seconds(entry["timeout"]) < seconds(run["spec"]["timeouts"]["pipeline"]):
            refuse(f"{subject} is bounded at {entry['timeout']}, which is not under the run's {run['spec']['timeouts']['pipeline']}")
        passes_what_is_declared(subject, {param["name"] for param in entry["params"]}, tasks[entry["taskRef"]["name"]])
        for reference in references(entry):
            status = STATUS.fullmatch(reference)
            known = (
                reference == RUN_NAME
                or (status and status.group(1) in named)
                or (reference.startswith("params.") and reference[len("params."):] in params)
            )
            if not known:
                refuse(f"{subject} reads $({reference}), which nothing gives a `finally` task")
    exactly("the tasks `report` is told the status of", sorted(reported(pipeline)), sorted(named))
    flags = of(cluster, "ConfigMap", "tekton-pipelines").get("feature-flags", {}).get("data", {})
    if flags.get("enable-api-fields") not in ON_ERROR_GATES:
        refuse(f"Tekton's enable-api-fields is {flags.get('enable-api-fields')!r}, and it admits `onError` at {ON_ERROR_GATES}")


def pipeline_is_sound(pipeline, tasks):
    spec = pipeline["spec"]
    params = {param["name"] for param in spec["params"]}
    results = {}
    for entry in spec["tasks"]:
        subject = f"Pipeline {PIPELINE} task {entry['name']}"
        task = tasks.get(entry["taskRef"]["name"])
        if task is None or set(entry["taskRef"]) != {"name"}:
            refuse(f"{subject} is of {entry['taskRef']}, which is not a Task rendered in {BUILD_NAMESPACE}")
        if not entry.get("retries"):
            refuse(f"{subject} does not retry")
        passes_what_is_declared(subject, {param["name"] for param in entry["params"]}, task)
        results[entry["name"]] = {result["name"] for result in task["spec"].get("results", [])}
    for reference in references({field: value for field, value in spec.items() if field != "finally"}):
        parts = reference.split(".")
        known = (parts[0] == "params" and ".".join(parts[1:]) in params) or (
            len(parts) == 4 and parts[0] == "tasks" and parts[2] == "results" and parts[3] in results.get(parts[1], ())
        )
        if not known:
            refuse(f"Pipeline {PIPELINE} reads $({reference}), which nothing in it gives")
    return params


def cel(value):
    """A value as the CEL literal a policy holds it by.

    CEL refuses a map literal whose values are of more than one type, so
    where they are not all strings each is written `dyn(...)`.
    """
    if isinstance(value, dict):
        plain = all(isinstance(inner, str) for inner in value.values())
        return (
            "{"
            + ", ".join(
                f"{json.dumps(name)}: {cel(inner) if plain else f'dyn({cel(inner)})'}" for name, inner in value.items()
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ", ".join(cel(inner) for inner in value) + "]"
    return json.dumps(value)


def tokens(expression):
    """An expression as what CEL reads of it: a string whole, and no space."""
    return re.findall(r'"(?:[^"\\]|\\.)*"|[A-Za-z_]+|\S', expression)


def param_values(run):
    return {param["name"]: param["value"] for param in run["spec"]["params"]}


def admission_is_held(cluster, release_run, image_runs, sources_namespace):
    run = release_run["spec"]
    annotations = json.dumps(list(release_run["metadata"]["annotations"]))
    parameters = [param["name"] for param in run["params"]]
    # One spec for every image run, because one policy holds them all.
    specs = [{name: value for name, value in image_run["spec"].items() if name != "params"} for image_run in image_runs.values()]
    for file, spec in zip(image_runs, specs):
        exactly(f"{file}'s spec, its parameters apart,", spec, specs[0])
    images = {param_values(image_run)["image"]: param_values(image_run)["dockerfile"] for image_run in image_runs.values()}
    expected = {
        RUN_POLICY: {
            "asked": ASKED_OF,
            "variables": {"spec": cel({name: value for name, value in run.items() if name != "params"})},
            "validations": [
                f'object.apiVersion == {json.dumps(release_run["apiVersion"])}',
                "!has(object.metadata.labels)",
                f"!has(object.metadata.annotations) || object.metadata.annotations.all(name, name in {annotations})",
                'object.spec.all(field, field == "params" || field in variables.spec)',
                "variables.spec.all(field, field in object.spec && object.spec[field] == variables.spec[field])",
                f"has(object.spec.params) && object.spec.params.map(param, param.name) == {json.dumps(parameters)}",
            ],
        },
        SOURCE_POLICY: {
            "asked": {**ASKED_OF, "paramKind": SOURCE_KIND},
            "variables": {"named": f"{json.dumps(SOURCES)}[params.metadata.name]"},
            "validations": [FOR_A_SOURCE],
        },
        IMAGE_RUN_POLICY: {
            "asked": IMAGE_ASKED_OF,
            "variables": {
                "spec": cel(specs[0]),
                "images": cel(images),
                "params": "has(object.spec.params) ? object.spec.params : []",
            },
            "validations": [
                'object.apiVersion == "tekton.dev/v1"',
                "!has(object.metadata.labels)",
                "!has(object.metadata.annotations)",
                'object.spec.all(field, field == "params" || field in variables.spec)',
                "variables.spec.all(field, field in object.spec && object.spec[field] == variables.spec[field])",
                f"variables.params.map(param, param.name) == {json.dumps(IMAGE_PARAMS)}",
                BUILDS_WHAT_IS_NAMED,
            ],
        },
        IMAGE_SOURCE_POLICY: {
            "asked": {**IMAGE_ASKED_OF, "paramKind": SOURCE_KIND},
            "variables": {"named": f"{json.dumps(IMAGE_SOURCES)}[params.metadata.name]"},
            "validations": [FOR_A_SOURCE],
        },
    }
    exactly("the labels release-run.yaml carries", release_run["metadata"].get("labels"), None)
    exactly(
        "the parameters the two sources are held to",
        sorted(parameter for named in SOURCES.values() for parameter in named.values()),
        sorted(parameters),
    )
    for file, image_run in image_runs.items():
        exactly(
            f"the parameters {file} is held to",
            [name for name in IMAGE_PARAMS if name not in ("image", "dockerfile")],
            [parameter for named in IMAGE_SOURCES.values() for parameter in named.values()][:2],
        )
    policies = {name: policy["spec"] for name, policy in of(cluster, "ValidatingAdmissionPolicy").items()}
    exactly("the admission policies rendered", sorted(policies), sorted(expected))
    for name, held in expected.items():
        policy = policies[name]
        exactly(
            f"whom and what ValidatingAdmissionPolicy {name} is asked about",
            {field: value for field, value in policy.items() if field not in ("variables", "validations")},
            held["asked"],
        )
        exactly(
            f"what ValidatingAdmissionPolicy {name} names",
            {variable["name"]: tokens(variable["expression"]) for variable in policy["variables"]},
            {variable: tokens(expression) for variable, expression in held["variables"].items()},
        )
        exactly(
            f"what ValidatingAdmissionPolicy {name} holds a run to",
            [tokens(validation["expression"]) for validation in policy["validations"]],
            [tokens(expression) for expression in held["validations"]],
        )
    exactly(
        "the bindings of the admission policies",
        {name: binding["spec"] for name, binding in of(cluster, "ValidatingAdmissionPolicyBinding").items()},
        {
            RUN_POLICY: {"policyName": RUN_POLICY, "validationActions": ["Deny"]},
            **{
                f"release-trigger-runs-what-{source}-holds": {
                    "policyName": SOURCE_POLICY,
                    "validationActions": ["Deny"],
                    "paramRef": {"name": source, "namespace": sources_namespace, "parameterNotFoundAction": "Deny"},
                }
                for source in SOURCES
            },
            IMAGE_RUN_POLICY: {"policyName": IMAGE_RUN_POLICY, "validationActions": ["Deny"]},
            **{
                f"image-trigger-builds-what-{source}-holds": {
                    "policyName": IMAGE_SOURCE_POLICY,
                    "validationActions": ["Deny"],
                    "paramRef": {"name": source, "namespace": sources_namespace, "parameterNotFoundAction": "Allow"},
                }
                for source in IMAGE_SOURCES
            },
        },
    )


def carried(configs, file):
    """The one copy of a run file the trigger namespace's ConfigMaps carry."""
    found = [config["data"][file] for config in configs.values() if file in config["data"]]
    if len(found) != 1:
        refuse(f"{len(found)} ConfigMaps in {TRIGGER_NAMESPACE} carry {file}, not one")
    return found[0]


def cronjob_is_held(cluster, name, account):
    """One trigger's CronJob: its timing, its Job, its pod and its container,
    each to what every trigger's is. Returns the Job and the environment."""
    cronjob = of(cluster, "CronJob", TRIGGER_NAMESPACE)[name]
    exactly(f"CronJob {name}'s concurrencyPolicy", cronjob["spec"].get("concurrencyPolicy"), "Forbid")
    job = cronjob["spec"]["jobTemplate"]["spec"]
    if not job.get("activeDeadlineSeconds"):
        refuse(f"CronJob {name} has no activeDeadlineSeconds, and a trigger that hangs holds every later one back")
    exactly(
        f"CronJob {name}'s timing",
        {field: value for field, value in cronjob["spec"].items() if field != "jobTemplate"},
        TRIGGER_TIMING,
    )
    exactly(f"CronJob {name}'s Job", {field: value for field, value in job.items() if field != "template"}, TRIGGER_JOB)
    pod = job["template"]["spec"]
    exactly(f"CronJob {name}'s ServiceAccount", pod.get("serviceAccountName"), account)
    exactly(f"what CronJob {name}'s pod carries", sorted(pod), sorted(TRIGGER_POD_FIELDS))
    exactly(f"what CronJob {name}'s pod may do", pod["securityContext"], TRIGGER_POD_SECURITY)
    (container,) = pod["containers"]
    exactly(f"what CronJob {name}'s container carries", sorted(container), sorted(TRIGGER_CONTAINER_FIELDS))
    exactly(f"what CronJob {name}'s container may do", container["securityContext"], TRIGGER_CONTAINER_SECURITY)
    for volume in pod["volumes"]:
        kinds = set(volume) - {"name"}
        if not kinds <= {"configMap", "emptyDir"}:
            refuse(f"CronJob {name} has the volume {volume['name']} of {sorted(kinds)}, and a trigger is given nothing but its script and scratch")
    for each in pod["containers"] + pod.get("initContainers", []):
        if not PINNED.fullmatch(each["image"]):
            refuse(f"CronJob {name} runs {each['image']}, which is not a tag pinned by digest")
    environment = {entry["name"]: entry.get("value") for entry in container["env"]}
    exactly(f"the namespace CronJob {name} creates runs in", environment.get("RUNS_NAMESPACE"), BUILD_NAMESPACE)
    return job, environment


def run_is_placed(subject, run, template):
    metadata = run["metadata"]
    if "name" in metadata or not metadata.get("generateName"):
        refuse(f"{subject} has a name of its own, and a second run under it is refused or takes up the first's pods")
    exactly(f"{subject}'s namespace", metadata.get("namespace"), BUILD_NAMESPACE)
    exactly(f"{subject}'s ServiceAccount", template.get("serviceAccountName"), BUILDER)
    exactly(f"{subject}'s pod template", template.get("podTemplate"), PLACEMENT)


def main():
    if len(sys.argv) < 5:
        refuse(
            "usage: release-pipeline.py RENDERED_BUILD_SYSTEM RENDERED_APPS RENDERED_FLUX BUILD_SYSTEM_DIRECTORY"
            " [RENDERED_LAYER ...]"
        )
    directory = Path(sys.argv[4])
    cluster = [document for path in sys.argv[1:4] + sys.argv[5:] for document in layer(path)]
    rendered = set()
    for document in cluster:
        metadata = document["metadata"]
        identity = (document["apiVersion"].rpartition("/")[0], document["kind"], metadata.get("namespace"), metadata.get("name"))
        if identity in rendered:
            refuse(f"{document['kind']} {metadata.get('name')} is rendered twice, and two layers that apply one object each put their own back")
        rendered.add(identity)

    for kind in ("PipelineRun", "TaskRun"):
        if of(cluster, kind):
            refuse(f"the render holds the {kind} {sorted(of(cluster, kind))}, and what Flux applies is started at every reconcile")

    tasks = of(cluster, "Task", BUILD_NAMESPACE)
    exactly("the Tasks rendered", sorted(of(cluster, "Task")), sorted(tasks))
    tasks_are_sound(cluster, tasks)
    pipeline = of(cluster, "Pipeline", BUILD_NAMESPACE).get(PIPELINE)
    if pipeline is None:
        refuse(f"Pipeline {PIPELINE} is not rendered in {BUILD_NAMESPACE}")
    params = pipeline_is_sound(pipeline, tasks)

    # The manifests for a run.
    trigger_configs = of(cluster, "ConfigMap", TRIGGER_NAMESPACE)
    (release_run,) = objects(carried(trigger_configs, RUN_FILE))
    exactly("release-run.yaml's kind", (release_run["apiVersion"], release_run["kind"]), ("tekton.dev/v1", "PipelineRun"))
    run_is_placed("release-run.yaml", release_run, release_run["spec"].get("taskRunTemplate", {}))
    exactly("release-run.yaml's pipeline", release_run["spec"]["pipelineRef"], {"name": PIPELINE})
    exactly("what release-run.yaml's spec carries", sorted(release_run["spec"]), sorted(RUN_FIELDS))
    exactly("release-run.yaml's timeouts", release_run["spec"]["timeouts"], RUN_TIMEOUTS)
    finally_is_sound(cluster, pipeline, tasks, params, release_run)
    exactly(
        "what release-run.yaml passes",
        sorted(param["name"] for param in release_run["spec"]["params"]),
        sorted(params),
    )
    image_runs = {}
    for cronjob, trigger in IMAGE_TRIGGERS.items():
        file = trigger["run"]
        (run,) = objects(carried(trigger_configs, file))
        exactly(f"{file}'s kind", (run["apiVersion"], run["kind"]), ("tekton.dev/v1", "TaskRun"))
        run_is_placed(file, run, run["spec"])
        exactly(f"{file}'s Task", run["spec"]["taskRef"], {"name": BUILD_TASK, "kind": "Task"})
        exactly(f"what {file}'s spec carries", sorted(run["spec"]), sorted(IMAGE_RUN_FIELDS))
        exactly(f"{file}'s timeout", run["spec"]["timeout"], RUN_TIMEOUTS["pipeline"])
        exactly(f"what {file} passes", [param["name"] for param in run["spec"]["params"]], IMAGE_PARAMS)
        passes_what_is_declared(file, set(IMAGE_PARAMS), tasks[BUILD_TASK])
        exactly(f"the labels {file} carries", run["metadata"].get("labels"), None)
        exactly(f"the annotations {file} carries", run["metadata"].get("annotations"), None)
        image_runs[file] = run
    by_hand = {}
    for file in BY_HAND:
        (run,) = objects((directory / file).read_text())
        exactly(f"{file}'s kind", (run["apiVersion"], run["kind"]), ("tekton.dev/v1", "TaskRun"))
        run_is_placed(file, run, run["spec"])
        task = tasks.get(run["spec"]["taskRef"]["name"])
        if task is None:
            refuse(f"{file} is of {run['spec']['taskRef']}, which is not a Task rendered in {BUILD_NAMESPACE}")
        passes_what_is_declared(file, {param["name"] for param in run["spec"]["params"]}, task)
        by_hand[file] = run
    builder_egress = two_platforms_are_held(tasks, by_hand)

    # No token, and no role, for a task pod.
    builder = of(cluster, "ServiceAccount", BUILD_NAMESPACE).get(BUILDER)
    if builder is None or builder.get("automountServiceAccountToken") is not False:
        refuse(f"ServiceAccount {BUILDER} in {BUILD_NAMESPACE} does not say it mounts no token")
    exactly(f"what ServiceAccount {BUILDER} carries", sorted(set(builder) - {"apiVersion", "kind", "metadata", "automountServiceAccountToken"}), [])

    everyone = of(cluster, "RoleBinding", EVERYONE["namespace"]).get(EVERYONE["name"])
    if everyone is not None:
        role = of(cluster, "Role", EVERYONE["namespace"]).get(EVERYONE["name"], {})
        exactly(
            f"what RoleBinding {EVERYONE['name']} gives everyone who is authenticated",
            {"subjects": everyone.get("subjects"), "role": everyone["roleRef"], "rules": role.get("rules")},
            {field: EVERYONE[field] for field in ("subjects", "role", "rules")},
        )

    def bound_to(account, namespace):
        return [
            binding
            for binding in cluster
            if binding["kind"] in ("RoleBinding", "ClusterRoleBinding")
            and binding is not everyone
            and any(answers_to(subject, account, namespace) for subject in binding.get("subjects") or [])
        ]

    if bound_to(BUILDER, BUILD_NAMESPACE):
        refuse(f"ServiceAccount {BUILDER} is bound by {[binding['metadata']['name'] for binding in bound_to(BUILDER, BUILD_NAMESPACE)]}, and a task pod has no rights")

    # The trigger: alone in its namespace, and its rights exact.
    in_trigger = sorted(
        (document["kind"], document["metadata"]["name"])
        for document in cluster
        if document["metadata"].get("namespace") == TRIGGER_NAMESPACE
    )
    exactly(
        f"what is in {TRIGGER_NAMESPACE}",
        in_trigger,
        sorted(
            [("ServiceAccount", TRIGGER), ("CronJob", TRIGGER), ("ServiceAccount", IMAGE_TRIGGER)]
            + [("CronJob", name) for name in IMAGE_TRIGGERS]
            + [("ConfigMap", name) for name in trigger_configs]
            + [("NetworkPolicy", name) for name in TRIGGER_POLICIES]
        ),
    )
    if TRIGGER_NAMESPACE not in of(cluster, "Namespace"):
        refuse(f"Namespace {TRIGGER_NAMESPACE} is not rendered")
    exactly(
        f"the labels of Namespace {TRIGGER_NAMESPACE}",
        of(cluster, "Namespace")[TRIGGER_NAMESPACE]["metadata"].get("labels"),
        RESTRICTED,
    )
    job, environment = cronjob_is_held(cluster, TRIGGER, TRIGGER)
    exactly("the pipeline the trigger reads the runs of", environment.get("PIPELINE"), PIPELINE)
    image_jobs = {}
    for cronjob, trigger in IMAGE_TRIGGERS.items():
        image_job, image_environment = cronjob_is_held(cluster, cronjob, IMAGE_TRIGGER)
        exactly(f"the Task CronJob {cronjob} reads the runs of", image_environment.get("TASK"), BUILD_TASK)
        exactly(f"the source CronJob {cronjob} reads", image_environment.get("SOURCE"), trigger["source"])
        exactly(
            f"the image CronJob {cronjob} reads the runs by",
            image_environment.get("IMAGE"),
            param_values(image_runs[trigger["run"]])["image"],
        )
        exactly(
            f"the run file CronJob {cronjob} creates from",
            (image_environment.get("RUN_MANIFEST") or "").rpartition("/")[2],
            trigger["run"],
        )
        exactly(
            f"the namespace CronJob {cronjob} reads its source in",
            image_environment.get("SOURCES_NAMESPACE"),
            environment.get("SOURCES_NAMESPACE"),
        )
        image_jobs[cronjob] = image_job

    # Whoever is bound in the build namespace can start a pod there under a
    # label of their choosing, so it is bound to the trigger and to nobody
    # else, whichever layer renders the binding.
    exactly(
        f"the RoleBindings of {BUILD_NAMESPACE}",
        sorted(of(cluster, "RoleBinding", BUILD_NAMESPACE)),
        sorted([TRIGGER_RUNS, IMAGE_TRIGGER_RUNS]),
    )
    def rights_of(account):
        """What one trigger's ServiceAccount may do: one Role in each
        namespace, bound to it alone, by its one RoleBinding there."""
        roles = {}
        for binding in bound_to(account, TRIGGER_NAMESPACE):
            namespace = binding["metadata"].get("namespace")
            if binding["kind"] != "RoleBinding" or binding["roleRef"]["kind"] != "Role":
                refuse(f"{binding['kind']} {binding['metadata']['name']} gives {account} rights that are not a Role's")
            if len(binding["subjects"]) != 1:
                refuse(f"RoleBinding {binding['metadata']['name']} binds {account}'s Role to others as well")
            if binding["subjects"][0]["kind"] != "ServiceAccount":
                refuse(f"RoleBinding {binding['metadata']['name']} names a {binding['subjects'][0]['kind']} {account}'s token answers to, and not its ServiceAccount")
            role = of(cluster, "Role", namespace).get(binding["roleRef"]["name"])
            if role is None or namespace in roles:
                refuse(f"RoleBinding {binding['metadata']['name']} in {namespace} is not the one binding of one Role rendered there")
            roles[namespace] = role["rules"]
            others = [
                other["metadata"]["name"]
                for other in cluster
                if other["kind"] == "RoleBinding"
                and other["metadata"].get("namespace") == namespace
                and other["roleRef"]["name"] == binding["roleRef"]["name"]
                and other is not binding
            ]
            if others:
                refuse(f"Role {binding['roleRef']['name']} is {account}'s and is also bound by {others}")
        return roles

    exactly("what the trigger's ServiceAccount may do", rights_of(TRIGGER), TRIGGER_ROLES)
    exactly("what the image trigger's ServiceAccount may do", rights_of(IMAGE_TRIGGER), IMAGE_TRIGGER_ROLES)
    sources = of(cluster, "GitRepository", environment.get("SOURCES_NAMESPACE"))
    if "chuggy" not in sources:
        refuse(f"the trigger reads GitRepository chuggy in {environment.get('SOURCES_NAMESPACE')}, and no layer renders one there")
    exactly(
        "the kind of GitRepository chuggy",
        {field: sources["chuggy"][field] for field in SOURCE_KIND},
        SOURCE_KIND,
    )
    for name in IMAGE_SOURCES:
        if name not in sources:
            refuse(f"the image trigger reads GitRepository {name} in {environment.get('SOURCES_NAMESPACE')}, and no layer renders one there")
        exactly(f"the kind of GitRepository {name}", {field: sources[name][field] for field in SOURCE_KIND}, SOURCE_KIND)
    admission_is_held(cluster, release_run, image_runs, environment.get("SOURCES_NAMESPACE"))

    # The policies.
    def policies(documents, namespace):
        return {name: policy["spec"] for name, policy in of(documents, "NetworkPolicy", namespace).items()}

    exactly(f"the NetworkPolicies of {TRIGGER_NAMESPACE}", policies(cluster, TRIGGER_NAMESPACE), TRIGGER_POLICIES)
    exactly(
        "the labels the trigger's policy selects its pod by",
        job["template"]["metadata"].get("labels"),
        TRIGGER_POLICIES["release-trigger-egress"]["podSelector"]["matchLabels"],
    )
    for cronjob, trigger in IMAGE_TRIGGERS.items():
        exactly(
            f"the labels the policy of CronJob {cronjob} selects its pod by",
            image_jobs[cronjob]["template"]["metadata"].get("labels"),
            TRIGGER_POLICIES[trigger["policy"]]["podSelector"]["matchLabels"],
        )
    exactly(
        f"the NetworkPolicies of {BUILD_NAMESPACE}",
        policies(cluster, BUILD_NAMESPACE),
        {**BUILD_POLICIES, BUILDER_EGRESS: builder_egress},
    )
    registries = {name: registry_is_held(cluster, name, expected) for name, expected in REGISTRIES.items()}
    exactly(
        f"what is in {REGISTRY_NAMESPACE}",
        sorted(
            (document["kind"], document["metadata"]["name"])
            for document in cluster
            if document["metadata"].get("namespace") == REGISTRY_NAMESPACE
        ),
        sorted(REGISTRY_NAMESPACE_ALSO + [entry for registry in registries.values() for entry in registry["own"]]),
    )

    # The images' registry under two names, and one repository in the other
    # that a release is pushed to and read from.
    pushed_to, published_to = registries["registry"]["address"], registries[RELEASE_REGISTRY]["address"]
    passed = {
        entry["name"]: {param["name"]: param["value"] for param in entry["params"]}
        for entry in pipeline["spec"]["tasks"]
    }
    for build_task, named in (("build-api", "api-image"), ("build-console", "console-image")):
        pushed = passed[build_task]["image"]
        manifest = passed["publish"][named]
        if not pushed.startswith(pushed_to) or not manifest.startswith("registry.chuggy.internal/"):
            refuse(f"{build_task} pushes {pushed} and the release names {manifest}: not the registry's Service and the node's name for it")
        if pushed[len(pushed_to):] != manifest.partition("/")[2]:
            refuse(f"{build_task} pushes {pushed} and the release overrides {manifest}, which is another repository")
    release = of(cluster, "OCIRepository", "flux-system").get("chuggy-release")
    if release is None or release["spec"]["url"] != f"oci://{passed['publish']['release']}":
        refuse(f"the pipeline publishes to {passed['publish']['release']}, which is not what OCIRepository chuggy-release reads")
    if not passed["publish"]["release"].startswith(published_to):
        refuse(f"the pipeline publishes to {passed['publish']['release']}, which is not the release registry's Service")
    for file, run in {**by_hand, **image_runs}.items():
        image = param_values(run)["image"]
        if not image.startswith(pushed_to):
            refuse(f"{file} pushes {image}, which is not the registry's Service")


if __name__ == "__main__":
    main()
