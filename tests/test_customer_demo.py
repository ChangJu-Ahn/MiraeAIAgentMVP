from pathlib import Path
import pytest

from scripts import deploy_demo as demo

ROOT = Path(__file__).resolve().parents[1]


def test_plan_requires_a_customer_resource_group_and_does_not_target_author_subscription():
    args = demo.parse_args(["--resource-group", "rg-customer-example", "--check"])
    assert args.resource_group == "rg-customer-example"
    assert args.subscription is None and args.location == "koreacentral"
    text = (ROOT / "scripts/deploy_demo.py").read_text()
    assert "347e0df7" not in text and "rg-mirae-ai-agent-poc" not in text
    assert args.check and not args.yes
    assert args.function_build == "cloud"
    for filename in ("deploy.sh", "verify_availability.sh"):
        assert "347e0df7" not in (ROOT / "scripts" / filename).read_text()


def test_policy_tags_are_explicit_and_propagate_without_automatic_exemption():
    args = demo.parse_args(["--resource-group", "rg-demo", "--check"])
    assert demo.resource_tags(args) == {}
    args = demo.parse_args([
        "--resource-group", "rg-demo", "--check", "--resource-tag", "SecurityControl=Ignore",
        "--resource-tag", "purpose=customer-test",
    ])
    assert demo.resource_tags(args) == {"SecurityControl": "Ignore", "purpose": "customer-test"}
    assert demo.deployment_values(args, "", "User")["resourceTags"]["value"]["SecurityControl"] == "Ignore"
    assert demo.chat_parameters({
        "containerAppName": "chat", "containerEnvironmentId": "env", "acrLoginServer": "acr",
        "uamiId": "", "uamiClientId": "", "searchEndpoint": "search",
        "foundryProjectEndpoint": "model", "apiEndpoint": "fn", "appInsightsConnectionString": "",
        "reasoningDeploymentName": "reasoning", "chatDeploymentName": "chat",
        "embeddingDeploymentName": "embedding", "resourceTags": demo.resource_tags(args),
    }, "image", "koreacentral")["resourceTags"]["value"]["SecurityControl"] == "Ignore"


def test_existing_unrelated_resource_group_is_refused():
    with pytest.raises(RuntimeError, match="dedicated"):
        demo.check_group_ownership({"tags": {}, "location": "koreacentral"}, "koreacentral")
    with pytest.raises(RuntimeError, match="dedicated"):
        demo.check_group_ownership({"tags": None, "location": "koreacentral"}, "koreacentral")
    demo.check_group_ownership(
        {"tags": {demo.OWNER_TAG: demo.OWNER_VALUE}, "location": "koreacentral"}, "koreacentral",
    )
    with pytest.raises(RuntimeError, match="location"):
        demo.check_group_ownership(
            {"tags": {demo.OWNER_TAG: demo.OWNER_VALUE}, "location": "eastus"}, "koreacentral",
        )


def test_model_preflight_checks_versions_and_deployment_types():
    choices = demo.model_choices(demo.parse_args(["--resource-group", "rg-demo", "--check"]))
    inventory = [{
        "model": {"name": model.name, "version": model.version},
        "skus": [{"name": model.sku}],
    } for model in choices]
    demo.check_models(inventory, choices)
    inventory[0]["skus"] = [{"name": "Standard"}]
    with pytest.raises(RuntimeError, match="GlobalStandard"):
        demo.check_models(inventory, choices)


def test_service_inventory_skus_nested_under_model_and_capacity_limits():
    choice = demo.ModelChoice("gpt-4o", "2024-11-20", "GlobalStandard", 10)
    model = {"name": choice.name, "version": choice.version, "skus": [
        {"name": choice.sku, "capacity": {"minimum": 5, "maximum": 20, "step": 5}},
    ]}
    demo.check_models([{"model": model, "skus": None}], [choice])
    with pytest.raises(RuntimeError, match="capacity"):
        demo.check_models([{"model": model}], [
            demo.ModelChoice(choice.name, choice.version, choice.sku, 3),
        ])


def test_function_constraints_pin_transitive_dependencies_to_lock():
    pins = demo.function_constraints(ROOT)
    assert "azure-core==1." in pins
    assert "pypdf==6.19.0" in pins
    assert "mirae-ai-agent-mvp" not in pins
    assert "git+" not in pins


def test_readiness_http_does_not_hide_authentication_or_configuration_failure(monkeypatch):
    import requests
    response = requests.Response()
    response.status_code = 401
    response.url = "https://demo.test/health"
    monkeypatch.setattr(demo.requests, "get", lambda *a, **kw: response)
    with pytest.raises(requests.HTTPError):
        demo.wait_http(response.url, timeout=1)


def test_sample_content_is_an_actual_one_page_pdf():
    from pypdf import PdfReader
    import io
    pdf = PdfReader(io.BytesIO(demo.synthetic_pdf()))
    assert len(pdf.pages) == 1
    assert "Azure component demo" in pdf.pages[0].extract_text()


def test_bad_or_encrypted_sample_is_rejected_before_deployment(tmp_path):
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a PDF")
    with pytest.raises(ValueError, match="Invalid sample"):
        demo.validate_sample(invalid)
    from pypdf import PdfWriter
    encrypted = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("password")
    writer.write(encrypted)
    with pytest.raises(ValueError, match="Unlock"):
        demo.validate_sample(encrypted)


def test_quota_counts_combined_deployments_and_only_the_delta_on_rerun():
    choices = [demo.ModelChoice("model", "1", "GlobalStandard", 10)] * 2
    choices += [demo.ModelChoice("embedding", "1", "Standard", 50)]
    inventory = [
        {"model": {"name": "model", "version": "1", "skus": [
            {"name": "GlobalStandard", "usageName": "chat-quota"},
        ]}},
        {"model": {"name": "embedding", "version": "1", "skus": [
            {"name": "Standard", "usageName": "embedding-quota"},
        ]}},
    ]
    usages = [
        {"name": {"value": "chat-quota"}, "limit": 20, "currentValue": 0},
        {"name": {"value": "embedding-quota"}, "limit": 50, "currentValue": 0},
    ]
    demo.check_quota(inventory, usages, choices)
    usages[0]["limit"] = 19
    with pytest.raises(RuntimeError, match="Insufficient"):
        demo.check_quota(inventory, usages, choices)
    existing = [{
        "name": name, "sku": {"name": model.sku, "capacity": model.capacity},
        "properties": {"model": {"name": model.name, "version": model.version}},
    } for name, model in zip(("chat", "reasoning", "embedding"), choices)]
    for row in usages:
        row["currentValue"] = row["limit"]
    demo.check_quota(inventory, usages, choices, existing)


def test_deployment_stops_after_a_stage_failure_without_delete_or_success(monkeypatch, tmp_path):
    runner = demo.Deployment(
        demo.parse_args(["--resource-group", "rg-demo", "--yes"]), ROOT, tmp_path,
    )
    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setattr(runner, "provision", lambda: None)
    def fail():
        raise RuntimeError("Function build failed")
    monkeypatch.setattr(runner, "deploy_function", fail)
    monkeypatch.setattr(runner, "initialize_indexes", lambda: pytest.fail("must stop"))
    monkeypatch.setattr(runner, "verify", lambda: pytest.fail("must not claim success"))
    with pytest.raises(RuntimeError, match="Function build failed"):
        runner.run()


def test_real_function_deployment_sequence_uses_prebuilt_linux_package_then_activates(monkeypatch, tmp_path):
    args = demo.parse_args(["--resource-group", "rg-demo", "--yes", "--function-build", "local"])
    runner = demo.Deployment(args, ROOT, tmp_path)
    runner.outputs = {
        "functionAppName": "demo-function", "functionAppId": "/resource/id",
        "apiEndpoint": "https://demo-function.azurewebsites.net",
    }
    steps = []
    class CLI:
        def run(self, *args, **kwargs):
            steps.append(("az", args))
    runner.cli = CLI()
    def install(argv, **kwargs):
        steps.append(("install", argv))
        assert "--python-platform" in argv and "x86_64-manylinux_2_28" in argv
        assert "--only-binary" in argv and "--constraint" in argv
        p = tmp_path / "function-dependencies/pypdf/__init__.py"
        p.parent.mkdir(parents=True)
        p.write_text("")
    monkeypatch.setattr(demo, "command", install)
    monkeypatch.setattr(runner, "_deploy_zip", lambda zipfile: steps.append(("zip", zipfile)))
    monkeypatch.setattr(demo, "wait_http", lambda url: steps.append(("http", url)))
    runner.deploy_function()
    assert [step[0] for step in steps] == ["install", "zip", "az", "az", "http", "http"]
    assert "syncfunctiontriggers" in steps[2][1][-1]
    assert "AzureWebJobs.process_jobs.Disabled=false" in steps[3][1]


def test_cloud_function_package_needs_no_local_linux_wheel_download(monkeypatch, tmp_path):
    runner = demo.Deployment(
        demo.parse_args(["--resource-group", "rg-demo", "--yes"]), ROOT, tmp_path,
    )
    runner.outputs = {"functionAppName": "function", "functionAppId": "/id",
                      "apiEndpoint": "https://function.azurewebsites.net"}
    events = []
    class CLI:
        def run(self, *args, **kwargs):
            events.append("az")
    runner.cli = CLI()
    def cloud(path):
        path.write_bytes(b"prebuilt")
        events.append("cloud")
    monkeypatch.setattr(runner, "_cloud_function_package", cloud)
    monkeypatch.setattr(runner, "_deploy_zip", lambda path: events.append("zip"))
    monkeypatch.setattr(demo, "command", lambda *a, **kw: pytest.fail("no local pip"))
    monkeypatch.setattr(demo, "wait_http", lambda *a, **kw: events.append("http"))
    runner.deploy_function()
    assert events == ["cloud", "zip", "az", "az", "http", "http"]


def test_cloud_package_context_cannot_include_environment_or_credentials(tmp_path):
    demo.create_function_context(ROOT, tmp_path / "function")
    files = {str(p.relative_to(tmp_path / "function")) for p in (tmp_path / "function").rglob("*") if p.is_file()}
    assert {"Dockerfile", "build_function_package.py", "function_app.py", "ingest/jobs.py",
            "config/azure_auth.py", "constraints.txt", "requirements.txt", ".deployment"} <= files
    assert not any(".env" in f or "local.settings.json" in f or ".azure" in f for f in files)


def test_cloud_artifact_is_digest_verified_and_never_extracts_unrelated_tar_entries(tmp_path):
    import io
    import hashlib
    import tarfile
    from zipfile import ZipFile
    zipped = io.BytesIO()
    with ZipFile(zipped, "w") as archive:
        for name in ("function_app.py", "ingest/jobs.py", ".python_packages/lib/site-packages/pypdf/__init__.py"):
            archive.writestr(name, "# test")
    layer = tmp_path / "layer.tar"
    with tarfile.open(layer, "w") as archive:
        for name, content in (("function.zip", zipped.getvalue()), ("../../unrelated", b"never extract")):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    digest = "sha256:" + hashlib.sha256(layer.read_bytes()).hexdigest()
    destination = tmp_path / "function.zip"
    demo.extract_function_artifact(layer, destination, digest)
    assert destination.read_bytes() == zipped.getvalue()
    assert not (tmp_path.parent / "unrelated").exists()
    with pytest.raises(RuntimeError, match="digest"):
        demo.extract_function_artifact(layer, tmp_path / "bad.zip", "sha256:0000")


def test_zip_failure_is_never_treated_as_success(monkeypatch, tmp_path):
    runner = demo.Deployment(
        demo.parse_args(["--resource-group", "rg-demo", "--yes"]), ROOT, tmp_path,
    )
    runner.outputs = {"apiEndpoint": "https://function.azurewebsites.net"}
    from types import SimpleNamespace
    runner.credential = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="not-a-secret"))
    class Response:
        status_code = 200
        def __init__(self, value):
            self.value = value
        def raise_for_status(self):
            pass
        def json(self):
            return self.value
    class Session:
        headers = {}
        def get(self, url, **kw):
            if url.endswith("/api/deployments"):
                return Response([{"id": "old"}])
            return Response({"id": "new", "status": 3, "status_text": "Linux dependency error"})
        def post(self, *a, **kw):
            return Response({})
    monkeypatch.setattr(demo.requests, "Session", Session)
    zipfile = tmp_path / "app.zip"
    zipfile.write_bytes(b"test")
    with pytest.raises(RuntimeError, match="Linux dependency error"):
        runner._deploy_zip(zipfile)


def test_chat_parameters_use_deployment_outputs_not_author_resources():
    outputs = {
        "containerAppName": "customer-chat", "containerEnvironmentId": "env-id",
        "acrLoginServer": "customer.azurecr.io", "uamiId": "identity-id",
        "uamiClientId": "client-id", "searchEndpoint": "https://customer.search.windows.net",
        "foundryProjectEndpoint": "https://customer.services.ai.azure.com/api/projects/demo",
        "apiEndpoint": "https://customer-function.azurewebsites.net",
        "appInsightsConnectionString": "telemetry",
        "reasoningDeploymentName": "reasoning", "chatDeploymentName": "chat",
        "embeddingDeploymentName": "embedding",
    }
    params = demo.chat_parameters(outputs, "customer.azurecr.io/chat:tag", "koreacentral")
    env = {r["name"]: r["value"] for r in params["envVars"]["value"]}
    assert env["INGEST_API_ENDPOINT"] == outputs["apiEndpoint"]
    assert env["FOUNDRY_CHAT_DEPLOYMENT"] == "reasoning"
    assert env["SEARCH_INDEX_FIGURE"] == "figure-index"
    assert params["image"]["value"] == "customer.azurecr.io/chat:tag"


def test_image_context_excludes_secrets_and_function_package_has_all_runtime_modules(tmp_path):
    context = tmp_path / "context"
    demo.create_image_context(ROOT, context)
    assert (context / "Dockerfile").is_file()
    assert (context / ".chainlit/config.toml").is_file()
    assert not (context / ".env").exists()
    assert not (context / ".azure").exists()
    assert not (context / "tests").exists()
    assert list((context / "Docs").glob("*.pdf"))
    assert not list(context.rglob("local.settings.json"))
    deps = tmp_path / "dependencies"
    for package in ("azure/functions", "azure/storage/blob", "pypdf"):
        path = deps / package / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    archive = tmp_path / "function.zip"
    demo.package_function(ROOT, deps, archive)
    from zipfile import ZipFile
    with ZipFile(archive) as zipfile:
        assert {
            "function_app.py", "host.json", "requirements.txt", ".deployment",
            "ingest/jobs.py", "ingest/run.py", "config/settings.py",
            ".python_packages/lib/site-packages/pypdf/__init__.py",
        } <= set(zipfile.namelist())
        assert zipfile.read(".deployment").decode().endswith("SCM_DO_BUILD_DURING_DEPLOYMENT=false\n")
        assert all(".env" not in name for name in zipfile.namelist())


def test_customer_template_wires_every_component_and_small_model_capacities():
    text = (ROOT / "infra/customer-demo.bicep").read_text()
    assert "module base 'main.bicep'" in text
    assert "module ingestion 'ingestion.bicep'" in text
    assert "privateStorage: false" in text
    assert "prebuiltDeployment: true" in text
    assert "pauseProcessing: true" in text
    assert "chatCapacity" in text and "reasoningCapacity" in text
    assert "Microsoft.Storage/storageAccounts" in text
    assert "allowSharedKeyAccess: authMode == 'keys'" in text
    assert "allowBlobPublicAccess: false" in text


def test_foundry_project_and_model_creation_are_serialized():
    text = (ROOT / "infra/modules/foundry.bicep").read_text()
    chat = text.split("resource chat ", 1)[1].split("resource embedding ", 1)[0]
    assert "dependsOn: [project]" in chat


def test_cli_failures_propagate_and_never_return_success_shaped_empty_output(monkeypatch):
    import subprocess
    monkeypatch.setattr(demo.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 1, "", "AuthorizationFailed",
    ))
    with pytest.raises(RuntimeError, match="AuthorizationFailed"):
        demo.AzureCLI("sub").run("group", "show", "--name", "rg")


def test_deploy_order_avoids_app_placeholder_and_initializes_before_upload(monkeypatch, tmp_path):
    steps = []
    cfg = demo.parse_args(["--resource-group", "rg-customer-example", "--yes"])
    runner = demo.Deployment(cfg, ROOT, tmp_path)
    for name in ("preflight", "provision", "deploy_function", "initialize_indexes", "deploy_chat", "verify"):
        monkeypatch.setattr(runner, name, lambda name=name: steps.append(name))
    runner.run()
    assert steps == [
        "preflight", "provision", "deploy_function", "initialize_indexes", "deploy_chat", "verify",
    ]


def test_check_mode_has_no_provision_or_upload(monkeypatch, tmp_path):
    runner = demo.Deployment(
        demo.parse_args(["--resource-group", "rg-customer-example", "--check"]), ROOT, tmp_path,
    )
    steps = []
    monkeypatch.setattr(runner, "preflight", lambda: steps.append("preflight"))
    monkeypatch.setattr(runner, "provision", lambda: pytest.fail("check must not provision"))
    runner.run()
    assert steps == ["preflight"]


def test_resume_after_service_creation_does_not_require_a_not_yet_deployed_jobs_api(monkeypatch, tmp_path):
    args = demo.parse_args(["--resource-group", "rg-demo", "--yes"])
    runner = demo.Deployment(args, ROOT, tmp_path)
    runner.outputs = {"functionAppName": "new-function", "apiEndpoint": "https://new-function.test"}
    runner.principal, runner.principal_type = "", "User"
    runner.group_exists = True
    calls = []
    class CLI:
        def run(self, *args, **kwargs):
            calls.append(args)
            if args[:3] == ("functionapp", "function", "list"):
                return []
            return {}
    runner.cli = CLI()
    monkeypatch.setattr(demo, "wait_http", lambda *a, **kw: pytest.fail("no Function code exists yet"))
    monkeypatch.setattr(runner, "_outputs", lambda name: {"functionAppName": "new-function"})
    runner.provision()
    assert any(call[:3] == ("deployment", "group", "create") for call in calls)


def test_active_pdf_jobs_block_redeploy_before_any_provider_or_resource_write(monkeypatch, tmp_path):
    runner = demo.Deployment(demo.parse_args(["--resource-group", "rg-demo", "--yes"]), ROOT, tmp_path)
    runner.outputs = {"functionAppName": "function", "apiEndpoint": "https://function.test"}
    class CLI:
        def run(self, *args, **kw):
            assert args[:3] == ("functionapp", "function", "list")
            return [{"name": "function/jobs"}]
    runner.cli = CLI()
    from types import SimpleNamespace
    monkeypatch.setattr(demo, "wait_http", lambda *a, **kw: SimpleNamespace(
        json=lambda: [{"status": "running"}],
    ))
    with pytest.raises(RuntimeError, match="still active"):
        runner.provision()
