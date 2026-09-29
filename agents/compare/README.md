# Compare agent: VHOP demo

The Compare plugin runs the approved v5.1 deterministic comparison rules over the copied VHOP Data Package. Backend registration is enabled by opts: {vhop_demo: true} in both backend config files. It needs no model key. The existing LiteLLM retail comparison loop remains available when that option is absent.

The source CSV pack was copied read-only from Team_6_cAi, branch origin/feature/warehouse-data-pack, commit adf2d05d06211b7462c92dda73844a86d4316387. The copied files are under data/vhop. Do not edit the source repo. The CSV snapshot has 3,000 units, snapshot SNAP-20260630-01, semantic config 3.1.0. A12-08 is absent from that CSV, so data/vhop/hero_a12_08.json is a separate regression fixture from the approved golden case.

## Run in the browser

From the repository root:

    uv sync --frozen
    uv run python data/seed_warehouse.py
    uv run python data/seed_users.py
    cd frontend
    npm ci
    npm run build
    cd ..
    uv run uvicorn vdagent_backend.app:app --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000, choose Alice and select the compare agent in the left panel. The other agents still need their own model settings if used; Compare works without them in demo mode.
## Demo questions

1. "So sánh căn ZURICH-20.022 với các căn tương đồng" — real CSV unit with 10 eligible peers. Shows benchmark, exclusions and evidence.
2. "So sánh A12-08 với A12-11" — regression fixture, direct comparison. Both names are from the fixture, not the CSV.
3. "Xếp hạng DOM của ZURICH-20.022" — full project ranking; the peer group is not reused as the ranking population.
4. "So sánh DOM 2PN theo tầng trong PRJ-VHOP" — cohort across available 2PN units.
5. "PRJ-VHOP so với thị trường" — correctly returns insufficient evidence because the Data Package has no comparable external market benchmark.
6. "So sánh A12-08 chỉ với các căn cùng phân khu" — narrows the peer rules; 4 peers is insufficient, so no numeric conclusion is shown.
7. "So sánh A12-08 về giá, DOM, lượt quan tâm, ưu đãi" — shows all five comparison metrics, the per-unit table, and notable differences.
8. "So sánh ZURICH-20" — asks the user to choose a full unit code from matching units.

The chat also accepts a full JSON Compare request, for example:

    {"subject":{"entityType":"unit","entityCode":"ZURICH-20.022"},"comparisonMode":"peer_group","metricsRequested":["net_asking_price_per_m2","dom"]}

The response displays the artifact ID and content hash. Numeric calculations use Decimal and run without a model. The engine returns JSON peer_definition and comparison artifacts through CompareService.run, including source refs, confidence, limitations and chart hints.

## Offline fallback

    uv run python -m vdagent_compare.demo --artifact-out var/compare-demo.json

This prints the same real CSV comparison and saves both JSON artifacts; no browser or model key is needed.

## Test

    uv run pytest -q agents/compare

The existing LiteLLM tests run with the new tests. The new tests cover the A12-08 golden numbers, a real CSV peer group, all internal modes, unavailable market benchmark, scope denial, hash stability and backend demo registration.

## Scope of this demo

The copied CSV data is synthetic. The demo chat does not load per-user project/zone grants from the app database; structured Compare requests support an explicit allowedProjectIds/allowedZoneIds scope, which the engine enforces. For production, the Backend must supply those grants from authenticated user context. Group metrics and any comparison against the outside market must use an approved, same-definition Data Package.
The browser flow is a demo adapter. It does not persist artifacts in a shared store or execute the v5.1 batch run (GC-15). Those integrations require the production orchestrator and artifact services. The deterministic service covers the interactive comparison modes and returns artifacts inline.
