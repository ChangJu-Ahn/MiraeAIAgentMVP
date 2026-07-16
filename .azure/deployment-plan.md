# Azure Deployment Plan: MiraeAIAgentMVP

Status: Validated 2026-07-16 (v17)

Recipe: Bicep infrastructure with Azure CLI container deployment

## Goal

Run the public Chainlit PoC on Azure Container Apps with managed identity access to AI Search and Microsoft Foundry.

## Infrastructure

| Resource | Bicep module | Purpose |
|---|---|---|
| Azure AI Search | `search.bicep` | Four retrieval indexes |
| Document Intelligence | `docintelligence.bicep` | PDF layout extraction |
| Microsoft Foundry | `foundry.bicep` | Chat, embedding, vision, and evaluation models |
| Application Insights and Log Analytics | `observability.bicep` | Agent trace and platform logs |
| User-assigned managed identity | `identity.bicep` | Keyless application identity |
| Azure Container Registry | `acr.bicep` | Container images |
| Container Apps environment | `containerenv.bicep` | Runtime environment |
| Container App | `containerapp.bicep` | Public Chainlit endpoint, one replica |
| Role assignments | `rbac.bicep`, `apprbac.bicep` | Search read, Foundry inference, ACR pull |

Blob Storage is not part of the current application. Source-page rendering uses PDFs copied into the container image.

## Runtime

- Image command: `chainlit run app/chat.py --host 0.0.0.0 --port 8000`
- Authentication: `DefaultAzureCredential` selects the user-assigned identity through `AZURE_CLIENT_ID`.
- Required endpoints and deployment names are injected as Container App environment variables.
- `APPINSIGHTS_CONNECTION_STRING` enables Agent Framework trace export.
- Ingestion remains a local operator command; the Container App only queries existing indexes.

## Deployment

1. Validate and deploy `infra/main.bicep`.
2. Build and push the image to ACR.
3. Set `deployApp=true` and the new image reference.
4. Verify the public endpoint, a grounded answer, citations, and requested visuals.

```bash
bash scripts/verify_availability.sh
bash scripts/deploy.sh
uv run python scripts/smoke_test.py
```

## Security

- Azure service access is keyless and limited by RBAC.
- The public Chainlit endpoint has no end-user authentication for this PoC.
- The Application Insights connection string is the only runtime connection string.
- The app is fixed at one replica because the current Chainlit conversation session is process-local.

## Current Deployment

- Resource group: `rg-mirae-ai-agent-poc`
- Region: `koreacentral`
- Container App: `ca-mirae-v4xy5m5d3ltw6`
- Public URL: https://ca-mirae-v4xy5m5d3ltw6.purplesky-16661974.koreacentral.azurecontainerapps.io
- Image: `acrmiraev4xy5m5d3ltw6.azurecr.io/mirae-chat:v16`
- Revision: `ca-mirae-v4xy5m5d3ltw6--0000017`

The previously deployed Storage account is no longer referenced by code or Bicep. Removing that existing Azure resource is an explicit operational cleanup, not an incremental Bicep deployment side effect.

## Validation Proof

Revalidated at 2026-07-16 03:29 UTC for the MVP notice dialog-offset fix and image `mirae-chat:v17`.

- Git and application gates: branch `fix/mvp-dialog-offset-v17` at commit `3291d10ab5ac9e39e174682b43628cd2c56984c4` passed 428 tests with 9 environment-dependent skips and 4 existing dependency warnings. `uv lock --check`, JavaScript syntax validation, `git diff --check`, and the focused CSS regression contract also passed.
- Rendered behavior: a fresh local origin served the v17 CSS. At 1280 by 900 pixels, the notice, overlay, and Readme dialog boundaries were all 36 pixels; the close button began at 52 pixels. At 390 by 844 pixels, the three boundaries were all 52 pixels; the close button began at 68 pixels. Both layouts had zero document-level horizontal overflow, and clicking Close removed the dialog while retaining exactly one notice and the root offset.
- Target and baseline: the only enabled/default subscription is `ME-MngEnvMCAP094463-changjuahn-1` (`347e0df7-94e9-4feb-b42d-57d7e49566f2`). Existing resource group `rg-mirae-ai-agent-poc`, Container Apps environment `cae-mirae-v4xy5m5d3ltw6`, and Container App `ca-mirae-v4xy5m5d3ltw6` are in `koreacentral` and `Succeeded`. Healthy revision `0000017` runs `mirae-chat:v16` with one replica and 100% latest-revision traffic.
- Bicep and ARM preflight: MCP Bicep 0.45.15 compiled `infra/main.bicep` and `infra/main.bicepparam` with zero diagnostics. Resource-group validation returned `Succeeded` with correlation ID `c536ce36-886b-4b28-87ba-65c56b15da5f`. What-if returned `Succeeded` with 11 Modify, 6 NoChange, 5 expected Unsupported role assignments, 2 Ignore, and zero Delete changes.
- Security and image gate: static Bicep retains Search Index Data Reader, Cognitive Services OpenAI User, Cognitive Services User, and AcrPull at resource scope for UAMI principal `e2a20198-9516-43e0-b54a-fc1a5d088cb6`. The live AcrPull assignment is propagated on ACR `acrmiraev4xy5m5d3ltw6`, and tag `mirae-chat:v17` does not exist before the build. `.dockerignore` excludes `.worktrees`, `.env`, `.azure`, `reports`, and `.superpowers` from the remote build context.

Revalidated at 2026-07-16 01:37 UTC for the MVP visibility notice and image `mirae-chat:v16`.

- Git and application gates: `main` commit `0890cc9c6ec6140f4788c6cbb9c5a079ebd50be8` is pushed to `origin/main`; the checkout passed all 436 tests, `uv lock --check`, JavaScript syntax validation, `git diff --check`, zero VS Code diagnostics, the exact 429-line `README.md` suffix contract, and a RED-GREEN build-context regression test. `.dockerignore` excludes `.worktrees`, `.env`, and `reports`, so the isolated checkout, its environment symlink, and the three raw evaluation reports are not uploaded to ACR.
- Target and baseline: the only enabled/default subscription is `ME-MngEnvMCAP094463-changjuahn-1` (`347e0df7-94e9-4feb-b42d-57d7e49566f2`). Existing resource group `rg-mirae-ai-agent-poc`, Container Apps environment `cae-mirae-v4xy5m5d3ltw6`, and Container App `ca-mirae-v4xy5m5d3ltw6` are in `koreacentral` and `Succeeded`. Healthy revision `0000016` runs `mirae-chat:v15` with one replica and 100% latest-revision traffic.
- Bicep and ARM preflight: MCP Bicep 0.45.15 compiled `infra/main.bicep` and `infra/main.bicepparam` with zero diagnostics. Resource-group validation returned `Succeeded` with correlation ID `13743b35-b0a4-4a4f-8dae-99b6ef71b9ed`. What-if returned `Succeeded` with 17 Deploy, 5 expected Unsupported role assignments, 2 Ignore, and zero Delete changes.
- Security and dependencies: active subscription and management-group policy assignments were reviewed. UAMI principal `e2a20198-9516-43e0-b54a-fc1a5d088cb6` retains Search Index Data Reader, Cognitive Services OpenAI User, Cognitive Services User, and AcrPull on the required resource scopes. Pre-deployment keyless smoke tests passed for Azure AI Search, Document Intelligence, and Microsoft Foundry.
- Image gate: ACR `acrmiraev4xy5m5d3ltw6` and repository `mirae-chat` exist, while tag `mirae-chat:v16` does not. The existing AcrPull assignment is already propagated; no phase-one resource provisioning or RBAC change is required for this image-only rollout.

Revalidated at 2026-07-15 16:54 UTC for the Readme and source-document restoration on image `mirae-chat:v15`.

- Git and tests: commit `4f25662641f3d30a708941f96c7352174703dcea` is the verified tip of both local and remote `main`; `uv run pytest -q` passed 435 tests after the Docker compatibility fix; `uv lock --check`, staged and unstaged `git diff --check`, and VS Code diagnostics for the changed implementation, tests, and Dockerfile passed. The three raw evaluation reports remain untracked and excluded from the image.
- Target and baseline: the only enabled/default subscription is `ME-MngEnvMCAP094463-changjuahn-1` (`347e0df7-94e9-4feb-b42d-57d7e49566f2`). Existing resource group `rg-mirae-ai-agent-poc`, Container Apps environment `cae-mirae-v4xy5m5d3ltw6`, and Container App `ca-mirae-v4xy5m5d3ltw6` are in `koreacentral` and `Succeeded`. Healthy revision `0000015` runs `mirae-chat:v14` with one replica and 100% traffic.
- Bicep compilation and static contract: MCP Bicep 0.45.15 compiled `infra/main.bicep` and `infra/main.bicepparam` with zero diagnostics. Container Apps ingress and Chainlit both use port 8000, ACR admin access is disabled, and the UAMI is used for registry and Azure service access. Git tracks the five PDFs under canonical `Docs/`; `COPY */*.pdf Docs/` matches exactly those five PDFs from either macOS or Linux checkout casing and normalizes the runtime path used by corpus and source-document routes.
- ARM preflight: resource-group validation returned `Succeeded` with correlation ID `ce7f2344-ef8b-40f0-805c-c1237ae65818`. What-if returned `Succeeded` with 11 Modify, 6 NoChange, 2 Ignore, 5 expected Unsupported role assignments, zero Create, and zero Delete changes.
- Policy and RBAC: active subscription and management-group policy assignments were reviewed; ARM validation succeeded under the current policy set. UAMI principal `e2a20198-9516-43e0-b54a-fc1a5d088cb6` has Search Index Data Reader, Cognitive Services OpenAI User, Cognitive Services User, and AcrPull at the required resource scopes, matching `infra/modules/apprbac.bicep`.
- Image gate: initial ACR run `dej` rejected the directory bracket glob before an image or tag was produced. A focused RED-GREEN test and the full 435-test suite verified the file-glob correction in commit `4f25662`; neither `mirae-chat:v15` nor `mirae-chat:4f25662` existed before the retry. The local Docker daemon is unavailable, so ACR remote build is the Linux image build and validation path.

Revalidated on 2026-07-16 for the evaluation experience and image `mirae-chat:v14`.

- Target confirmed: subscription `ME-MngEnvMCAP094463-changjuahn-1` (`347e0df7-94e9-4feb-b42d-57d7e49566f2`), resource group `rg-mirae-ai-agent-poc`, region `koreacentral`, and Container App `ca-mirae-v4xy5m5d3ltw6` (`Succeeded`). The current healthy baseline is revision `0000014` on `mirae-chat:v13` with 100% latest-revision traffic.
- Git and tests: `uv run pytest -q` passed 427 tests; `uv lock --check`, `git diff --check`, and VS Code diagnostics for all changed Python files passed.
- Evaluation publication: regenerating `public/evaluation-data.json` from the approved 16-row batch artifact produced a byte-for-byte identical snapshot. Publication tests enforce the public field allowlist, and `reports/` remains excluded from the image.
- Bicep MCP compilation: `infra/main.bicep` and `infra/main.bicepparam` compiled successfully with zero diagnostics using Bicep 0.45.15.
- ARM preflight for `mirae-chat:v14`: group validation returned `Succeeded`; what-if reported 11 Modify, 6 NoChange, 2 Ignore, 5 expected Unsupported role assignments, and zero Delete changes.
- Container contract: Dockerfile and Chainlit listen on port 8000, Container Apps ingress targets port 8000, and the image includes only the allowlisted public evaluation snapshot rather than raw reports. The local Docker engine is unavailable, so ACR remote build is the image build and validation path.
- Live dependencies and RBAC: Search, Document Intelligence, and Foundry smoke tests passed with keyless authentication. UAMI principal `e2a20198-9516-43e0-b54a-fc1a5d088cb6` retains Search Index Data Reader, Cognitive Services OpenAI User, Cognitive Services User, and AcrPull on the required scopes.
- Azure Policy assignments at management-group and subscription scope were reviewed. The active policy set is unchanged from v13, and ARM validation succeeded for v14.
- Image gate: `mirae-chat:v14` did not exist before deployment.

Revalidated on 2026-07-15 for `main` merge `12a00ea` and image `mirae-chat:v13`.

- Target confirmed: default subscription `ME-MngEnvMCAP094463-changjuahn-1` (`347e0df7-94e9-4feb-b42d-57d7e49566f2`), existing resource group `rg-mirae-ai-agent-poc`, region `koreacentral`, and existing Container Apps environment `cae-mirae-v4xy5m5d3ltw6` (`Succeeded`). Subscription and location prompts returned user unavailable, so the validated existing v12 target was retained.
- Git and tests: merge commit `12a00ea` is pushed to `origin/main`; `uv run pytest -q` passed 405 tests; `uv lock --check` and `git diff --check` passed.
- Bicep MCP compilation: `infra/main.bicep` and `infra/main.bicepparam` compiled successfully with zero diagnostics using Bicep 0.45.15.
- ARM preflight for `mirae-chat:v13`: group validation `Succeeded`; what-if reported 17 Deploy, 2 Ignore, 5 expected dynamic role assignments as Unsupported, and zero Delete changes. The ignored resources are the existing Storage account and Event Grid system topic and will not be modified.
- Container contract: Dockerfile and Chainlit listen on port 8000, Container Apps ingress targets port 8000, ACR admin access is disabled, and five non-empty source PDFs are present. The local Docker daemon is unavailable, so ACR remote build is the image build and validation path.
- Live RBAC: UAMI principal `e2a20198-9516-43e0-b54a-fc1a5d088cb6` has Search Index Data Reader, Cognitive Services OpenAI User, Cognitive Services User, and AcrPull on the required scopes.
- Azure Policy assignments at management-group and subscription scope were reviewed; the same policy set permits the existing compliant v12 deployment and ARM validation for v13 succeeded.
- Image gate: `mirae-chat:v13` did not exist before deployment. The current Container App was `Succeeded`, used `mirae-chat:v12`, and routed 100% of traffic to the latest revision.

Revalidated on 2026-07-15 for the v12 diagnostics and reasoning UI restoration.

- Target confirmed: default subscription `ME-MngEnvMCAP094463-changjuahn-1` (`347e0df7-94e9-4feb-b42d-57d7e49566f2`), existing resource group `rg-mirae-ai-agent-poc`, region `koreacentral`, and existing Container Apps environment `cae-mirae-v4xy5m5d3ltw6` (`Succeeded`).
- Tests: 395 non-live tests passed; all 10 Foundry, AI Search, Document Intelligence, streaming, and evaluation integration tests passed against Azure.
- VS Code diagnostics: zero errors across `agent/`, `app/`, and `tests/`; `git diff --check` and `uv lock --check` passed.
- Bicep MCP compilation: `infra/main.bicep` and `infra/main.bicepparam` both produced templates with zero diagnostics.
- ARM preflight for `mirae-chat:v12`: group validation `Succeeded`; what-if reported 17 deploy, 5 expected unresolved role assignments, 2 ignored legacy resources, and zero deletes.
- Container contract: Dockerfile listens on port 8000 and Container Apps ingress targets port 8000; five non-empty source PDFs remain in the image context. A local Docker engine is unavailable, so the image build will be validated by ACR remote build.
- Live RBAC: UAMI principal `e2a20198-9516-43e0-b54a-fc1a5d088cb6` has Search Index Data Reader, Cognitive Services OpenAI User, Cognitive Services User, and AcrPull on the required scopes.
- Azure Policy assignments were reviewed; the existing deployment is already compliant with the active subscription and management-group policies.

Validated on 2026-07-15 against subscription `347e0df7-94e9-4feb-b42d-57d7e49566f2`, resource group `rg-mirae-ai-agent-poc`, and region `koreacentral`.

- `uv run pytest -q`: 390 passed.
- `uv lock --check` and `git diff --check`: passed.
- Pylance workspace diagnostics: zero errors.
- `az bicep build --file infra/main.bicep --stdout`: passed with Bicep 0.41.2.
- `az deployment group validate ... deployApp=true containerImage=<current-image>`: `Succeeded`.
- `az deployment group what-if ...`: `Succeeded`; 17 deploy, 2 ignore, 5 role-assignment resources unresolved until deployment, and zero deletes.
- Live RBAC: UAMI has `Search Index Data Reader`, `Cognitive Services OpenAI User`, `Cognitive Services User`, and `AcrPull` on the required resources.
- Azure Policy assignments at the target resource-group scope: none.
- `uv run python scripts/smoke_test.py`: AI Search, Document Intelligence, and Foundry passed with keyless authentication.
- Container image context: five non-empty source PDFs are copied by the Dockerfile and are not excluded by `.dockerignore`.
- Azure AI Search inventory: `narrative-index`, `table-index`, `fund-catalog-index`, and `evaluation-facts-index`; all four are referenced by production code, so no index is eligible for deletion.

## Deployment Verification

### v16 MVP Visibility Notice and Complete Readme

- Source commits `d9fb9e4` and `d4d3b8e` were merged into `main` as `58a8502`. Build-context hardening commit `0890cc9` and validated deployment-source commit `89e1f83` are pushed to `origin/main`. The verified checkout passed 436 tests, `uv lock --check`, JavaScript syntax validation, `git diff --check`, zero VS Code diagnostics, and the exact 429-line `README.md` suffix contract.
- ACR remote build run `dem` pushed `mirae-chat:v16` and `mirae-chat:89e1f83` with digest `sha256:0f6bac0163d158af492a382e7df44d445c1a28d1d7b8584173d21e8739d4d9b9`.
- ARM deployment `mirae-v16-deploy-20260716` succeeded with correlation ID `4d6c8aed-366f-4f2a-8a33-32588bfb41d1`; all 19 deployment operations succeeded.
- Container App revision `ca-mirae-v4xy5m5d3ltw6--0000017` is active, `Healthy`, and `Provisioned`, runs one replica of `mirae-chat:v16`, and receives 100% of latest-revision traffic. The Container App provisioning state is `Succeeded` and both latest revision pointers resolve to `0000017`.
- Public `/`, `/health`, `/source-docs`, Evaluation assets, `/public/mvp-notice.js`, and `/public/custom.css` requests returned HTTP 200. All five source-document URLs returned HTTP 206 with a valid `%PDF-` signature, while an unknown source ID returned 404.
- Production browser verification confirmed exactly one persistent MVP notice on initial load and after starting a new chat. Desktop reserved a 36-pixel banner offset with zero horizontal overflow. At 390 by 844 pixels, the banner reserved 52 pixels, both custom header icons remained 24 by 24 pixels, the composer remained visible, and horizontal overflow was zero.
- The deployed Readme begins with the MVP notice, includes the canonical `Mirae AI Agent MVP` content and final repository-README sentence, and renders 18,512 characters. The chat-start welcome message also begins with the non-Production MVP notice.
- A live grounded question completed in 18.1 seconds, answered that the 2025 국민연금기금 final grade is `양호`, and cited the `table-index` evaluation summary on p.180. The answer did not display `E_STREAM`.
- Post-deployment keyless smoke tests passed for Azure AI Search, Document Intelligence, and Microsoft Foundry. Live RBAC recheck confirmed Search Index Data Reader, Cognitive Services OpenAI User, Cognitive Services User, and AcrPull for UAMI principal `e2a20198-9516-43e0-b54a-fc1a5d088cb6` on the required runtime scopes.
- The active-revision workload-log sample contained 302 entries and zero traceback, exception, unhandled-error, critical, fatal, `E_STREAM`, or standalone error patterns. Since rollout at 01:49 UTC, Application Insights recorded eight successful dependencies, zero failed dependencies, zero exceptions, and zero error-level traces; no request telemetry was emitted in that window.
- System logs recorded six transient KEDA `ScaledObjectCheckFailed` events as the revision was created and ten transient startup-probe failures through 01:50:10 UTC. The captured system events contain no later warning for revision `0000017`; traffic was set to 100% at 01:50:21 UTC, and the final live-state check remained healthy with one replica.

### v15 Readme and Source Documents

- Git commit `4f25662641f3d30a708941f96c7352174703dcea` is pushed to `origin/main`. The initial ACR run `dej` rejected `COPY [Dd]ocs/ Docs/` before producing a tag; regression-tested commit `4f25662` replaced it with `COPY */*.pdf Docs/`.
- ACR remote build run `dek` passed the PDF copy stage and pushed `mirae-chat:v15` and `mirae-chat:4f25662` with the same digest, `sha256:00dca7b48d624398b7c19ed1d22a8ad90a2949940b045818c6d33172e9118ef8`.
- ARM deployment `mirae-v15-deploy-20260716` succeeded with correlation ID `3276f730-71d5-4aaa-a3e9-38e253f8e176`; all 19 deployment operations succeeded.
- Container App revision `ca-mirae-v4xy5m5d3ltw6--0000016` is active, `Healthy`, and `Provisioned`, runs one ready replica of `mirae-chat:v15` with zero restarts, and receives 100% of latest-revision traffic.
- Public `/`, `/health`, `/source-docs`, `/public/evaluation.html`, `/public/evaluation-data.json`, `/public/evaluation-icon.png`, and `/public/custom.css` requests returned HTTP 200 with the expected content types. The deployed evaluation snapshot has schema version 1 and 16 rows.
- All five stable source-document URLs returned inline PDF responses with HTTP 206, a valid `%PDF-` signature, and correct byte ranges. An unknown document ID returned 404.
- Browser verification confirmed the audited Readme, both header links, five evaluator cards, 16 evaluation questions, the privacy notice, and five source-document links. Desktop and 390-pixel mobile layouts had no horizontal overflow; mobile hid only the two custom-link labels and retained both icons. The Evaluation and source-document pages emitted no console errors.
- A live grounded question completed in 17.3 seconds and answered that the 2025 국민연금기금 final grade is `양호`, citing the evaluation summary on p.180. A repeat run returned the same grade and page. Neither run displayed `E_STREAM`.
- Post-deployment Search, Document Intelligence, and Foundry keyless smoke tests passed. UAMI principal `e2a20198-9516-43e0-b54a-fc1a5d088cb6` retains Search Index Data Reader, Cognitive Services OpenAI User, Cognitive Services User, and AcrPull at the required scopes.
- Active-revision workload logs contained zero traceback, exception, unhandled-error, critical, fatal, `E_STREAM`, or error-level patterns. The verified chat run recorded seven successful Application Insights dependencies, zero failed dependencies, and zero exceptions.
- System logs recorded nine transient startup-probe failures from 17:11:11 through 17:11:19 UTC while revision `0000016` initialized; none recurred afterward. Chainlit also requests avatar images derived from the reasoning-step labels (`/avatars/생각 중...`), which return non-blocking HTTP 400 responses without affecting the rendered reasoning step or answer.
- Browser verification retained two non-blocking upstream Chainlit warnings: Chromium skipped an invalid `*/*` MIME declaration, and the mobile dialog reported a missing description or `aria-describedby`. Neither warning caused layout overflow, navigation failure, or chat errors.

### v14 Evaluation Experience

- Git feature commit `8e20f7c` and merge commit `7d2680d` are pushed to `origin/feature/evaluation-experience-v14` and `origin/main`; the remote main ref was verified as `7d2680d7695c1944e70ac309fb51f282a6548b1e` before the image build.
- ACR remote build run `deh` pushed `mirae-chat:v14` and `mirae-chat:7d2680d` with digest `sha256:0571fbc8043ea949abd6fad9388f9f58576078776115855a7731d882b16f16cf`.
- ARM deployment `mirae-v14-deploy-20260716` succeeded with correlation ID `106b4c83-1062-4d3d-9c66-4f145a127cbc`; all deployment operations succeeded.
- Container App revision `ca-mirae-v4xy5m5d3ltw6--0000015` is active, `Healthy`, and `Provisioned`, runs one ready replica of `mirae-chat:v14` with zero restarts, and receives 100% of latest-revision traffic.
- Public `/`, `/health`, `/public/evaluation.html`, `/public/evaluation-data.json`, and `/public/evaluation-icon.png` requests succeeded. The deployed snapshot reported schema version 1 and exactly 16 rows. Post-deployment Search, Document Intelligence, and Foundry smoke tests passed.
- Browser verification confirmed the `Evaluation` header link, the 16-question dashboard, all five evaluator summaries, the privacy notice, and the `답변 평가 (답변 완료 후 백그라운드 품질 평가)` setting. Desktop and 390-pixel mobile layouts rendered without horizontal overflow.
- With answer evaluation enabled, an exact golden question rendered the grounded answer and citation before evaluation completed. The later result action opened a five-metric panel with Groundedness 5, Relevance 4, Similarity 5, Coherence 4, and Fluency 5; Similarity was included because the question matched the published review set exactly.
- Active-revision workload logs contained zero traceback, exception, unhandled-error, critical, fatal, or error-level patterns after the browser test. Application Insights reported zero exceptions, zero error-level traces, and zero failed requests in the preceding hour.
- System logs recorded nine transient startup-probe warnings while revision `0000015` initialized; the last was at 15:33:04 UTC, none recurred afterward, and the revision remained healthy throughout verification.

### v13 Reasoning and Debug Streaming Restoration

- Git merge `12a00ea` is pushed to `origin/main`. ACR remote build run `deg` pushed `mirae-chat:v13` and `mirae-chat:12a00ea` with digest `sha256:49d18cd4af63bc1f5cde0aedcc081f6e57d882a30cd22f9f761a17232d61307f`.
- ARM deployment `mirae-v13-deploy-20260715` succeeded with correlation ID `5d3da93e-fa82-4e42-a125-1aa731c8920c`.
- Container App revision `ca-mirae-v4xy5m5d3ltw6--0000014` is `Healthy` and `Provisioned`, runs one replica of `mirae-chat:v13`, and receives 100% of latest-revision traffic.
- Public `/` and `/health` requests returned HTTP 200; `/health` returned `{"status":"ok"}`. Post-deployment smoke tests passed for AI Search, Document Intelligence, and Foundry.
- Browser settings verification enabled debug and reflection, changed reasoning effort from `medium` to `high`, and confirmed the settings. The grounded Korean query completed round 1 in 13.6s, reflection requested supplementation, and round 2 completed in 38.5s without `E_STREAM`.
- Browser tool steps rendered names and timings. Round 1 showed `resolve_fund` at 0.9s and `get_fund_evaluations` at 0.4s. Round 2 showed two `search_narrative` calls, `search_tables`, and `get_fund_evaluations` at 0.6s each.
- The final answer was Korean, identified the grade as `우수`, and displayed seven cited sources. The debug sidebar displayed both rounds, tool and ranked Search details, final citations, and Raw OpenTelemetry spans. Closing it and selecting `디버그 보기` reopened the stored trace.
- Automatic `reasoning.summary` text in round 2 was English even though the system prompt explicitly requires the user's language. A production reproduction and a separate prompt-only probe with a closing language reminder produced the same result. The Responses API exposes `auto`, `concise`, and `detailed` summary modes but no language or locale control, so prompt-only enforcement cannot guarantee the summary language. No language detector, translation SDK, or additional translation model call was reintroduced.
- Active-revision workload logs contained zero traceback, exception, unhandled-error, `E_STREAM`, or error-level patterns. Application Insights reported zero exceptions, zero error-level traces, and zero failed requests after rollout.
- System logs recorded transient KEDA and startup-probe events while the revision was starting; the last startup probe failure was at 13:17:48 UTC, none recurred from 13:18 UTC onward, and the revision remained healthy throughout browser verification.

### v12 Diagnostics and Reasoning UI Restoration

- ACR remote build run `def` succeeded and pushed `mirae-chat:v12` with digest `sha256:0ba7766338246ade61b10dff18b375e23a02ae6fcb2c773cadee4ddc4090d436`.
- ARM deployment `mirae-v12-deploy-20260715` succeeded; every deployment operation succeeded.
- Container App revision `ca-mirae-v4xy5m5d3ltw6--0000012` is `Healthy` and `Provisioned`, runs one replica of `mirae-chat:v12`, and receives 100% of latest-revision traffic.
- Public `/` and `/health` requests returned HTTP 200; `/health` returned `{"status":"ok"}`.
- Post-deployment `scripts/smoke_test.py`: AI Search, Document Intelligence, and Foundry passed with keyless authentication.
- Browser settings test enabled debug and reflection, changed reasoning effort from `medium` to `high`, and confirmed the settings.
- Browser answer test rendered Korean reasoning summaries and total round timings. The grounded query completed round 1 in 57.0s, reflection reported `보완 필요`, and the second round completed in 90.5s with cited report evidence.
- Browser tool steps rendered names and timings: `resolve_fund` 0.5s, `search_narrative` 1.0-1.2s, and `get_fund_evaluations` 0.3s. Expanded steps displayed the query filters, retrieved source text, structured score `23.12/30`, and citations.
- The debug sidebar displayed both rounds, ranked Search results, final citations, and Raw OpenTelemetry spans. Closing it and using the latest `디버그 보기` action reopened the same trace successfully.
- Live RBAC recheck confirmed Search Index Data Reader, Cognitive Services OpenAI User, Cognitive Services User, and AcrPull for UAMI principal `e2a20198-9516-43e0-b54a-fc1a5d088cb6` on the required runtime scopes.
- Active-revision workload logs contained no error, traceback, exception, or unhandled-error patterns. Application Insights reported zero exceptions and zero error-level traces during the rollout and browser tests.
- System logs contained only transient KEDA/startup-probe warnings while revision `0000012` was starting; none recurred after 10:30:47 UTC, and the revision remained healthy throughout post-deployment tests.

### v11 Core Simplification

- Git: feature commit `96fd6b0`; merge commit `8402253` pushed to `origin/main`.
- ACR build: run `dee`; tags `mirae-chat:v11` and `mirae-chat:8402253`.
- Image digest: `sha256:7765e3b777b054030110492ca3aa5cc1b6cf3ba21dce20a6b2c630a059798dc6`.
- ARM deployment: `mirae-core-simplification-20260715` succeeded with correlation ID `1680136d-e3eb-4f41-975f-6b0f088c67cf`.
- Container App: revision `ca-mirae-v4xy5m5d3ltw6--0000011` is healthy and running with one replica; latest-revision traffic weight is 100%.
- Runtime configuration contains only the retained Search, Foundry, Application Insights, and managed-identity variables; removed Storage variables are absent.
- Public HTTPS endpoint returned 200 and served the Chainlit application.
- Browser test answered the 2025 국민연금기금 grade question with `table-index` citations to p.180 and p.237.
- Multi-turn visual test rendered the original p.180 PDF page from the container image.
- Revision logs contained zero traceback, unhandled-exception, critical, fatal, or error-level patterns; Application Insights transmission succeeded.
- Post-deployment `scripts/smoke_test.py`: AI Search, Document Intelligence, and Foundry passed.
- Post-deployment Search inventory remains the same four required indexes; no indexes were deleted.
