"""Customer-owned Azure component demo: run with `uv run --frozen python ...`."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from azure.core.exceptions import AzureError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OWNER_TAG = "mirae-component-demo"
OWNER_VALUE = "v1"
PROVIDERS = (
    "Microsoft.App", "Microsoft.ContainerRegistry", "Microsoft.CognitiveServices",
    "Microsoft.Search", "Microsoft.Storage", "Microsoft.Web", "Microsoft.EventGrid",
    "Microsoft.Insights", "Microsoft.OperationalInsights", "Microsoft.ManagedIdentity",
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", required=True, help="New, dedicated customer demo RG")
    parser.add_argument("--subscription", help="Defaults to the account selected by az login")
    parser.add_argument("--location", default="koreacentral")
    parser.add_argument("--model-location", help="Foundry/model region; defaults to --location")
    parser.add_argument("--principal-id", help="Deploying Entra object ID (not application/client ID)")
    parser.add_argument("--auth-mode", choices=("keys", "identity"), default="keys",
                        help="keys: Contributor-only demo; identity: needs role-assignment permission")
    parser.add_argument("--function-build", choices=("cloud", "local"), default="cloud",
                        help="cloud: build Function dependencies in ACR; local: download Linux wheels locally")
    parser.add_argument("--resource-tag", action="append", default=[], metavar="KEY=VALUE",
                        help="Explicit organization-approved tags on new demo resources; never added automatically")
    parser.add_argument("--chat-model", default="gpt-4o")
    parser.add_argument("--chat-version", default="2024-11-20")
    parser.add_argument("--chat-capacity", type=int, default=10)
    parser.add_argument("--reasoning-model", default="gpt-5.4-mini")
    parser.add_argument("--reasoning-version", default="2026-03-17")
    parser.add_argument("--reasoning-capacity", type=int, default=10)
    parser.add_argument("--embedding-capacity", type=int, default=50)
    parser.add_argument("--sample-pdf", type=Path, help="Instead of the small generated smoke-test PDF")
    parser.add_argument("--check", action="store_true", help="Read-only preflight; no resources or uploads")
    parser.add_argument("--yes", action="store_true", help="Accept creation of billable public demo resources")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.()-]{0,89}", args.resource_group):
        parser.error("Use a resource-group name containing only letters, numbers, _, -, ., (, )")
    for region in (args.location, args.model_location or args.location):
        if not re.fullmatch(r"[a-z0-9]+", region):
            parser.error("Use Azure region identifiers, for example koreacentral")
    if min(args.chat_capacity, args.reasoning_capacity, args.embedding_capacity) < 1:
        parser.error("Model capacities must be positive")
    if args.sample_pdf and (not args.sample_pdf.is_file() or args.sample_pdf.suffix.lower() != ".pdf"):
        parser.error("--sample-pdf must identify an existing PDF")
    for tag in args.resource_tag:
        if "=" not in tag or not tag.split("=", 1)[0] or tag.split("=", 1)[0] == OWNER_TAG:
            parser.error("--resource-tag must be KEY=VALUE and cannot replace the ownership tag")
    return args


def resource_tags(args) -> dict[str, str]:
    return dict(tag.split("=", 1) for tag in args.resource_tag)


def command(argv: list[str], *, json_output: bool = False):
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if result.returncode:
        # CLI stdout may contain credentials/configuration; only diagnostic stderr is shown.
        raise RuntimeError(f"{' '.join(argv[:3])} failed:\n{result.stderr.strip()}")
    if not json_output:
        return result.stdout
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{' '.join(argv[:3])} returned invalid JSON") from exc


class AzureCLI:
    def __init__(self, subscription: str):
        self.subscription = subscription

    def run(self, *args: str, json_output: bool = True):
        return command([
            "az", *args, "--subscription", self.subscription,
            "--only-show-errors", "--output", "json" if json_output else "none",
        ], json_output=json_output)


@dataclass(frozen=True)
class ModelChoice:
    name: str
    version: str
    sku: str
    capacity: int


def model_choices(args) -> list[ModelChoice]:
    return [
        ModelChoice(args.chat_model, args.chat_version, "GlobalStandard", args.chat_capacity),
        ModelChoice(args.reasoning_model, args.reasoning_version, "GlobalStandard", args.reasoning_capacity),
        ModelChoice("text-embedding-3-large", "1", "Standard", args.embedding_capacity),
    ]


def check_models(inventory: list[dict], choices: list[ModelChoice]) -> None:
    for choice in choices:
        matching = [
            row for row in inventory
            if row.get("model", {}).get("name") == choice.name
            and str(row["model"].get("version")) == choice.version
        ]
        if not matching:
            raise RuntimeError(
                f"Model {choice.name}/{choice.version} is unavailable in the selected model region. "
                "Select --model-location or a supported model/version; no fallback is applied.",
            )
        skus = [
            sku for row in matching
            for sku in (row.get("skus") or row.get("model", {}).get("skus") or [])
        ]
        if not any(sku.get("name") == choice.sku for sku in skus):
            raise RuntimeError(f"{choice.name}/{choice.version} does not offer {choice.sku} here")
        limits = next(sku for sku in skus if sku.get("name") == choice.sku).get("capacity") or {}
        minimum, maximum, step = (limits.get(name) for name in ("minimum", "maximum", "step"))
        if ((minimum is not None and choice.capacity < minimum)
                or (maximum is not None and choice.capacity > maximum)
                or (step and (choice.capacity - (minimum or 0)) % step)):
            raise RuntimeError(f"Invalid {choice.name} {choice.sku} capacity {choice.capacity}: {limits}")


def check_group_ownership(group: dict, location: str) -> None:
    if (group.get("tags") or {}).get(OWNER_TAG) != OWNER_VALUE:
        raise RuntimeError(
            "Use a new dedicated resource group. Refusing to deploy into an unrelated existing RG.",
        )
    if group["location"] != location:
        raise RuntimeError("Existing demo resource-group location differs from --location")


def check_quota(inventory: list[dict], usages: list[dict], choices: list[ModelChoice],
                existing: list[dict] | None = None) -> None:
    required: dict[str, int] = {}
    for deployment_name, choice in zip(("chat", "reasoning", "embedding"), choices):
        matching = next(
            row["model"] for row in inventory
            if row.get("model", {}).get("name") == choice.name
            and str(row["model"].get("version")) == choice.version
        )
        row = next(row for row in inventory if row.get("model") == matching)
        skus = row.get("skus") or matching.get("skus") or []
        sku = next(sku for sku in skus if sku["name"] == choice.sku)
        usage_name = sku.get("usageName")
        if not usage_name:
            raise RuntimeError(f"No quota identifier for {choice.name}/{choice.sku}; check Foundry quota")
        current = next((item for item in existing or [] if item["name"] == deployment_name), None)
        retained = 0
        if current:
            model = current["properties"]["model"]
            if model["name"] == choice.name and current["sku"]["name"] == choice.sku:
                retained = current["sku"]["capacity"]
        required[usage_name] = required.get(usage_name, 0) + max(0, choice.capacity - retained)
    available = {row["name"]["value"]: row["limit"] - row["currentValue"] for row in usages}
    for name, amount in required.items():
        if amount and (name not in available or available[name] < amount):
            raise RuntimeError(
                f"Insufficient regional quota {name}: need {amount} additional capacity units; "
                f"available={available.get(name, 'unknown')}. Request quota or change model region/capacity.",
            )


def write_parameters(path: Path, values: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0", "parameters": values,
    }, indent=2), encoding="utf-8")


def deployment_values(args, principal: str, principal_type: str) -> dict:
    values = {
        "location": args.location, "modelLocation": args.model_location or args.location,
        "developerObjectId": principal, "developerPrincipalType": principal_type,
        "authMode": args.auth_mode,
        "resourceTags": resource_tags(args),
        "chatModelName": args.chat_model, "chatModelVersion": args.chat_version,
        "chatCapacity": args.chat_capacity,
        "reasoningModelName": args.reasoning_model, "reasoningModelVersion": args.reasoning_version,
        "reasoningCapacity": args.reasoning_capacity, "embeddingCapacity": args.embedding_capacity,
    }
    return {name: {"value": value} for name, value in values.items()}


def chat_parameters(outputs: dict, image: str, location: str) -> dict:
    env = {
        "SEARCH_ENDPOINT": outputs["searchEndpoint"],
        "SEARCH_INDEX_NARRATIVE": "narrative-index", "SEARCH_INDEX_TABLE": "table-index",
        "SEARCH_INDEX_FIGURE": "figure-index", "SEARCH_INDEX_CATALOG": "fund-catalog-index",
        "SEARCH_INDEX_FACTS": "evaluation-facts-index",
        "INGEST_API_ENDPOINT": outputs["apiEndpoint"],
        "FOUNDRY_PROJECT_ENDPOINT": outputs["foundryProjectEndpoint"],
        "FOUNDRY_CHAT_DEPLOYMENT": outputs["reasoningDeploymentName"],
        "FOUNDRY_VISION_DEPLOYMENT": outputs["chatDeploymentName"],
        "FOUNDRY_EVAL_DEPLOYMENT": outputs["chatDeploymentName"],
        "FOUNDRY_EMBEDDING_DEPLOYMENT": outputs["embeddingDeploymentName"],
        "APPINSIGHTS_CONNECTION_STRING": outputs["appInsightsConnectionString"],
        "AZURE_CLIENT_ID": outputs["uamiClientId"],
    }
    return {key: {"value": value} for key, value in {
        "name": outputs["containerAppName"], "location": location,
        "environmentId": outputs["containerEnvironmentId"], "acrLoginServer": outputs["acrLoginServer"],
        "uamiId": outputs["uamiId"], "image": image,
        "authMode": outputs.get("authenticationMode", "identity"),
        "searchName": outputs.get("searchName", ""),
        "foundryName": outputs.get("foundryName", ""),
        "acrName": outputs.get("acrName", ""),
        "resourceTags": outputs.get("resourceTags", {}),
        "envVars": [{"name": key, "value": value} for key, value in env.items()],
    }.items()}


def create_image_context(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("Dockerfile", "pyproject.toml", "uv.lock", "chainlit.md", ".dockerignore"):
        shutil.copy2(root / name, destination / name)
    for name in ("agent", "app", "search", "ingest", "config", "eval", "public"):
        shutil.copytree(
            root / name, destination / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env*", "local.settings.json"),
        )
    (destination / ".chainlit").mkdir()
    shutil.copy2(root / ".chainlit/config.toml", destination / ".chainlit/config.toml")
    (destination / "Docs").mkdir()
    for pdf in (root / "Docs").glob("*.pdf"):
        shutil.copy2(pdf, destination / "Docs" / pdf.name)
    if not list((destination / "Docs").glob("*.pdf")):
        raise RuntimeError("The repository's bundled PDFs are missing; Dockerfile expects Docs/*.pdf")


def package_function(root: Path, dependencies: Path, destination: Path) -> None:
    if not (dependencies / "pypdf/__init__.py").is_file():
        raise RuntimeError("Function dependencies were not installed completely")
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(".deployment", "[config]\nSCM_DO_BUILD_DURING_DEPLOYMENT=false\n")
        for name in ("function_app.py", "host.json", "requirements.txt"):
            archive.write(root / "functions/ingestion" / name, name)
        for package in ("ingest", "config"):
            for source in sorted((root / package).glob("*.py")):
                compile(source.read_text(encoding="utf-8"), str(source), "exec")
                archive.write(source, str(source.relative_to(root)))
        for source in sorted(dependencies.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                archive.write(source, ".python_packages/lib/site-packages/" + str(source.relative_to(dependencies)))


def function_constraints(root: Path) -> str:
    locked = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    return "\n".join(
        f"{p['name']}=={p['version']}" for p in locked["package"]
        if "version" in p and p["name"] != "mirae-ai-agent-mvp"
    ) + "\n"


def create_function_context(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "functions/ingestion/Dockerfile.package", destination / "Dockerfile")
    shutil.copy2(root / "scripts/build_function_package.py", destination / "build_function_package.py")
    for name in ("function_app.py", "host.json", "requirements.txt"):
        shutil.copy2(root / "functions/ingestion" / name, destination / name)
    for package in ("ingest", "config"):
        (destination / package).mkdir()
        for source in (root / package).glob("*.py"):
            shutil.copy2(source, destination / package / source.name)
    (destination / ".deployment").write_text(
        "[config]\nSCM_DO_BUILD_DURING_DEPLOYMENT=false\n", encoding="utf-8",
    )
    (destination / "constraints.txt").write_text(function_constraints(root), encoding="utf-8")


def extract_function_artifact(layer: Path, destination: Path, digest: str) -> None:
    if hashlib.sha256(layer.read_bytes()).hexdigest() != digest.removeprefix("sha256:"):
        raise RuntimeError("Function artifact layer digest does not match the registry manifest")
    with tarfile.open(layer, "r:*") as archive:
        member = next((member for member in archive.getmembers() if member.name.lstrip("./") == "function.zip"), None)
        if member is None or not member.isfile():
            raise RuntimeError("Cloud build layer does not contain a regular function.zip")
        source = archive.extractfile(member)
        if source is None:
            raise RuntimeError("Cannot read the cloud Function ZIP")
        with source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)
    with ZipFile(destination) as archive:
        if not {"function_app.py", "ingest/jobs.py", ".python_packages/lib/site-packages/pypdf/__init__.py"} <= set(archive.namelist()):
            raise RuntimeError("Cloud Function package is incomplete")


def wait_http(url: str, *, timeout: int = 600) -> requests.Response:
    deadline = time.monotonic() + timeout
    detail = ""
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return response
            if response.status_code not in {403, 404, 429, 500, 502, 503, 504}:
                response.raise_for_status()
            detail = f"HTTP {response.status_code}"
        except (requests.ConnectionError, requests.Timeout) as exc:
            detail = type(exc).__name__
        time.sleep(10)
    raise TimeoutError(f"{url} did not become ready: {detail}")


def synthetic_pdf() -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        }),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 16 Tf 40 700 Td (Azure component demo: Blob to Search) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def validate_sample(path: Path) -> None:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Sample exceeds the Function's 50 MB upload limit")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("Unlock the sample PDF before deployment")
        if not len(reader.pages):
            raise ValueError("Sample PDF has no pages")
    except PdfReadError as exc:
        raise ValueError(f"Invalid sample PDF: {path.name}") from exc


class Deployment:
    def __init__(self, args, root: Path, work: Path):
        self.args, self.root, self.work = args, root, work
        self.outputs: dict = {}
        self.cli: AzureCLI
        self.credential = None
        self.group_exists = False

    def preflight(self) -> None:
        if sys.version_info[:2] != (3, 12):
            raise RuntimeError("Run with uv run --python 3.12 --frozen python scripts/deploy_demo.py")
        for name in ("az", "uv"):
            if not shutil.which(name):
                raise RuntimeError(f"Install {name} before running the customer demo")
        if self.args.sample_pdf:
            validate_sample(self.args.sample_pdf)
        account_args = ["az", "account", "show", "--output", "json"]
        if self.args.subscription:
            account_args += ["--subscription", self.args.subscription]
        account = command(account_args, json_output=True)
        self.cli = AzureCLI(account["id"])
        from azure.identity import AzureCliCredential
        self.credential = AzureCliCredential(subscription=account["id"])
        cloud = command(["az", "cloud", "show", "--query", "name", "--output", "tsv"]).strip()
        if cloud != "AzureCloud":
            raise RuntimeError("This reference demo supports Azure public cloud only")
        self.principal_type = "User" if account["user"]["type"] == "user" else "ServicePrincipal"
        self.principal = self.args.principal_id
        if not self.principal and self.args.auth_mode == "identity":
            if self.principal_type != "User":
                raise RuntimeError("Service-principal login requires --principal-id <Entra object ID>")
            token = self.credential.get_token("https://graph.microsoft.com/.default").token
            me = requests.get(
                "https://graph.microsoft.com/v1.0/me?$select=id",
                headers={"Authorization": "Bearer " + token}, timeout=30,
            )
            me.raise_for_status()
            self.principal = me.json()["id"]
        self.principal = self.principal or ""
        models = self.cli.run("cognitiveservices", "model", "list", "--location", self.args.model_location or self.args.location)
        check_models(models, model_choices(self.args))
        groups = self.cli.run("group", "list")
        group = next((g for g in groups if g["name"].casefold() == self.args.resource_group.casefold()), None)
        if group:
            check_group_ownership(group, self.args.location)
            self.group_exists = True
            deployments = self.cli.run("deployment", "group", "list", "-g", self.args.resource_group)
            if any(d["name"] == "mirae-customer-services" and d["properties"]["provisioningState"] == "Succeeded" for d in deployments):
                self.outputs = self._outputs("mirae-customer-services")
                if self.outputs.get("authenticationMode", "identity") != self.args.auth_mode:
                    raise RuntimeError("Changing authentication mode requires a new dedicated RG")
        existing_models = []
        if self.outputs:
            existing_models = self.cli.run(
                "cognitiveservices", "account", "deployment", "list",
                "-g", self.args.resource_group, "-n", self.outputs["foundryName"],
            )
        usages = self.cli.run(
            "cognitiveservices", "usage", "list", "--location", self.args.model_location or self.args.location,
        )
        check_quota(models, usages, model_choices(self.args), existing_models)
        for filename in ("customer-demo.bicep", "customer-chat.bicep"):
            self.cli.run("bicep", "build", "--file", str(self.root / "infra" / filename),
                         "--outfile", str(self.work / (filename + ".json")), json_output=False)
        print(f"Subscription: {account['name']} ({account['id']})", flush=True)
        print(f"Dedicated RG: {self.args.resource_group}; region: {self.args.location}; "
              f"models: {self.args.model_location or self.args.location}", flush=True)
        print(f"Authentication: {self.args.auth_mode}. API keys are used only in the new customer demo, not the existing deployment.", flush=True)
        if self.args.resource_tag:
            print("Explicit resource tags:", resource_tags(self.args), flush=True)
        print("Preflight passed: model/SKU availability and current quota. ARM validation still checks policy/capacity.", flush=True)

    def _outputs(self, name: str) -> dict:
        result = self.cli.run("deployment", "group", "show", "-g", self.args.resource_group, "--name", name)
        return {key: value["value"] for key, value in result["properties"]["outputs"].items()}

    def provision(self) -> None:
        if self.outputs:
            # Do not restart a worker in the middle of customer data processing.
            functions = self.cli.run(
                "functionapp", "function", "list", "-g", self.args.resource_group,
                "-n", self.outputs["functionAppName"],
            )
            # A previous attempt may have provisioned services but never deployed Function code.
            if any(f["name"].rsplit("/", 1)[-1] == "jobs" for f in functions):
                jobs = wait_http(self.outputs["apiEndpoint"] + "/api/jobs").json()
                if any(job["status"] not in {"queued", "running", "retrying", "completed", "failed", "superseded"} for job in jobs):
                    raise RuntimeError("Unrecognized job state; inspect the existing deployment before updating")
                if any(job["status"] in {"queued", "running", "retrying"} for job in jobs):
                    raise RuntimeError("Existing PDF jobs are still active. Rerun deployment after /api/jobs completes.")
        for provider in PROVIDERS:
            self.cli.run("provider", "register", "--namespace", provider, "--wait", json_output=False)
        if not self.group_exists:
            self.cli.run("group", "create", "--name", self.args.resource_group,
                         "--location", self.args.location, "--tags", f"{OWNER_TAG}={OWNER_VALUE}",
                         *self.args.resource_tag)
        elif self.args.resource_tag:
            self.cli.run(
                "tag", "update", "--resource-id",
                f"/subscriptions/{self.cli.subscription}/resourceGroups/{self.args.resource_group}",
                "--operation", "Merge", "--tags", *self.args.resource_tag,
            )
        path = self.work / "services.parameters.json"
        write_parameters(path, deployment_values(self.args, self.principal, self.principal_type))
        common = ["-g", self.args.resource_group, "--template-file", str(self.root / "infra/customer-demo.bicep"),
                  "--parameters", str(path)]
        self.cli.run("deployment", "group", "validate", *common)
        self.cli.run("deployment", "group", "create", "--name", "mirae-customer-services", *common)
        self.outputs = self._outputs("mirae-customer-services")

    def deploy_function(self) -> None:
        package = self.work / "function.zip"
        if self.args.function_build == "cloud":
            self._cloud_function_package(package)
        else:
            deps = self.work / "function-dependencies"
            constraints = self.work / "constraints.txt"
            constraints.write_text(function_constraints(self.root), encoding="utf-8")
            command([
                "uv", "pip", "install", "--target", str(deps),
                "--python-platform", "x86_64-manylinux_2_28", "--python-version", "3.12",
                "--only-binary", ":all:", "--constraint", str(constraints),
                "--requirements", str(self.root / "functions/ingestion/requirements.txt"),
            ])
            package_function(self.root, deps, package)
        self._deploy_zip(package)
        self.cli.run("rest", "--method", "post", "--url",
                     f"https://management.azure.com{self.outputs['functionAppId']}/syncfunctiontriggers?api-version=2024-04-01",
                     json_output=False)
        self.cli.run("functionapp", "config", "appsettings", "set", "-g", self.args.resource_group,
                     "-n", self.outputs["functionAppName"], "--settings",
                     "AzureWebJobs.index.Disabled=false", "AzureWebJobs.process_jobs.Disabled=false",
                     json_output=False)
        wait_http(self.outputs["apiEndpoint"] + "/api/jobs")
        wait_http(self.outputs["apiEndpoint"] + "/api/documents")

    def _cloud_function_package(self, package: Path) -> None:
        context = self.work / "function-build-context"
        create_function_context(self.root, context)
        digest = hashlib.sha256()
        for path in sorted(p for p in context.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(context)).encode())
            digest.update(path.read_bytes())
        repository = "mirae-function-package"
        tag = "customer-" + digest.hexdigest()[:16]
        self.cli.run("acr", "build", "--registry", self.outputs["acrName"],
                     "--image", repository + ":" + tag, "--file", str(context / "Dockerfile"),
                     "--no-logs", str(context))
        server = self.outputs["acrLoginServer"]
        if self.args.auth_mode == "keys":
            login = self.cli.run("acr", "credential", "show", "--name", self.outputs["acrName"])
            auth = (login["username"], login["passwords"][0]["value"])
        else:
            login = self.cli.run("acr", "login", "--name", self.outputs["acrName"], "--expose-token")
            auth = ("00000000-0000-0000-0000-000000000000", login["accessToken"])
        token_response = requests.get(
            f"https://{server}/oauth2/token",
            params={"service": server, "scope": f"repository:{repository}:pull"},
            auth=auth, timeout=60,
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        token = token_data.get("access_token") or token_data["token"]
        headers = {"Authorization": "Bearer " + token}
        manifest = requests.get(
            f"https://{server}/v2/{repository}/manifests/{tag}",
            headers={**headers, "Accept": "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json"},
            timeout=60,
        )
        manifest.raise_for_status()
        layers = manifest.json().get("layers", [])
        if len(layers) != 1:
            raise RuntimeError("Function artifact image must contain exactly one scratch-image layer")
        layer = self.work / "function-layer.tar"
        with requests.get(
            f"https://{server}/v2/{repository}/blobs/{layers[0]['digest']}",
            headers=headers, stream=True, timeout=180,
        ) as response:
            response.raise_for_status()
            with layer.open("wb") as stream:
                for block in response.iter_content(1024 * 1024):
                    stream.write(block)
        extract_function_artifact(layer, package, layers[0]["digest"])
        print("Function Linux dependencies built in ACR; artifact ZIP verified.", flush=True)

    def _deploy_zip(self, package: Path) -> None:
        scm = self.outputs["apiEndpoint"].replace(".azurewebsites.net", ".scm.azurewebsites.net")
        session = requests.Session()
        session.headers["Authorization"] = "Bearer " + self.credential.get_token("https://management.azure.com/.default").token
        previous_response = session.get(scm + "/api/deployments", timeout=60)
        previous_response.raise_for_status()
        previous_ids = {entry["id"] for entry in previous_response.json()}
        with package.open("rb") as stream:
            try:
                response = session.post(scm + "/api/zipdeploy?isAsync=true", data=stream, timeout=180)
                response.raise_for_status()
            except requests.ReadTimeout:
                print("ZIP response timed out; checking whether the deployment was admitted (not resending).", flush=True)
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            response = session.get(scm + "/api/deployments/latest", timeout=60)
            if response.status_code == 404:
                time.sleep(10)
                continue
            response.raise_for_status()
            state = response.json()
            if state["id"] not in previous_ids and not state["id"].startswith("temp-"):
                if state["status"] == 4:
                    print("Function prebuilt ZIP deployed.", flush=True)
                    return
                if state["status"] == 3:
                    raise RuntimeError(f"Function deployment failed: {state.get('status_text')}; inspect SCM deployment {state['id']}")
            time.sleep(10)
        raise TimeoutError("Function deployment did not finish; resources are preserved for diagnosis/rerun")

    def initialize_indexes(self) -> None:
        from azure.core.exceptions import HttpResponseError, ServiceRequestError
        from config.settings import get_settings
        for key, value in {
            "SEARCH_ENDPOINT": self.outputs["searchEndpoint"],
            "STORAGE_BLOB_ENDPOINT": self.outputs["storageEndpoint"],
            "INGEST_API_ENDPOINT": self.outputs["apiEndpoint"],
            "DOC_INTELLIGENCE_ENDPOINT": self.outputs["docIntelligenceEndpoint"],
            "FOUNDRY_PROJECT_ENDPOINT": self.outputs["foundryProjectEndpoint"],
            "UPLOAD_CONTAINER": "pdfs", "ASSETS_CONTAINER": "document-assets",
        }.items():
            os.environ[key] = value
        for key, value in {
            "SEARCH_INDEX_NARRATIVE": "narrative-index", "SEARCH_INDEX_TABLE": "table-index",
            "SEARCH_INDEX_FIGURE": "figure-index", "SEARCH_INDEX_CATALOG": "fund-catalog-index",
            "SEARCH_INDEX_FACTS": "evaluation-facts-index",
        }.items():
            os.environ[key] = value
        get_settings.cache_clear()
        from azure.search.documents.indexes import SearchIndexClient
        from ingest.indexer import build_index
        from ingest.structured_indexer import build_catalog_index, build_facts_index
        client = SearchIndexClient(self.outputs["searchEndpoint"], self.search_credential())
        indexes = [build_index(name) for name in ("narrative-index", "table-index", "figure-index")]
        indexes += [build_catalog_index("fund-catalog-index"), build_facts_index("evaluation-facts-index")]
        deadline = time.monotonic() + 600
        while True:
            try:
                for index in indexes:
                    client.create_or_update_index(index)
                break
            except HttpResponseError as exc:
                if exc.status_code not in {403, 429, 503} or time.monotonic() >= deadline:
                    raise
                print(f"Waiting for Search readiness/RBAC (HTTP {exc.status_code})...", flush=True)
                time.sleep(15)
            except ServiceRequestError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(15)
        # Uses the system key managed by the AzureFunction endpoint, never prints/stores it.
        self.cli.run(
            "eventgrid", "event-subscription", "create", "--name", "mirae-pdf-ingestion",
            "--source-resource-id", self.outputs["storageId"], "--endpoint-type", "azurefunction",
            "--endpoint", self.outputs["functionAppId"] + "/functions/index",
            "--included-event-types", "Microsoft.Storage.BlobCreated",
            "--subject-begins-with", "/blobServices/default/containers/pdfs/",
        )

    def deploy_chat(self) -> None:
        deadline = time.monotonic() + 300
        while self.args.auth_mode == "identity":
            roles = self.cli.run(
                "role", "assignment", "list", "--assignee-object-id", self.outputs["uamiPrincipalId"],
                "--scope", f"/subscriptions/{self.cli.subscription}/resourceGroups/{self.args.resource_group}"
                f"/providers/Microsoft.ContainerRegistry/registries/{self.outputs['acrName']}",
            )
            if any(r["roleDefinitionName"] == "AcrPull" for r in roles):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("AcrPull role has not propagated")
            time.sleep(15)
        context = self.work / "image-context"
        create_image_context(self.root, context)
        digest = hashlib.sha256()
        for path in sorted(p for p in context.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(context)).encode())
            digest.update(path.read_bytes())
        tag = "customer-" + digest.hexdigest()[:16]
        self.cli.run("acr", "build", "--registry", self.outputs["acrName"],
                     "--image", "mirae-chat:" + tag, "--file", str(context / "Dockerfile"),
                     "--no-logs", str(context))
        image = self.outputs["acrLoginServer"] + "/mirae-chat:" + tag
        parameters = self.work / "chat.parameters.json"
        write_parameters(parameters, chat_parameters(self.outputs, image, self.args.location))
        self.cli.run(
            "deployment", "group", "create", "-g", self.args.resource_group,
            "--name", "mirae-customer-chat", "--template-file", str(self.root / "infra/customer-chat.bicep"),
            "--parameters", str(parameters),
        )
        self.outputs["chatbotUrl"] = self._outputs("mirae-customer-chat")["chatbotUrl"]
        wait_http(self.outputs["chatbotUrl"] + "/health")

    def verify(self) -> None:
        from azure.storage.blob import BlobServiceClient
        from azure.search.documents import SearchClient
        from ingest.blob import document_metadata
        name = self.args.sample_pdf.name if self.args.sample_pdf else "demo-connection-check.pdf"
        content = self.args.sample_pdf.read_bytes() if self.args.sample_pdf else synthetic_pdf()
        if len(content) > 50 * 1024 * 1024:
            raise ValueError("Sample exceeds the Function's 50 MB upload limit")
        blob = self.storage_client().get_blob_client("pdfs", name)
        if blob.exists() and blob.download_blob().readall() != content:
            raise RuntimeError(f"Refusing to overwrite a different customer PDF named {name}; select another sample name")
        response = requests.post(
            self.outputs["uploadUrl"], files={"file": (name, content, "application/pdf")}, timeout=120,
        )
        response.raise_for_status()
        if response.status_code != 202:
            raise RuntimeError("Upload endpoint did not acknowledge asynchronous ingestion")
        etag = blob.get_blob_properties().etag
        metadata = document_metadata(name, {})
        job_id = metadata.doc_id + "-" + hashlib.sha256((name + "\0" + etag).encode()).hexdigest()[:32]
        deadline = time.monotonic() + 3600
        last = None
        while time.monotonic() < deadline:
            jobs = wait_http(self.outputs["apiEndpoint"] + "/api/jobs", timeout=120).json()
            job = next((row for row in jobs if row["job_id"] == job_id), None)
            if job:
                state = (job["status"], job["stage"], job["pages_completed"], job["chunks_completed"])
                if state != last:
                    print("PDF progress:", state, flush=True)
                    last = state
                if job["status"] in {"failed", "superseded"}:
                    raise RuntimeError(f"PDF ingestion {job['status']}: {job['error']}")
                if job["status"] == "completed":
                    break
            time.sleep(10)
        else:
            raise TimeoutError("PDF still processing; inspect /api/jobs. It will continue autonomously.")
        credential = self.search_credential()
        deadline = time.monotonic() + 120
        while True:
            hits = []
            for index_name in ("narrative-index", "table-index", "figure-index"):
                client = SearchClient(self.outputs["searchEndpoint"], index_name, credential)
                hits.extend(client.search(search_text="*", filter=f"doc_id eq '{metadata.doc_id}'", top=1))
            if hits:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Completed sample has no body/table/figure evidence in Search")
            time.sleep(5)
        if not self.args.sample_pdf and not any("Azure component demo" in hit["content"] for hit in hits):
            raise RuntimeError("Indexed synthetic sample does not match the uploaded PDF")
        settings = wait_http(self.outputs["chatbotUrl"] + "/project/settings").json()
        if settings["features"]["spontaneous_file_upload"]["enabled"]:
            raise RuntimeError("Chat attachments are unexpectedly enabled")
        if not settings["ui"]["name"]:
            raise RuntimeError("Chatbot settings are unavailable")
        records = wait_http(self.outputs["apiEndpoint"] + "/api/documents").json()
        if not any(row["doc_id"] == metadata.doc_id for row in records):
            raise RuntimeError("Completed source is absent from the chatbot's document listing")
        summary = {key: self.outputs[key] for key in (
            "chatbotUrl", "uploadUrl", "apiEndpoint", "storageAccountName", "storageEndpoint",
            "uploadContainer", "assetsContainer", "searchName", "searchEndpoint", "functionAppName",
        )}
        summary.update(subscription=self.cli.subscription, resourceGroup=self.args.resource_group,
                       sample=name, authenticationMode=self.args.auth_mode, verified=True)
        destination = self.root / ".azure/customer" / self.args.resource_group / "deployment.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("\nPASS: upload -> Blob -> Event Grid -> Function -> DI/embedding -> Search -> source list.", flush=True)
        print("Chatbot: " + summary["chatbotUrl"], flush=True)
        print("Upload:  " + summary["uploadUrl"], flush=True)
        print("Jobs:    " + summary["apiEndpoint"] + "/api/jobs", flush=True)
        print("Source:  " + summary["storageAccountName"] + "/pdfs", flush=True)
        print("Saved:   " + str(destination), flush=True)
        print("The sample is kept for testing. This command never resets indexes or deletes customer data.", flush=True)
        print("Contributor demo uses API keys in Azure app settings/secrets; no keys are written to this report.", flush=True)

    def search_credential(self):
        if self.args.auth_mode == "identity":
            return self.credential
        from azure.core.credentials import AzureKeyCredential
        keys = self.cli.run("search", "admin-key", "show", "-g", self.args.resource_group,
                            "--service-name", self.outputs["searchName"])
        return AzureKeyCredential(keys["primaryKey"])

    def storage_client(self):
        from azure.storage.blob import BlobServiceClient
        from azure.core.credentials import AzureNamedKeyCredential
        credential = self.credential
        if self.args.auth_mode == "keys":
            keys = self.cli.run("storage", "account", "keys", "list",
                                "-g", self.args.resource_group, "-n", self.outputs["storageAccountName"])
            credential = AzureNamedKeyCredential(self.outputs["storageAccountName"], keys[0]["value"])
        return BlobServiceClient(self.outputs["storageEndpoint"], credential)

    def run(self) -> None:
        self.preflight()
        if self.args.check:
            print("Read-only check complete. No Azure resources or data were changed.", flush=True)
            return
        if not self.args.yes:
            raise RuntimeError("Deployment creates billable resources and public demo endpoints; rerun with --yes to accept.")
        for name in ("provision", "deploy_function", "initialize_indexes", "deploy_chat", "verify"):
            print(f"\n=== {name} ===", flush=True)
            getattr(self, name)()


def main() -> int:
    args = parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="mirae-customer-") as directory:
            Deployment(args, ROOT, Path(directory)).run()
        return 0
    except (AzureError, OSError, RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"\nDEPLOYMENT NOT COMPLETE: {exc}", file=sys.stderr)
        print("Resources are preserved. Resolve the reported prerequisite/error and rerun the same command.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
