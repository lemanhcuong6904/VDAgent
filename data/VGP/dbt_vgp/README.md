# dbt_vgp — dbt project cho VGP Data Warehouse (mo rong ngoai schema v3 goc)

dbt project THAT (khong phai chi tai lieu mo ta) — doc truc tiep 17 file CSV trong
`../data/` qua dbt-duckdb (`meta.external_location`, khong copy du lieu), dung lai
toan bo logic Python trong `generate_vgp_mock.py` duoi dang SQL cho mart chan doan,
them 1 mart consolidation tong hop hieu suat kenh phan phoi tu Bridge + Attribution,
va 1 helper xac dinh ky snapshot "active" dung chung cho toan bo project.

## Cai dat

```bash
pip install "dbt-core==1.7.13" "dbt-duckdb==1.7.1"
```

(Ban dbt-core moi nhat qua `pip install dbt-core` bi loi tai `dbt-core-experimental-parser`
do moi truong mang gioi han download file lon — da xac nhan pin ban 1.7.13 chay on dinh.)

## Chay

```bash
cd dbt_vgp
export DBT_PROFILES_DIR="$(pwd)/profiles"   # hoac set DBT_PROFILES_DIR tren Windows
dbt debug   # kiem tra ket noi
dbt build   # chay toan bo model + test
```

Chay xong tao file `vgp.duckdb` (warehouse cuc bo) trong thu muc nay — co the mo
bang `duckdb vgp.duckdb` de query truc tiep, hoac `../data/build_benchmark.py` se tu
dong gan (ATTACH) file nay de test cac cau hoi dung mart consolidation (xem cuoi file).

**QUAN TRONG — luon `cd dbt_vgp` truoc khi chay `dbt build`**: `_sources.yml` va
`profiles.yml` dung **duong dan TUONG DOI** (`../data/...`, `vgp.duckdb`), tinh tu
thu muc lam viec (CWD) luc goi lenh `dbt`. Neu chay `dbt build` tu 1 thu muc khac
(khong phai `dbt_vgp/`), duong dan se resolve sai. Da xac minh: **project di
chuyen duoc sang bat ky may/thu muc nao** (test thuc te bang cach copy toan bo
`2509_VinGrandPark/` sang duong dan khac hoan toan roi chay lai ca 3 buoc - generator,
`dbt build`, `build_benchmark.py` - deu PASS 100% khong can sua gi). Ban truoc day
tung hardcode duong dan tuyet doi `C:/A47752_HaDuyAnh/...` o 4 cho
(`_sources.yml`, `profiles.yml`, `generate_vgp_mock.py`, `build_benchmark.py`) - da
sua het sang duong dan tuong doi/tu suy tu vi tri file (`os.path.dirname(os.path.abspath(__file__))`
trong Python, `../data/...` trong dbt).

**Luu y**: phai chay `dbt build` truoc khi chay `build_benchmark.py` neu muon cac
cau hoi #29-31 (dung mart consolidation) chay duoc.

## Hop dong khoa Central DWH (`warehouse/id_registry.json`)

VGP la 1/5 Project Data Pack hop nhat vao 1 Central DWH (`vdagent_dw_re`, task N3).
Sau audit phat hien 6 vi phap cau truc so voi hop dong nay, da sua het:
`project_key` gio la **1 dong duy nhat = 300** (`project_id="PRJ-VGP"`) thay vi 6
dong nhu truoc; `zone_key` re-key ve dai **301-399**; `channel_key` ve **3001-3099**;
`infra_key` ve **3101-3199**; `unit_code` doi format thanh `VGP-U`+5 so thu tu toan
cuc (`unit_id` cu bi bo - khong phai field trong hop dong). Chi tiet day du (bang
doi chieu truoc/sau, ly do thiet ke) o [`../data/README.md` muc 1.2](../data/README.md).

**Anh huong toi cac model trong project nay**: `project_key` gio la hang so, KHONG
con dung de phan biet 6 phan khu (Rainbow/Origami/.../Opus One) duoc nua - moi cho
truoc day GROUP BY/JOIN theo `project_key` (Peer Group trong `int_peer_median.sql`,
join lay `is_sales_permit_issued`/`is_bank_guarantee_issued` trong
`dm_unit_friction_diagnostics.sql`, median gia thu cap trong `int_secondary_stats.sql`)
da doi sang dung `dim_zone_master.sub_project_id`/`sub_project_name` (8 cot MOI,
chuyen xuong tu `dim_project_profile` cu) thay the - join qua `zone_key` (fact ->
`dim_zone_master`, van la single-hop, dung tinh than Text-to-SQL cua thiet ke goc).

## Cau truc

```
models/
  staging/            -- 1:1 voi cac nguon CSV (view, doc truc tiep CSV qua external_location)
    stg_dim_project_profile.sql, stg_dim_zone_master.sql, stg_dim_unit_master.sql,
    stg_dim_sales_channel.sql, stg_dim_secondary_market_comps.sql,
    stg_fact_unit_inventory_snapshot.sql, stg_fact_sales_funnel_daily.sql,
    stg_fact_market_macro_monthly.sql, stg_semantic_config.sql,
    stg_snapshot_manifest.sql             -- Moi: expose cot is_active
    stg_bridge_unit_channel_history.sql   -- Bridge (mo rong)
    stg_fact_funnel_attribution.sql       -- Attribution (mo rong)
    _sources.yml            -- khai bao 17 nguon (external_location)
    _staging__schema.yml    -- test cho stg_snapshot_manifest + 2 staging Bridge/Attribution
  marts/
    int_active_snapshot.sql          -- Moi: helper 1 dong xac dinh ky ACTIVE
    int_peer_median.sql              -- Peer Group 2 tang (vector hoa lai bang SQL),
                                         nhom theo sub_project_id (dim_zone_master),
                                         KHONG con dung project_key (gio la hang so 300)
    int_defect_thermal_penalty.sql   -- diem phat khuyet tat vat ly + vi khi hau
    int_secondary_stats.sql          -- trung vi gia thu cap + co gan day (tinh tu ky ACTIVE),
                                         nhom theo sub_project_id (dim_secondary_market_comps)
    int_funnel_dropoff.sql           -- ty le rut coc tich luy
    dm_unit_friction_diagnostics.sql -- MART 1: ma tran 8 nguyen nhan, tinh lai
                                         hoan toan bang SQL (khong doc lai CSV Python)
    mart_channel_attribution_performance.sql
                                      -- MART 2: tong hop hieu suat tung san
                                         phan phoi tu Bridge + Attribution - xem mo ta grain o duoi
    _marts__schema.yml       -- test cho int_active_snapshot + 2 mart + 2 model int_* khac
tests/                        -- singular test (moi file = 1 test, FAIL neu co dong tra ve)
  assert_dbt_matches_python_diagnostics.sql
    -- So sanh primary_cause_code giua ban SQL (dm_unit_friction_diagnostics) va
    -- ban Python (source dm_unit_friction_diagnostics_python). PASS = khop tuyet doi.
  assert_bridge_exactly_one_current_per_unit.sql
    -- Moi unit_key phai co DUNG 1 dong is_current=TRUE trong bridge_unit_channel_history.
  assert_attribution_weight_valid_range.sql
    -- attribution_weight phai nam trong (0, 1].
  assert_attribution_weight_sums_to_one.sql
    -- Tong attribution_weight theo (unit_key, outcome_date_key) phai xap xi 1.0
    -- (dung sai 0.01) - dung quy tac mo hinh LINEAR.
  assert_exactly_one_active_snapshot.sql
    -- Phai co DUNG 1 kỳ is_active=TRUE trong snapshot_manifest.
```

## Mart consolidation: `mart_channel_attribution_performance`

**Muc dich**: tra loi cac cau hoi ve hieu suat san phan phoi ("san nao dang giu
nhieu can nhat", "san nao dong gop nhieu nhat vao chuyen doi theo attribution") ma
truoc day KHONG co mart nao xu ly - Bridge/Attribution truoc do chi la 2 bang du
lieu tho, chua co tang tong hop.

**Grain**: 1 dong / 1 `channel_key` (`dim_sales_channel`) - tong hop TOAN BO lich
su, khong theo tung ky snapshot (vi Bridge/Attribution la du lieu xuyen suot vong
doi can, khong phai ban chup dinh ky nhu `fact_unit_inventory_snapshot`).

**Khoa noi**:
- `stg_dim_sales_channel.channel_key` (LEFT JOIN goc)
- `stg_bridge_unit_channel_history.channel_key` (agg: so can dang/da tung duoc giao)
- `stg_fact_funnel_attribution.channel_key` (agg: so touchpoint + tong trong so
  dong gop duoc quy ve kenh nay, xac dinh qua bridge tai dung thoi diem touchpoint)

**KHONG dung lai / khong nhan ban logic** cua `dm_unit_friction_diagnostics` - day
la goc nhin hoan toan khac (hieu suat kenh/marketing attribution vs. chan doan ly
do ton kho), 2 mart doc lap, khong tham chieu chung.

**Cach dung**: `SELECT * FROM main_marts.mart_channel_attribution_performance` sau
`dbt build`, hoac xem cau hoi #29-31 trong `../data/18_benchmark_gold_sql.csv`
(doc truc tiep tu bang nay qua ATTACH, khong tinh lai).

## Quy uoc "snapshot active" (co cot rieng, co can cu ro rang)

**Da co can cu nghiep vu** (yeu cau tuong minh) nen KHONG con dung quy uoc ngam
"kỳ moi nhat = MAX(snapshot_date_key)" nua. Thay vao do:

- `snapshot_manifest.is_active` (BOOLEAN, cot MO RONG so voi schema v3 goc) —
  danh dau DUNG 1 kỳ la kỳ CHINH THUC dung de bao cao. Hien tai:
  **`is_active = TRUE` cho kỳ 2026-06-30**, cac kỳ con lai (04-30, 05-31, 07-31,
  08-31, 09-29) deu `FALSE`.
- `semantic_config.active_snapshot_date_key = 20260630` — ban sao dang so nguyen,
  tien dung cho SQL khong muon JOIN/loc boolean.
- `int_active_snapshot.sql` — model helper 1 dong, MOI noi trong dbt project can
  biet "ky active" PHAI `ref()` toi day (`int_secondary_stats.sql` la vi du), KHONG
  duoc hardcode ngay truc tiep trong SQL.
- Test `assert_exactly_one_active_snapshot.sql` dam bao luon co dung 1 kỳ active.

**Phan biet 2 khai niem**:
| Khai niem | Gia tri | Y nghia |
|---|---|---|
| Kỳ **active** | 2026-06-30 | Kỳ chinh thuc dung de bao cao (business rule tuong minh) |
| Kỳ **moi NAP gan nhat** | 2026-09-29 | `MAX(snapshot_date)` - du lieu da nap toi day nhung 3 kỳ sau active (07-31, 08-31, 09-29) coi la so bo/chua chinh thuc |

Neu sau nay kỳ active thay doi (vi du sang thang tiep theo), chi can sua
`ACTIVE_SNAPSHOT_DATE` trong `generate_vgp_mock.py` roi chay lai - toan bo pipeline
(Python + dbt + benchmark) se tu dong dung nhat quan vi deu doc tu cung 1 nguon
(`snapshot_manifest.is_active`), khong co hardcode rai rac.

## Ket qua lan chay gan nhat

`dbt build`: **68/68 PASS** (17 view model + 2 table model, 49 test) — re-verify
sau khi sua theo hop dong `id_registry.json` (gop `project_key` 6->1, re-key
zone/channel/infra_key, doi format `unit_code`). Bao gom:
- Test doi chieu Python vs SQL tren toan bo 2.144 dong chan doan — khop tuyet doi
  (bao gom logic "secondary gan day" nay da doi sang tinh tu ky ACTIVE 06-30, ca 2
  ben Python va SQL deu dung cung moc nen van khop).
- Test rang buoc Bridge (`assert_bridge_exactly_one_current_per_unit`) va
  Attribution (`assert_attribution_weight_valid_range`,
  `assert_attribution_weight_sums_to_one`) — deu PASS.
- Test `assert_exactly_one_active_snapshot` — PASS.
- Toan bo test quan he khoa ngoai (`relationships`) giua cac staging model moi va
  `dim_unit_master`/`dim_sales_channel`/`fact_sales_funnel_daily` — deu PASS.

## Gioi han da biet

- `int_peer_median` va `int_funnel_dropoff` dung gia dinh don gian hoa nhu ban
  Python (Peer Group 2 tang thay vi 6 tieu chi day du; funnel dropoff xap xi dung
  chung cho ca 6 ky thay vi tinh rieng tung ky) - xem `../data/README.md`.
- `mart_channel_attribution_performance` tong hop TOAN BO lich su (khong co chieu
  thoi gian/snapshot) - neu can phan tich xu huong hieu suat kenh theo thoi gian,
  se can them cot ky/thang vao grain.
- 7 staging model con lai (`dim_date`, `dim_infrastructure_assets`,
  `fact_unit_price_history`, `fact_sales_channel_performance`...) da co source
  declared nhung CHUA co file .sql staging rieng - ngoai pham vi cac lan cap nhat
  gan day (chi tap trung Bridge/Attribution + mart consolidation + active snapshot
  theo yeu cau).
- Ky ACTIVE (06-30) chi anh huong toi cac truy van/model CHU DONG tham chieu
  `int_active_snapshot` (vd `int_secondary_stats`, cac cau hoi benchmark #6-8, #15,
  #19, #22, #24). Cac bang fact van chua/luu du lieu day du ca 6 kỳ (04-30 den
  09-29) - ky active KHONG xoa hay an di du lieu cac kỳ khac, chi la 1 con tro
  metadata cho biet kỳ nao "chinh thuc" khi can 1 moc duy nhat de bao cao.
