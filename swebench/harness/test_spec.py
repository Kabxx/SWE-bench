import hashlib
import json
import platform
import re
import toml
from tqdm.auto import tqdm
import logging
import os,requests
from dataclasses import dataclass
from typing import Any, Union, cast

from swebench.harness.constants import (
    SWEbenchInstance,
    KEY_INSTANCE_ID,
    FAIL_TO_PASS,
    PASS_TO_PASS,
    MAP_REPO_TO_INSTALL,
    MAP_REPO_TO_REQS_PATHS,
    MAP_REPO_VERSION_TO_SPECS,
    USE_X86,
    SWE_BENCH_URL_RAW
)
from swebench.harness.dockerfiles import (
    get_dockerfile_base,
    get_dockerfile_env,
    get_dockerfile_instance,
)
from swebench.harness.utils import (
    get_requirements,
    get_test_directives,
    clean_cargo_toml,
    clean_workspace_cargo_toml,
    get_rust_test_command,
    clean_comment
)

logger = logging.getLogger(__name__)

DIFF_MODIFIED_FILE_REGEX = r"--- a/(.*)"


@dataclass
class TestSpec:
    """
    A dataclass that represents a test specification for a single instance of SWE-bench.
    """
    instance_id: str
    repo: str
    version: str
    repo_script_list: list[str]
    eval_script_list: list[str]
    env_script_list: list[str]
    arch: str
    cargo_toml: str
    FAIL_TO_PASS: list[str]
    PASS_TO_PASS: list[str]
    tests_changed: list[str]

    @property
    def setup_env_script(self):
        return "\n".join(["#!/bin/bash", "set -euxo pipefail"] + self.env_script_list) + "\n"

    @property
    def eval_script(self):
        return "\n".join(["#!/bin/bash", "set -uxo pipefail"] + self.eval_script_list) + "\n"
        # Don't exit early because we need to revert tests at the end

    @property
    def install_repo_script(self):
        return "\n".join(["#!/bin/bash", "set -euxo pipefail"] + self.repo_script_list) + "\n"

    @property
    def base_image_key(self):
        return f"sweb.base.{self.arch}:latest"

    @property
    def env_image_key(self):
        """
        The key for the environment image is based on the hash of the environment script list.
        If the environment script list changes, the image will be rebuilt automatically.

        Note that old images are not automatically deleted, so consider cleaning up old images periodically.
        """
        hash_object = hashlib.sha256()
        hash_object.update(str(self.env_script_list).encode("utf-8"))
        hash_value = hash_object.hexdigest()
        val = hash_value[:22]  # 22 characters is still very likely to be unique
        return f"sweb.env.{self.arch}.{val}:latest"

    @property
    def instance_image_key(self):
        return f"sweb.eval.{self.arch}.{self.instance_id}:latest"

    def get_instance_container_name(self, run_id=None):
        if not run_id:
            return f"sweb.eval.{self.instance_id}"
        return f"sweb.eval.{self.instance_id}.{run_id}"

    @property
    def base_dockerfile(self):
        return get_dockerfile_base(self.platform, self.arch)

    @property
    def env_dockerfile(self):
        return get_dockerfile_env(self.platform, self.arch)

    @property
    def instance_dockerfile(self):
        return get_dockerfile_instance(self.platform, self.env_image_key)

    @property
    def platform(self):
        if self.arch == "x86_64":
            return "linux/x86_64"
        elif self.arch == "arm64":
            return "linux/arm64/v8"
        else:
            raise ValueError(f"Invalid architecture: {self.arch}")


def get_test_specs_from_dataset(dataset: Union[list[SWEbenchInstance], list[TestSpec]]) -> list[TestSpec]:
    """
    Idempotent function that converts a list of SWEbenchInstance objects to a list of TestSpec objects.
    """
    if isinstance(dataset[0], TestSpec):
        return cast(list[TestSpec], dataset)
    typed_dataset = cast(list[SWEbenchInstance], dataset)
    progress_bar = tqdm(typed_dataset, desc="Converting instances to test specs")
    mapped_results = map(make_test_spec, progress_bar)
    filtered_result = [item for item in mapped_results if item is not None]
    return filtered_result


def make_repo_script_list(specs, repo, repo_directory, base_commit, env_name):
    """
    Create a list of bash commands to set up the repository for testing.
    This is the setup script for the instance image.
    """
    setup_commands = [
        # f"git clone -o origin https://github.com/{repo} {repo_directory}",
        # f"chmod -R 777 {repo_directory}",  # So nonroot user can run tests
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
        # f"git remote remove origin",
    ]
    if repo in MAP_REPO_TO_INSTALL:
        setup_commands.append(MAP_REPO_TO_INSTALL[repo])

    # Run pre-install set up if provided
    if "pre_install" in specs:
        for pre_install in specs["pre_install"]:
            setup_commands.append(pre_install)

    if "install" in specs:
        setup_commands.append(specs["install"])
    return setup_commands


def make_env_script_list(instance, specs, repo, repo_directory, env_name):
    """
    Creates the list of commands to set up the conda environment for testing.
    This is the setup script for the environment image.
    """
    HEREDOC_DELIMITER = "EOF_59812759871"
    reqs_commands = [
        f"rustup default {specs['rustc']}",
        f"git clone -o origin https://github.com/{repo} {repo_directory}",
        f"chmod -R 777 {repo_directory}",  # So nonroot user can run tests
        f"cd {repo_directory}",
        f"git reset --hard {instance['environment_setup_commit']}",
        "cargo fetch"
    ]


    # if "[workspace]" in reqs:
    #     workspace_data = toml.loads(reqs)
    #     workspace_cargo_toml = clean_comment(reqs)
    #     reqs_commands.append(
    #         f"cat <<'{HEREDOC_DELIMITER}' > {path_to_reqs}\n{workspace_cargo_toml}\n{HEREDOC_DELIMITER}"
    #     )

    #     # 使用 cat 写入 main.rs 文件
    #     reqs_commands.append(
    #         f"mkdir -p src && cat <<'{HEREDOC_DELIMITER}' > src/main.rs\nfn main() {{}}\n{HEREDOC_DELIMITER}"
    #     )

    #     members = workspace_data.get('workspace', {}).get('members', [])
    #     for member in members:
    #         toml_path = os.path.join(member, "Cargo.toml")
    #         member_reqs = get_requirements(instance, toml_path)
    #         member_reqs = clean_comment(member_reqs)

    #         # 使用 cat 写入 main.rs 和 lib.rs 文件
    #         reqs_commands.append(
    #             f"mkdir -p {member}/src && cat <<'{HEREDOC_DELIMITER}' > {member}/src/main.rs\nfn main() {{}}\n{HEREDOC_DELIMITER}"
    #         )
    #         reqs_commands.append(
    #             f"cat <<'{HEREDOC_DELIMITER}' > {member}/src/lib.rs\npub fn hello() {{}}\n{HEREDOC_DELIMITER}"
    #         )
    #         reqs_commands.append(
    #             f"cat <<'{HEREDOC_DELIMITER}' > {toml_path}\n{member_reqs}\n{HEREDOC_DELIMITER}"
    #         )
    # else:
    #     cleaned_reqs = clean_comment(reqs)
    #     reqs_commands.append(
    #         f"cat <<'{HEREDOC_DELIMITER}' > {path_to_reqs}\n{cleaned_reqs}\n{HEREDOC_DELIMITER}"
    #     )

        # # 使用 cat 写入 src 目录下的 main.rs 和 lib.rs 文件
        # reqs_commands.append(
        #     f"mkdir -p src && cat <<'{HEREDOC_DELIMITER}' > src/main.rs\nfn main() {{}}\n{HEREDOC_DELIMITER}"
        # )
        # reqs_commands.append(
        #     f"cat <<'{HEREDOC_DELIMITER}' > src/lib.rs\npub fn hello() {{}}\n{HEREDOC_DELIMITER}"
        # )

    return reqs_commands


def make_eval_script_list(instance, specs, env_name, repo_directory, base_commit, test_patch):
    """
    Applies the test patch and runs the tests.
    """
    HEREDOC_DELIMITER = "EOF_114329324912"
    test_files = re.findall(DIFF_MODIFIED_FILE_REGEX, test_patch)
    # Reset test files to the state they should be in before the patch.
    reset_tests_command = f"git checkout {base_commit} {' '.join(test_files)}"
    apply_test_patch_command = (
        f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{test_patch}\n{HEREDOC_DELIMITER}"
    )
    test_command = f"{MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]["test_cmd"]}"
    eval_commands = []
    if "eval_commands" in specs:
        eval_commands += specs["eval_commands"]
    eval_commands += [
        f"git config --global --add safe.directory {repo_directory}",  # for nonroot user
        f"cd {repo_directory}",
        # This is just informational, so we have a record
        f"git status",
        f"git show",
        # f"git diff {base_commit}",
        # "source /opt/miniconda3/bin/activate",
        # f"conda activate {env_name}",
    ]
    if "install" in specs:
        eval_commands.append(specs["install"])
    eval_commands += [
        reset_tests_command,
        apply_test_patch_command,
        test_command,
        reset_tests_command,  # Revert tests after done, leave the repo in the same state as before
    ]
    return eval_commands


def make_test_spec(instance: SWEbenchInstance) -> TestSpec | None:
    if isinstance(instance, TestSpec):
        return instance
    if "version" not in instance:
        logger.warning(f"Instance {instance['instance_id']} does not have a version field, skipping")
        return None
    instance_id = instance[KEY_INSTANCE_ID]
    repo = instance["repo"]
    version = instance["version"]
    base_commit = instance["base_commit"]
    problem_statement = instance["problem_statement"]
    hints_text = instance["hints_text"]  # Unused
    test_patch = instance["test_patch"]

    def _from_json_or_obj(key: str) -> Any:
        """If key points to string, load with json"""
        if isinstance(instance[key], str):
            return json.loads(instance[key])
        return instance[key]

    pass_to_pass = _from_json_or_obj(PASS_TO_PASS)
    fail_to_pass = _from_json_or_obj(FAIL_TO_PASS)

    env_name = "testbed"
    repo_directory = f"/{env_name}"
    specs = MAP_REPO_VERSION_TO_SPECS[repo][version]

    repo_script_list = make_repo_script_list(specs, repo, repo_directory, base_commit, env_name)
    try:
        env_script_list = make_env_script_list(instance, specs, repo, repo_directory, env_name)
    except Exception as e:
        logger.warning(f"Failed to create make env script for {instance_id}: {e}")
        return None
    eval_script_list = make_eval_script_list(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    if platform.machine() in {"aarch64", "arm64"}:
        # use arm64 unless explicitly specified
        arch = "arm64" if instance_id not in USE_X86 else "x86_64"
    else:
        arch = "x86_64"

    # get cargo.toml
    req_path = MAP_REPO_TO_REQS_PATHS[repo]
    reqs_url = os.path.join(SWE_BENCH_URL_RAW, repo, base_commit, req_path[0])
    reqs = requests.get(reqs_url)
    cargo_toml = reqs.text

    tests_changed = get_test_directives(instance)


    return TestSpec(
        instance_id=instance_id,
        repo=repo,
        env_script_list=env_script_list,
        repo_script_list=repo_script_list,
        eval_script_list=eval_script_list,
        version=version,
        arch=arch,
        tests_changed=tests_changed,
        cargo_toml=cargo_toml,
        FAIL_TO_PASS=fail_to_pass,
        PASS_TO_PASS=pass_to_pass,
    )
