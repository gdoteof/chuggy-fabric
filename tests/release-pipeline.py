#!/usr/bin/env python3
"""Refuse a release pipeline whose manifests are not what its files argue.

usage: release-pipeline.py RENDERED_BUILD_SYSTEM RENDERED_APPS RENDERED_FLUX
           BUILD_SYSTEM_DIRECTORY [RENDERED_LAYER ...]

Every assertion is made against what the layers render, except for the one
manifest nothing renders: worker-image-run.yaml is read as a file, and
release-run.yaml as the trigger's ConfigMap carries it.

EVERY LAYER GIVEN IS READ AS ONE CLUSTER, because a namespace's policies add
up across whoever applies them, and so do its bindings: what is held of a
namespace here is held of every render this is given, and
tests/release-pipeline.nix lists them. An object two of them render is
refused. Each layer would put its own back at its interval.

NO TASK POD HAS A TOKEN. A run's pods are placed by the run, so both
manifests for one name the `builder` ServiceAccount and a pod template that
mounts no token, `builder` mounts none itself and is bound to no role, and no
Task has a volume that is anything but a ConfigMap or an empty directory.

ONLY THE TRIGGER IS GIVEN A ROUTE TO THE API SERVER. The build namespace's
policies are held exactly: `build-egress` to what it was before the pipeline,
because a rule widened for a task is a route for every task, and one rule
beside it for the pods of `publish-release` alone. The trigger's namespace
holds the trigger and nothing else, its two policies are held exactly, and so
are the two Roles its ServiceAccount is bound to, which are bound to nobody
else. A binding counts when it names the ServiceAccount, or the user or a
group its token also is.

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
manifest is rendered. THE TRIGGER IS SUSPENDED: it starts nothing until a
commit says so. That the two release layers read what a run publishes is held
by tests/flux-layers.py, beside the two sources.

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
needs to start nothing.

WHAT ONLY A RUN WOULD OTHERWISE SHOW is held here because the trigger is
suspended and nothing runs one: a Task a Pipeline names that is not there, a
parameter passed that is not declared or declared and never passed, a script
that is not in the ConfigMap a step mounts, a reference to a result no task
writes, the image a build pushes under one name and the release overrides
under another path, the source the trigger reads in a namespace where it is
not, and a release pushed to a repository the Flux source does not read, or
to a registry that is not the release registry's Service.
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

TRIGGER_POLICIES = {
    "release-trigger-default-deny": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
    "release-trigger-egress": {
        "podSelector": {"matchLabels": {"app": "release-trigger"}},
        "policyTypes": ["Egress"],
        "egress": [
            KUBE_DNS,
            {
                "to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": ["10.42.0.0/16", "10.43.0.0/16"]}}],
                "ports": [{"protocol": "TCP", "port": 6443}],
            },
        ],
    },
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

# The steps of each Task, in order, and what each may do.
STEPS = {
    "build-image": {
        "fetch": {**CONFINED, **AS_BUILDKIT},
        "build": {
            "runAsNonRoot": True,
            **AS_BUILDKIT,
            "allowPrivilegeEscalation": True,
            "capabilities": {"add": ["SETGID", "SETUID"], "drop": ["ALL"]},
            "readOnlyRootFilesystem": True,
            "seccompProfile": {"type": "Unconfined"},
            "appArmorProfile": {"type": "Unconfined"},
        },
    },
    "publish-release": {
        "fetch": {**CONFINED, **AS_BUILDKIT},
        "publish": {**CONFINED, **AS_NOBODY},
    },
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

# What admission asks of a PipelineRun the trigger's ServiceAccount creates.
RUN_POLICY = "release-trigger-creates-the-release-run"
SOURCE_POLICY = "release-trigger-runs-what-a-source-holds"
ASKED_OF = {
    "failurePolicy": "Fail",
    "matchConstraints": {
        "resourceRules": [
            {"apiGroups": ["tekton.dev"], "apiVersions": ["*"], "operations": ["CREATE"], "resources": ["pipelineruns"]}
        ]
    },
    "matchConditions": [
        {
            "name": "created-by-the-release-trigger",
            "expression": f'request.userInfo.username == "system:serviceaccount:{TRIGGER_NAMESPACE}:{TRIGGER}"',
        }
    ],
}
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
        for volume in spec.get("volumes", []):
            kinds = set(volume) - {"name"}
            if not kinds <= {"configMap", "emptyDir"}:
                refuse(f"Task {name} has the volume {volume['name']} of {sorted(kinds)}, and a task pod is given nothing but scripts and scratch")
            volumes[volume["name"]] = volume
        for step in spec["steps"]:
            subject = f"Task {name} step {step['name']}"
            if not PINNED.fullmatch(step["image"]):
                refuse(f"{subject} runs {step['image']}, which is not a tag pinned by digest")
            command = step.get("command")
            if "script" in step or not command or command[0] != "/bin/sh" or len(command) != 2:
                refuse(f"{subject} does not name a `command` that is /bin/sh over one script file")
            exactly(f"what {subject} carries beyond {sorted(STEP_FIELDS)}", sorted(set(step) - STEP_FIELDS), [])
            exactly(f"what {subject} may do", step.get("securityContext"), STEPS[name][step["name"]])
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


def passes_what_is_declared(subject, passed, task):
    declared = {param["name"]: param for param in task["spec"].get("params", [])}
    for name in passed:
        if name not in declared:
            refuse(f"{subject} passes `{name}`, which Task {task['metadata']['name']} does not declare")
    for name, param in declared.items():
        if "default" not in param and name not in passed:
            refuse(f"{subject} does not pass `{name}`, which Task {task['metadata']['name']} requires")


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
    for reference in references(spec):
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


def admission_is_held(cluster, release_run, sources_namespace):
    run = release_run["spec"]
    annotations = json.dumps(list(release_run["metadata"]["annotations"]))
    parameters = [param["name"] for param in run["params"]]
    expected = {
        RUN_POLICY: {
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
            "paramKind": SOURCE_KIND,
            "variables": {"named": f"{json.dumps(SOURCES)}[params.metadata.name]"},
            "validations": [FOR_A_SOURCE],
        },
    }
    exactly("the labels release-run.yaml carries", release_run["metadata"].get("labels"), None)
    exactly(
        "the parameters the two sources are held to",
        sorted(parameter for named in SOURCES.values() for parameter in named.values()),
        sorted(parameters),
    )
    policies = {name: policy["spec"] for name, policy in of(cluster, "ValidatingAdmissionPolicy").items()}
    exactly("the admission policies rendered", sorted(policies), sorted(expected))
    for name, held in expected.items():
        policy = policies[name]
        exactly(
            f"whom and what ValidatingAdmissionPolicy {name} is asked about",
            {field: value for field, value in policy.items() if field not in ("variables", "validations")},
            {**ASKED_OF, **{field: value for field, value in held.items() if field == "paramKind"}},
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
        },
    )


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

    # The two manifests for a run.
    trigger_configs = of(cluster, "ConfigMap", TRIGGER_NAMESPACE)
    carried = [config["data"][RUN_FILE] for config in trigger_configs.values() if RUN_FILE in config["data"]]
    if len(carried) != 1:
        refuse(f"{len(carried)} ConfigMaps in {TRIGGER_NAMESPACE} carry {RUN_FILE}, not one")
    (release_run,) = objects(carried[0])
    exactly("release-run.yaml's kind", (release_run["apiVersion"], release_run["kind"]), ("tekton.dev/v1", "PipelineRun"))
    run_is_placed("release-run.yaml", release_run, release_run["spec"].get("taskRunTemplate", {}))
    exactly("release-run.yaml's pipeline", release_run["spec"]["pipelineRef"], {"name": PIPELINE})
    exactly("what release-run.yaml's spec carries", sorted(release_run["spec"]), sorted(RUN_FIELDS))
    exactly("release-run.yaml's timeouts", release_run["spec"]["timeouts"], RUN_TIMEOUTS)
    exactly(
        "what release-run.yaml passes",
        sorted(param["name"] for param in release_run["spec"]["params"]),
        sorted(params),
    )
    (worker_run,) = objects((directory / "worker-image-run.yaml").read_text())
    exactly("worker-image-run.yaml's kind", (worker_run["apiVersion"], worker_run["kind"]), ("tekton.dev/v1", "TaskRun"))
    run_is_placed("worker-image-run.yaml", worker_run, worker_run["spec"])
    worker_task = tasks.get(worker_run["spec"]["taskRef"]["name"])
    if worker_task is None:
        refuse(f"worker-image-run.yaml is of {worker_run['spec']['taskRef']}, which is not a Task rendered in {BUILD_NAMESPACE}")
    passes_what_is_declared(
        "worker-image-run.yaml", {param["name"] for param in worker_run["spec"]["params"]}, worker_task
    )

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

    # The trigger: suspended, alone in its namespace, and its rights exact.
    in_trigger = sorted(
        (document["kind"], document["metadata"]["name"])
        for document in cluster
        if document["metadata"].get("namespace") == TRIGGER_NAMESPACE
    )
    exactly(
        f"what is in {TRIGGER_NAMESPACE}",
        in_trigger,
        sorted(
            [("ServiceAccount", TRIGGER), ("CronJob", TRIGGER)]
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
    cronjob = of(cluster, "CronJob", TRIGGER_NAMESPACE)[TRIGGER]
    if cronjob["spec"].get("suspend") is not True:
        refuse(f"CronJob {TRIGGER} is not suspended, and it starts a release for every commit as soon as it is applied")
    exactly(f"CronJob {TRIGGER}'s concurrencyPolicy", cronjob["spec"].get("concurrencyPolicy"), "Forbid")
    job = cronjob["spec"]["jobTemplate"]["spec"]
    if not job.get("activeDeadlineSeconds"):
        refuse(f"CronJob {TRIGGER} has no activeDeadlineSeconds, and a trigger that hangs holds every later one back")
    exactly(
        f"CronJob {TRIGGER}'s timing",
        {name: value for name, value in cronjob["spec"].items() if name not in ("suspend", "jobTemplate")},
        TRIGGER_TIMING,
    )
    exactly(f"CronJob {TRIGGER}'s Job", {name: value for name, value in job.items() if name != "template"}, TRIGGER_JOB)
    pod = job["template"]["spec"]
    exactly(f"CronJob {TRIGGER}'s ServiceAccount", pod.get("serviceAccountName"), TRIGGER)
    exactly(f"what CronJob {TRIGGER}'s pod carries", sorted(pod), sorted(TRIGGER_POD_FIELDS))
    exactly(f"what CronJob {TRIGGER}'s pod may do", pod["securityContext"], TRIGGER_POD_SECURITY)
    (container,) = pod["containers"]
    exactly(f"what CronJob {TRIGGER}'s container carries", sorted(container), sorted(TRIGGER_CONTAINER_FIELDS))
    exactly(f"what CronJob {TRIGGER}'s container may do", container["securityContext"], TRIGGER_CONTAINER_SECURITY)
    for volume in pod["volumes"]:
        kinds = set(volume) - {"name"}
        if not kinds <= {"configMap", "emptyDir"}:
            refuse(f"CronJob {TRIGGER} has the volume {volume['name']} of {sorted(kinds)}, and the trigger is given nothing but its script and scratch")
    for container in pod["containers"] + pod.get("initContainers", []):
        if not PINNED.fullmatch(container["image"]):
            refuse(f"CronJob {TRIGGER} runs {container['image']}, which is not a tag pinned by digest")
    environment = {entry["name"]: entry.get("value") for entry in pod["containers"][0]["env"]}
    exactly("the namespace the trigger creates runs in", environment.get("RUNS_NAMESPACE"), BUILD_NAMESPACE)
    exactly("the pipeline the trigger reads the runs of", environment.get("PIPELINE"), PIPELINE)

    # Whoever is bound in the build namespace can start a pod there under a
    # label of their choosing, so it is bound to the trigger and to nobody
    # else, whichever layer renders the binding.
    exactly(f"the RoleBindings of {BUILD_NAMESPACE}", sorted(of(cluster, "RoleBinding", BUILD_NAMESPACE)), [TRIGGER_RUNS])
    bindings = bound_to(TRIGGER, TRIGGER_NAMESPACE)
    roles = {}
    for binding in bindings:
        namespace = binding["metadata"].get("namespace")
        if binding["kind"] != "RoleBinding" or binding["roleRef"]["kind"] != "Role":
            refuse(f"{binding['kind']} {binding['metadata']['name']} gives the trigger rights that are not a Role's")
        if len(binding["subjects"]) != 1:
            refuse(f"RoleBinding {binding['metadata']['name']} binds the trigger's Role to others as well")
        if binding["subjects"][0]["kind"] != "ServiceAccount":
            refuse(f"RoleBinding {binding['metadata']['name']} names a {binding['subjects'][0]['kind']} the trigger's token answers to, and not its ServiceAccount")
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
            refuse(f"Role {binding['roleRef']['name']} is the trigger's and is also bound by {others}")
    exactly("what the trigger's ServiceAccount may do", roles, TRIGGER_ROLES)
    sources = of(cluster, "GitRepository", environment.get("SOURCES_NAMESPACE"))
    if "chuggy" not in sources:
        refuse(f"the trigger reads GitRepository chuggy in {environment.get('SOURCES_NAMESPACE')}, and no layer renders one there")
    exactly(
        "the kind of GitRepository chuggy",
        {field: sources["chuggy"][field] for field in SOURCE_KIND},
        SOURCE_KIND,
    )
    admission_is_held(cluster, release_run, environment.get("SOURCES_NAMESPACE"))

    # The policies.
    def policies(documents, namespace):
        return {name: policy["spec"] for name, policy in of(documents, "NetworkPolicy", namespace).items()}

    exactly(f"the NetworkPolicies of {TRIGGER_NAMESPACE}", policies(cluster, TRIGGER_NAMESPACE), TRIGGER_POLICIES)
    exactly(
        "the labels the trigger's policy selects its pod by",
        job["template"]["metadata"].get("labels"),
        TRIGGER_POLICIES["release-trigger-egress"]["podSelector"]["matchLabels"],
    )
    exactly(f"the NetworkPolicies of {BUILD_NAMESPACE}", policies(cluster, BUILD_NAMESPACE), BUILD_POLICIES)
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
    worker = {param["name"]: param["value"] for param in worker_run["spec"]["params"]}
    if not worker["image"].startswith(pushed_to):
        refuse(f"worker-image-run.yaml pushes {worker['image']}, which is not the registry's Service")


if __name__ == "__main__":
    main()
