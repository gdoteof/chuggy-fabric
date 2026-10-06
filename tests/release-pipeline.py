#!/usr/bin/env python3
"""Refuse a release pipeline whose manifests are not what its files argue.

Every assertion is made against `kubectl kustomize` output, except for the
one manifest nothing renders: worker-image-run.yaml is read as a file, and
release-run.yaml as the trigger's ConfigMap carries it.

NO TASK POD HAS A TOKEN. A run's pods are placed by the run, so both
manifests for one name the `builder` ServiceAccount and a pod template that
mounts no token, `builder` mounts none itself and is bound to no role, and no
Task has a volume that is anything but a ConfigMap or an empty directory.

ONLY THE TRIGGER IS GIVEN A ROUTE TO THE API SERVER. The build namespace's
two policies are held to what they were before the pipeline: a rule widened
for a task is a route for every task. The trigger's namespace holds the
trigger and nothing else, its two policies are held exactly, and so are the
two Roles its ServiceAccount is bound to, which are bound to nobody else. The
registry admits task pods and source-controller and no third reader.

A RUN STARTED BY FLUX IS A RUN STARTED AT EVERY RECONCILE, so neither run
manifest is rendered. THE TRIGGER IS SUSPENDED: it starts nothing until a
commit says so. That the two release layers still read git is held by
tests/flux-layers.py, beside the two sources.

EVERY IMAGE IS PINNED BY DIGEST, and every step names its `command`, without
which Tekton asks the image's registry for the entrypoint.

WHAT ONLY A RUN WOULD OTHERWISE SHOW is held here because the trigger is
suspended and nothing runs one: a Task a Pipeline names that is not there, a
parameter passed that is not declared or declared and never passed, a script
that is not in the ConfigMap a step mounts, a reference to a result no task
writes, the image a build pushes under one name and the release overrides
under another path, the source the trigger reads in a namespace where it is
not, and a release pushed to a repository the Flux source does not read.
"""

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

REGISTRY_POLICY = {
    "podSelector": {"matchLabels": {"app": "registry"}},
    "policyTypes": ["Ingress", "Egress"],
    "ingress": [
        {
            "from": [
                {
                    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": BUILD_NAMESPACE}},
                    "podSelector": TASK_PODS,
                },
                {
                    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "flux-system"}},
                    "podSelector": {"matchLabels": {"app": "source-controller"}},
                },
            ],
            "ports": [{"protocol": "TCP", "port": 5000}],
        }
    ],
}

TRIGGER_ROLES = {
    "flux-system": [
        {
            "apiGroups": ["source.toolkit.fluxcd.io"],
            "resources": ["gitrepositories"],
            "resourceNames": ["chuggy", "fabric-release"],
            "verbs": ["get"],
        }
    ],
    BUILD_NAMESPACE: [
        {"apiGroups": ["tekton.dev"], "resources": ["pipelineruns"], "verbs": ["list", "create", "delete"]}
    ],
}

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


def references(value):
    if isinstance(value, str):
        yield from REFERENCE.findall(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def tasks_are_sound(build, tasks):
    configs = of(build, "ConfigMap", BUILD_NAMESPACE)
    for name, task in tasks.items():
        spec = task["spec"]
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


def run_is_placed(subject, run, template):
    metadata = run["metadata"]
    if "name" in metadata or not metadata.get("generateName"):
        refuse(f"{subject} has a name of its own, and a second run under it is refused or takes up the first's pods")
    exactly(f"{subject}'s namespace", metadata.get("namespace"), BUILD_NAMESPACE)
    exactly(f"{subject}'s ServiceAccount", template.get("serviceAccountName"), BUILDER)
    exactly(f"{subject}'s pod template", template.get("podTemplate"), PLACEMENT)


def main():
    if len(sys.argv) != 5:
        refuse("usage: release-pipeline.py RENDERED_BUILD_SYSTEM RENDERED_APPS RENDERED_FLUX BUILD_SYSTEM_DIRECTORY")
    build, apps, flux = (objects(Path(path).read_text()) for path in sys.argv[1:4])
    directory = Path(sys.argv[4])

    for kind in ("PipelineRun", "TaskRun"):
        if of(build, kind):
            refuse(f"the render holds the {kind} {sorted(of(build, kind))}, and what Flux applies is started at every reconcile")

    tasks = of(build, "Task", BUILD_NAMESPACE)
    exactly("the Tasks rendered", sorted(of(build, "Task")), sorted(tasks))
    tasks_are_sound(build, tasks)
    pipeline = of(build, "Pipeline", BUILD_NAMESPACE).get(PIPELINE)
    if pipeline is None:
        refuse(f"Pipeline {PIPELINE} is not rendered in {BUILD_NAMESPACE}")
    params = pipeline_is_sound(pipeline, tasks)

    # The two manifests for a run.
    trigger_configs = of(build, "ConfigMap", TRIGGER_NAMESPACE)
    carried = [config["data"][RUN_FILE] for config in trigger_configs.values() if RUN_FILE in config["data"]]
    if len(carried) != 1:
        refuse(f"{len(carried)} ConfigMaps in {TRIGGER_NAMESPACE} carry {RUN_FILE}, not one")
    (release_run,) = objects(carried[0])
    exactly("release-run.yaml's kind", (release_run["apiVersion"], release_run["kind"]), ("tekton.dev/v1", "PipelineRun"))
    run_is_placed("release-run.yaml", release_run, release_run["spec"].get("taskRunTemplate", {}))
    exactly("release-run.yaml's pipeline", release_run["spec"]["pipelineRef"], {"name": PIPELINE})
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
    builder = of(build, "ServiceAccount", BUILD_NAMESPACE).get(BUILDER)
    if builder is None or builder.get("automountServiceAccountToken") is not False:
        refuse(f"ServiceAccount {BUILDER} in {BUILD_NAMESPACE} does not say it mounts no token")
    exactly(f"what ServiceAccount {BUILDER} carries", sorted(set(builder) - {"apiVersion", "kind", "metadata", "automountServiceAccountToken"}), [])

    def bound_to(account, namespace):
        return [
            binding
            for binding in build
            if binding["kind"] in ("RoleBinding", "ClusterRoleBinding")
            and any(
                subject.get("kind") == "ServiceAccount"
                and subject.get("name") == account
                and subject.get("namespace") == namespace
                for subject in binding.get("subjects") or []
            )
        ]

    if bound_to(BUILDER, BUILD_NAMESPACE):
        refuse(f"ServiceAccount {BUILDER} is bound by {[binding['metadata']['name'] for binding in bound_to(BUILDER, BUILD_NAMESPACE)]}, and a task pod has no rights")

    # The trigger: suspended, alone in its namespace, and its rights exact.
    in_trigger = sorted(
        (document["kind"], document["metadata"]["name"])
        for document in build
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
    if TRIGGER_NAMESPACE not in of(build, "Namespace"):
        refuse(f"Namespace {TRIGGER_NAMESPACE} is not rendered")
    cronjob = of(build, "CronJob", TRIGGER_NAMESPACE)[TRIGGER]
    if cronjob["spec"].get("suspend") is not True:
        refuse(f"CronJob {TRIGGER} is not suspended, and it starts a release for every commit as soon as it is applied")
    exactly(f"CronJob {TRIGGER}'s concurrencyPolicy", cronjob["spec"].get("concurrencyPolicy"), "Forbid")
    job = cronjob["spec"]["jobTemplate"]["spec"]
    if not job.get("activeDeadlineSeconds"):
        refuse(f"CronJob {TRIGGER} has no activeDeadlineSeconds, and a trigger that hangs holds every later one back")
    pod = job["template"]["spec"]
    exactly(f"CronJob {TRIGGER}'s ServiceAccount", pod.get("serviceAccountName"), TRIGGER)
    for container in pod["containers"] + pod.get("initContainers", []):
        if not PINNED.fullmatch(container["image"]):
            refuse(f"CronJob {TRIGGER} runs {container['image']}, which is not a tag pinned by digest")
    environment = {entry["name"]: entry.get("value") for entry in pod["containers"][0]["env"]}
    exactly("the namespace the trigger creates runs in", environment.get("RUNS_NAMESPACE"), BUILD_NAMESPACE)
    exactly("the pipeline the trigger reads the runs of", environment.get("PIPELINE"), PIPELINE)

    bindings = bound_to(TRIGGER, TRIGGER_NAMESPACE)
    roles = {}
    for binding in bindings:
        namespace = binding["metadata"].get("namespace")
        if binding["kind"] != "RoleBinding" or binding["roleRef"]["kind"] != "Role":
            refuse(f"{binding['kind']} {binding['metadata']['name']} gives the trigger rights that are not a Role's")
        if len(binding["subjects"]) != 1:
            refuse(f"RoleBinding {binding['metadata']['name']} binds the trigger's Role to others as well")
        role = of(build, "Role", namespace).get(binding["roleRef"]["name"])
        if role is None or namespace in roles:
            refuse(f"RoleBinding {binding['metadata']['name']} in {namespace} is not the one binding of one Role rendered there")
        roles[namespace] = role["rules"]
        others = [
            other["metadata"]["name"]
            for other in build
            if other["kind"] == "RoleBinding"
            and other["metadata"].get("namespace") == namespace
            and other["roleRef"]["name"] == binding["roleRef"]["name"]
            and other is not binding
        ]
        if others:
            refuse(f"Role {binding['roleRef']['name']} is the trigger's and is also bound by {others}")
    exactly("what the trigger's ServiceAccount may do", roles, TRIGGER_ROLES)
    sources = of(flux, "GitRepository", environment.get("SOURCES_NAMESPACE"))
    if "chuggy" not in sources:
        refuse(f"the trigger reads GitRepository chuggy in {environment.get('SOURCES_NAMESPACE')}, and cluster/flux renders none there")

    # The policies.
    def policies(documents, namespace):
        return {name: policy["spec"] for name, policy in of(documents, "NetworkPolicy", namespace).items()}

    exactly(f"the NetworkPolicies of {TRIGGER_NAMESPACE}", policies(build, TRIGGER_NAMESPACE), TRIGGER_POLICIES)
    exactly(
        "the labels the trigger's policy selects its pod by",
        job["template"]["metadata"].get("labels"),
        TRIGGER_POLICIES["release-trigger-egress"]["podSelector"]["matchLabels"],
    )
    exactly(f"the NetworkPolicies of {BUILD_NAMESPACE}", policies(build, BUILD_NAMESPACE), BUILD_POLICIES)
    registry = [
        spec
        for spec in policies(apps, "chuggy-registry").values()
        if spec["podSelector"] == REGISTRY_POLICY["podSelector"]
    ]
    exactly("the NetworkPolicies that select the registry", registry, [REGISTRY_POLICY])

    # One registry under two names, and one repository a release is pushed to
    # and read from.
    service = of(apps, "Service", "chuggy-registry").get("registry")
    if service is None:
        refuse("cluster/apps renders no Service registry in chuggy-registry")
    pushed_to = f"registry.chuggy-registry.svc.cluster.local:{service['spec']['ports'][0]['port']}/"
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
    release = of(flux, "OCIRepository", "flux-system").get("chuggy-release")
    if release is None or release["spec"]["url"] != f"oci://{passed['publish']['release']}":
        refuse(f"the pipeline publishes to {passed['publish']['release']}, which is not what OCIRepository chuggy-release reads")
    if not passed["publish"]["release"].startswith(pushed_to):
        refuse(f"the pipeline publishes to {passed['publish']['release']}, which is not the registry's Service")
    worker = {param["name"]: param["value"] for param in worker_run["spec"]["params"]}
    if not worker["image"].startswith(pushed_to):
        refuse(f"worker-image-run.yaml pushes {worker['image']}, which is not the registry's Service")


if __name__ == "__main__":
    main()
