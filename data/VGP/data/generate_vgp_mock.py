# -*- coding: utf-8 -*-
"""
Generator v3 - VECTORIZED (pandas/numpy), quy mo THAT theo nghien cuu 6 phan khu
VGP (~33.600 can - xem bang PROJECT_REAL_TOTAL_UNITS o khoi "6. dim_zone_master").
Da tung thu scale len 300.000 can (v2) nhung xac nhan KHONG phu hop thuc te (vuot
xa tong quy mo THAT cua ca 6 phan khu duoc mo hinh hoa) nen quay lai quy mo that,
dung dung so toa/so can THAT da cao duoc cho tung phan khu thay vi 1 con so dat
truoc. So voi ban dau (1.960 can, README goi la v3 cu/luc do), ban nay:
  - Dung DUNG so toa that: Rainbow 17, Origami 21, Beverly 6, Glory Heights 5
    (KHONG PHAI 8 nhu 2 ban truoc), Opus One 4 toa that OS1/OS2/OS3/OS5 (KHONG
    PHAI 8) voi DUNG so can tung toa (578/480/448/578, nguon xem README).
  - `units_per_floor` gio DAN XUAT tu (so can thuc te cua zone / total_floors)
    thay vi random doc lap - dam bao nhat quan noi bo (sua diem yeu da biet o
    ban 300k: "total_floors/units_per_floor khong khop so can thuc te"). Rieng 8
    zone LOW_RISE_VILLA (Manhattan Cum) KHONG dan xuat duoc (khong phai 1 toa chia
    tang) - total_floors/units_per_floor cua CHUNG ghi NULL (dung tinh than docx,
    truong nullable), thay vi hardcode 4/1 gay invariant gia nhu ban truoc do.
  - Van giu vector hoa pandas/numpy (van toan bo pipeline duoi day khong doi) de
    de dang scale lai neu can trong tuong lai.
  - Them 2 bang MOI ngoai schema v3 goc (theo yeu cau mo rong):
      16_bridge_unit_channel_history.csv (Bridge table)
      17_fact_funnel_attribution.csv (Attribution table)
  - dm_unit_friction_diagnostics tinh cho CA 6 KY SNAPSHOT (khong chi ky moi nhat).
  - Peer Group don gian hoa con 2 tang (project+type+floor_band -> project+type)
    thay vi 6 tieu chi day du - van giu don gian hoa nay du quy mo da giam, vi
    logic tinh toan khong phu thuoc quy mo va viec vector hoa 2 tang de doc/bao
    tri hon (xem README ve danh doi nay).
"""
import csv
import os
import numpy as np
import pandas as pd
from datetime import date, timedelta

RNG_SEED = 42
rng = np.random.default_rng(RNG_SEED)

# Ghi vao dung thu muc chua file script nay (data/) - KHONG hardcode duong dan
# tuyet doi, de ca project di chuyen duoc sang may/thu muc khac ma khong phai sua.
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUT_DIR, exist_ok=True)

def write_csv_df(name, df):
    path = os.path.join(OUT_DIR, name)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"wrote {name}: {len(df):,} rows, {len(df.columns)} cols")

def d(y, m, dd):
    return date(y, m, dd)

def date_key_s(dt_series):
    return dt_series.dt.strftime("%Y%m%d").astype(int)

def date_key(dt):
    return int(dt.strftime("%Y%m%d"))

# ---------------------------------------------------------------------------
# 0. HANG SO NGHIEP VU (giu nguyen tu ban v1)
# ---------------------------------------------------------------------------
OVERDUE_THRESHOLD_DAYS = 90
PEER_MIN_SAMPLE_SIZE = 5
DEFECT_TRASH_ROOM_HARD_M = 3.0
DEFECT_TRASH_ROOM_SOFT_M = 5.0
DEFECT_DARK_BEDROOM_POINTS_PER = 15
DEFECT_EFFICIENCY_HARD = 0.75
DEFECT_EFFICIENCY_SOFT = 0.80
THERMAL_WEST_EXPOSURE_HARD_PCT = 0.50
THERMAL_WEST_EXPOSURE_SOFT_PCT = 0.25
THERMAL_OBSTRUCTION_HARD_M = 8.0
SECONDARY_GAP_TRIGGER_PCT = 15.0
PIR_TRIGGER_RATIO = 20.0
PEER_OVERPRICE_TRIGGER_PCT = 8.0
LOW_COMMISSION_THRESHOLD_PCT = 1.5
FUNNEL_DROPOFF_TRIGGER_PCT = 60.0
DEFECT_UNIT_SHARE = 0.18
DEFECT_MISPRICED_SHARE = 0.45

SNAPSHOT_DATES = [d(2026,4,30), d(2026,5,31), d(2026,6,30), d(2026,7,31), d(2026,8,31), d(2026,9,29)]
SNAPSHOT_DATES_TS = [pd.Timestamp(x) for x in SNAPSHOT_DATES]
TODAY = SNAPSHOT_DATES[-1]
TODAY_TS = pd.Timestamp(TODAY)
DIM_DATE_START = d(2025,1,1)
DIM_DATE_END = d(2026,12,31)
# Ky "ACTIVE" (chinh thuc dung de bao cao) theo yeu cau - KHAC voi ky moi NAP gan
# nhat (TODAY = 2026-09-29, vi du lieu van tiep tuc duoc nap). 2026-06-30 duoc
# gan danh dau la ky "chot so chinh thuc" (vi du: do tre chot so/kiem toan giua
# nam), cac ky sau (07-31, 08-31, 09-29) la du lieu so bo da nap nhung CHUA active.
# Day la CAN CU ro rang (khai bao tuong minh trong snapshot_manifest.is_active +
# semantic_config), khong phai tu y gan.
ACTIVE_SNAPSHOT_DATE = d(2026, 6, 30)
ACTIVE_SNAPSHOT_TS = pd.Timestamp(ACTIVE_SNAPSHOT_DATE)

# Hop dong khoa Central DWH (warehouse/id_registry.json + SNAPSHOT_RULES.md, task N3,
# owner Ha Duy Anh) - VGP la 1 trong 5 Project Data Pack hop nhat vao 1 kho trung tam.
# Dai khoa danh rieng cho VGP (project_key=300):
VGP_PROJECT_KEY = 300           # 1 du an = 1 project_key duy nhat (khong con 6 nhu truoc)
VGP_PROJECT_ID = "PRJ-VGP"
ZONE_KEY_BAND = (301, 399)      # zone_key: 301-399
CHANNEL_KEY_BAND = (3001, 3099)  # channel_key: 3001-3099
INFRA_KEY_BAND = (3101, 3199)    # infra_key: 3101-3199
UNIT_CODE_PREFIX = "VGP-U"
UNIT_CODE_WIDTH = 5
# Registry: dataset_id="vdagent_dw_re" (KHONG con hau to "_vgp"), dataset_version/
# semantic_version="3.1.0", source_system="ENTERPRISE_DW_RE" (KHONG con "_MOCK").
REGISTRY_DATASET_ID = "vdagent_dw_re"
REGISTRY_DATASET_VERSION = "3.1.0"
REGISTRY_SOURCE_SYSTEM = "ENTERPRISE_DW_RE"

# Quy mo can ho khong con la target dat truoc (300k) - gio DAN XUAT tu tong so
# can THAT/uoc luong co nguon cua tung phan khu (xem khoi "6. dim_zone_master").
print("Bat dau sinh du lieu VGP mock v3 (quy mo THAT theo nghien cuu 6 phan khu)...")

# ---------------------------------------------------------------------------
# 1-2. snapshot_manifest, semantic_config
# ---------------------------------------------------------------------------
manifest_rows = [[f"SNAP-{sd.strftime('%Y%m%d')}-01", REGISTRY_DATASET_ID, REGISTRY_DATASET_VERSION,
                   REGISTRY_DATASET_VERSION, sd.isoformat(), "Asia/Ho_Chi_Minh", "VND",
                   "ASKING_EXCL_VAT_EXCL_MAINT", "NET_INTERNAL_M2", REGISTRY_SOURCE_SYSTEM,
                   sd == ACTIVE_SNAPSHOT_DATE]
                  for sd in SNAPSHOT_DATES]
write_csv_df("01_snapshot_manifest.csv", pd.DataFrame(manifest_rows, columns=[
    "snapshot_id","dataset_id","dataset_version","semantic_version","snapshot_date",
    "timezone","currency","price_basis","area_basis","source_system","is_active"]))

V = REGISTRY_DATASET_VERSION
config_rows = [
    ["overdue_threshold_days", str(OVERDUE_THRESHOLD_DAYS), "INTEGER", V, "APPROVED",
     "So ngay DOM toi thieu de can duoc coi la qua han ban."],
    ["peer_min_sample_size", str(PEER_MIN_SAMPLE_SIZE), "INTEGER", V, "APPROVED",
     "Co mau toi thieu cua peer group."],
    ["defect_trash_room_hard_m", str(DEFECT_TRASH_ROOM_HARD_M), "DECIMAL", V, "APPROVED", ""],
    ["defect_trash_room_soft_m", str(DEFECT_TRASH_ROOM_SOFT_M), "DECIMAL", V, "APPROVED", ""],
    ["secondary_gap_trigger_pct", str(SECONDARY_GAP_TRIGGER_PCT), "DECIMAL", V, "APPROVED", ""],
    ["pir_trigger_ratio", str(PIR_TRIGGER_RATIO), "DECIMAL", V, "APPROVED", ""],
    ["peer_overprice_trigger_pct", str(PEER_OVERPRICE_TRIGGER_PCT), "DECIMAL", V, "APPROVED", ""],
    ["low_commission_threshold_pct", str(LOW_COMMISSION_THRESHOLD_PCT), "DECIMAL", V, "APPROVED", ""],
    ["funnel_dropoff_trigger_pct", str(FUNNEL_DROPOFF_TRIGGER_PCT), "DECIMAL", V, "APPROVED", ""],
    ["defect_unit_share_assumption", str(DEFECT_UNIT_SHARE), "DECIMAL", V, "PENDING",
     "Ty le can gia lap chiu loi cau truc - tu hieu chinh."],
    ["attribution_model_default", "LINEAR", "STRING", V, "PENDING",
     "Mo hinh attribution mac dinh cho fact_funnel_attribution (bang mo rong ngoai schema goc)."],
    ["active_snapshot_date_key", str(date_key(ACTIVE_SNAPSHOT_DATE)), "INTEGER", V, "APPROVED",
     "Ky snapshot CHINH THUC dung de bao cao (khac ky moi NAP gan nhat trong "
     "fact_unit_inventory_snapshot - xem cot is_active trong snapshot_manifest)."],
]
write_csv_df("02_semantic_config.csv", pd.DataFrame(config_rows, columns=[
    "config_key","config_value","value_type","semantic_version","approval_status","description"]))

# ---------------------------------------------------------------------------
# 3. dim_date
# ---------------------------------------------------------------------------
all_dates = pd.date_range(DIM_DATE_START, DIM_DATE_END, freq="D")
dim_date = pd.DataFrame({"full_date": all_dates})
dim_date["date_key"] = date_key_s(dim_date["full_date"])
dim_date["year"] = dim_date["full_date"].dt.year
dim_date["quarter"] = dim_date["full_date"].dt.quarter
dim_date["month"] = dim_date["full_date"].dt.month
dim_date["day_of_month"] = dim_date["full_date"].dt.day
dim_date["is_weekend"] = dim_date["full_date"].dt.dayofweek >= 5
dim_date["fiscal_quarter"] = dim_date["year"].astype(str) + "-Q" + dim_date["quarter"].astype(str)
dim_date["full_date"] = dim_date["full_date"].dt.strftime("%Y-%m-%d")
dim_date = dim_date[["date_key","full_date","year","quarter","month","day_of_month","is_weekend","fiscal_quarter"]]
write_csv_df("03_dim_date.csv", dim_date)
DATE_KEY_SET = set(dim_date["date_key"])

print("Da xong: manifest, config, dim_date")

# ---------------------------------------------------------------------------
# 4. dim_infrastructure_assets
# ---------------------------------------------------------------------------
# infra_key re-key ve dai 3101-3199 theo warehouse/id_registry.json (band project_key=300)
infra_rows = [
    [INFRA_KEY_BAND[0] + 0, "INF-METRO-01", "Tuyen Metro so 1 Ben Thanh - Suoi Tien", "URBAN_METRO",
     "COMMERCIAL_OPERATION", 100.00, 2021, 2024],
    [INFRA_KEY_BAND[0] + 1, "INF-VANHDAI3-TD", "Vanh dai 3 TP.HCM (doan qua TP. Thu Duc)", "RING_ROAD",
     "UNDER_CONSTRUCTION", 82.50, 2025, 2026],
    [INFRA_KEY_BAND[0] + 2, "INF-METRO-07", "Tuyen Metro so 7 (Tan Kien - Vinhomes Grand Park)", "URBAN_METRO",
     "PLANNING_APPROVED", None, None, None],
    [INFRA_KEY_BAND[0] + 3, "INF-CT-LONGTHANH", "Cao toc TP.HCM - Long Thanh - Dau Giay (mo rong)", "EXPRESSWAY",
     "UNDER_CONSTRUCTION", 70.00, 2026, 2026],
]
write_csv_df("08_dim_infrastructure_assets.csv", pd.DataFrame(infra_rows, columns=[
    "infra_key","infra_id","infra_name","infra_type","lifecycle_stage",
    "construction_progress_pct","original_completion_year","revised_completion_year"]))

# ---------------------------------------------------------------------------
# 5. dim_project_profile - CHI 1 DONG (project_key=300, project_id="PRJ-VGP")
# theo warehouse/id_registry.json: "Mot du an = mot project_key duy nhat. Cac
# phase/toa thap con nam duoi project_key do bang zone_key, KHONG tao them
# project_key." Truoc day co 6 project_key rieng (1 per phan khu) - SAI kien
# truc so voi hop dong. 6 phan khu (Rainbow/Origami/Beverly/Glory Heights/
# Manhattan/Opus One) van giu day du thuoc tinh rieng (segment, construction_
# status, is_sales_permit_issued, is_bank_guarantee_issued, handover...) nhung
# duoc CHUYEN XUONG cap dim_zone_master (xem khoi "6. dim_zone_master" ben
# duoi) - dung tinh than vi du "The Beverly" cua Ocean Park trong note #48-50
# id_registry.json. SUB_PROJECTS o day la bien NOI BO Python (KHONG ghi thanh
# project_key trong bat ky CSV nao nua) dung de dan xuat cac thuoc tinh do.
SUB_PROJECTS = [
    (1, "PRJ-VGP-RAINBOW", "The Rainbow - Vinhomes Grand Park", "MID",
     "HANDED_OVER", 100.00, True, True, d(2020,12,31), (42,55), 17),
    (2, "PRJ-VGP-ORIGAMI", "The Origami - Vinhomes Grand Park", "MID_HIGH",
     "HANDED_OVER", 100.00, True, True, d(2021,6,30), (58,70), 21),
    (3, "PRJ-VGP-BEVERLY", "The Beverly - Vinhomes Grand Park", "MID_HIGH",
     "HANDED_OVER", 100.00, True, True, d(2022,3,31), (60,75), 6),
    (4, "PRJ-VGP-GLORY", "Glory Heights - Vinhomes Grand Park", "MID_HIGH",
     "HANDED_OVER", 100.00, True, True, d(2022,9,30), (53.2,77.7), 8),
    # is_bank_guarantee_issued=False = KICH BAN BENCHMARK CAY TAY (xem README)
    (5, "PRJ-VGP-MANHATTAN", "The Manhattan - Vinhomes Grand Park", "MID_HIGH",
     "HANDED_OVER", 100.00, True, False, d(2022,12,31), (65,85), 8),
    (6, "PRJ-VGP-OPUSONE", "The Opus One - Vinhomes Grand Park", "MID_HIGH",
     "SUPERSTRUCTURE", 55.00, True, True, d(2028,12,31), (70,95), 8),
]
# Gia tri du an TONG HOP (aggregate) tu 6 phan khu - chi mang tinh mo ta/tom tat
# o cap project_key=300, KHONG dung de dan xuat logic chan doan (logic van dung
# gia tri rieng tung phan khu qua dim_zone_master). Chon:
#  - segment: da so (5/6) la MID_HIGH.
#  - construction_status: "SUPERSTRUCTURE" vi Opus One (1/6) van dang xay -
#    du an TONG THE chua "100% ban giao".
#  - construction_progress_pct: trung binh KHONG trong so 6 phan khu.
#  - is_sales_permit_issued: True (ca 6 phan khu deu True).
#  - is_bank_guarantee_issued: False (Manhattan la ngoai le - co canh bao la
#    dai dien cho toan du an, phan anh dung tinh than "khong PHAI tat ca deu
#    co bao lanh").
#  - expected_handover_date: MAX (du an chi thuc su "xong" khi phan cuoi
#    cung - Opus One - ban giao).
_agg_progress = round(sum(p[5] for p in SUB_PROJECTS) / len(SUB_PROJECTS), 2)
_agg_handover = max(p[8] for p in SUB_PROJECTS)
# Giu NGUYEN so lan goi rng.integers(1200,3500) nhu vong lap 6 phan khu cu (1 lan/
# phan khu) du gio chi con 1 dong - tranh lech RNG stream cho toan bo phan sinh
# du lieu phia sau (da xac minh: bo 5 lan goi lam SECONDARY_ARBITRAGE - von da rat
# mong, 4/2144 ca - roi ve 0 do random variance, pha vo yeu cau "scenario
# coverage du 8 nguyen nhan" da xac lap tu dau). Chi lay 1 gia tri dai dien.
_distance_samples = [int(rng.integers(1200, 3500)) for _ in SUB_PROJECTS]
project_rows = [[
    VGP_PROJECT_KEY, VGP_PROJECT_ID, "Vinhomes Grand Park", "MKT-THUDUC-VGP",
    "Thu Duc - Vinhomes Grand Park", "TP. Ho Chi Minh", "TP. Thu Duc",
    "Vingroup (Vinhomes)", "TIER_1", "DOMESTIC",
    "MID_HIGH", "SUPERSTRUCTURE", _agg_progress, True, False, False,
    "INF-METRO-01", _distance_samples[0], "Techcombank", _agg_handover.isoformat(),
]]
write_csv_df("04_dim_project_profile.csv", pd.DataFrame(project_rows, columns=[
    "project_key","project_id","project_name","market_id","market_name","province_city","district",
    "developer_name","developer_tier","developer_origin","segment","construction_status",
    "construction_progress_pct","is_sales_permit_issued","is_bank_guarantee_issued",
    "max_foreign_quota_exceeded","primary_infra_id","distance_to_primary_infra_m",
    "partner_bank_name","expected_handover_date"]))
# Cac dict noi bo nay dung sub_project_key (1-6, KHONG phai project_key CSV nua)
# lam key - giu nguyen toan bo logic nghiep vu hien co (handover/band/is_permit/
# is_bank/is_selling) khong doi, chi khac cho GHI RA CSV.
SUB_PROJECT_INFO = {p[0]: p for p in SUB_PROJECTS}
SUB_PROJECT_BAND = {pk: p[9] for pk, p in SUB_PROJECT_INFO.items()}

print("Da xong: infra, project")

# ---------------------------------------------------------------------------
# 6. dim_zone_master - QUY MO THAT (khong con theo duoi muc tieu 300k nua - da
# xac nhan 300k KHONG phu hop thuc te). Dung DUNG so toa THAT + tong so can THAT
# (hoac uoc luong co nguon) cho tung phan khu, nghien cuu bo sung 2026-09-29:
#   - Rainbow:  17 toa that,    ~10.400 can (CAO: vinhomes.vn/market.vinhomes.vn,
#               2 nguon cho 10.343-10.435, lay trung binh)
#   - Origami:  21 toa that,    12.000 can THAT (CAO, da xac nhan tu truoc)
#   - Beverly:   6 toa that,     5.088 can (CAO: cafeland.vn/market.vinhomes.vn -
#               so nay la CA KHU gom ca cum Solari, khong tach rieng duoc 6 toa
#               chinh, dung lam tong cho ca 6 toa)
#   - Glory Heights: 5 toa that (KHONG PHAI 8 nhu ban truoc - da sua),
#               ~3.500 can (CAO nhung nguon khong thong nhat: 3.450-3.620,
#               lay gia tri giua)
#   - Manhattan: villa thap tang, 550 can THAT (CAO, khong doi), chia uoc le
#               thanh 8 cum minh hoa (KHONG PHAI so cum that, chi la chia deu)
#   - Opus One:  4 toa that (OS1,OS2,OS3,OS5 - KHONG PHAI 8 nhu ban truoc),
#               dung DUNG so tang x can/tang THAT tung toa (CAO:
#               onehousing.vn/blog/du-an-the-opus-one...):
#               OS1=34 tang x17 can/tang=578, OS2=32x15=480,
#               OS3=32x14=448, OS5=34x17=578 (tong 2.084; nguon khac cho
#               tong 1.952 - 2 nguon lech ~6%, uu tien so chi tiet tung toa
#               vi cu the/co the kiem chung hon)
# LUU Y: day la quy mo THAT cua 6 phan khu duoc mo hinh hoa trong bo du lieu
# nay - KHONG PHAI toan bo VGP that (~44.000 "san pham BDS" gom ca thap tang/
# shophouse cua NHIEU phan khu khac ma bo du lieu nay chua mo hinh hoa).
# ---------------------------------------------------------------------------
ZONE_COUNT = {1: 17, 2: 21, 3: 6, 4: 5, 5: 8, 6: 4}
ZONE_PREFIX = {1: "Rainbow", 2: "Origami", 3: "Beverly", 4: "Glory Heights",
               5: "Manhattan Cum", 6: "Opus One"}
VILLA_PROJECT = 5
PROJECT_REAL_TOTAL_UNITS = {1: 10_400, 2: 12_000, 3: 5_088, 4: 3_500, 5: 550, 6: 2_084}
# Opus One: dung DUNG so can tung toa that thay vi chia deu (xem ghi chu tren)
OPUS_ONE_REAL_TOWER_UNITS = [578, 480, 448, 578]  # OS1, OS2, OS3, OS5

zone_rows = []
zone_key_seq = ZONE_KEY_BAND[0]  # re-key ve dai 301-399 (warehouse/id_registry.json)
ZONE_KEY_OF = {}          # zone_key -> (sub_project_key, zone_type, total_floors, is_villa, n_units)
UNITS_BY_PROJECT_ZONE = []  # list of (zone_key, sub_project_key, n_units, is_villa)
for pk, n in ZONE_COUNT.items():
    is_villa = (pk == VILLA_PROJECT)
    prefix = ZONE_PREFIX[pk]
    label = "" if is_villa else "Toa "
    project_total = PROJECT_REAL_TOTAL_UNITS[pk]
    for i in range(1, n + 1):
        zid = f"{prefix.split()[0].upper()}{i}"
        zname = f"{label}{prefix} {i}"
        if is_villa:
            n_units_zone = round(project_total / n)  # chia deu (uoc le, xem ghi chu)
            # total_floors/units_per_floor la khai niem TOA APARTMENT theo docx goc
            # ("tong so tang noi cua toa thap", "mat do can ho tren 1 mat san tang") -
            # khong dan xuat duoc cho villa (moi zone la CUM nhieu can biet thu rieng
            # le, khong phai 1 toa chia tang). Docx de total_floors nullable rieng cho
            # truong hop nay (KHONG co huong dan gan cung). Truoc day hardcode 4/1 gay
            # invariant gia (4x1=4 != 69 can thuc/zone) - nay ghi NULL cho dung tinh
            # than docx, minh bach la "khong ap dung" thay vi so sai. total_floors_gen
            # rieng (4) van dung NOI BO de sinh floor_number cap CAN (bat buoc khong
            # null theo docx, dai dien so tang BEN TRONG 1 can biet thu don le).
            total_floors_gen, basement, upf, elev = 4, 0, 1, 0
            total_floors, upf_csv = None, None
            ztype, handover_std = "LOW_RISE_VILLA", "BARE_SHELL"
        elif pk == 6:
            n_units_zone = OPUS_ONE_REAL_TOWER_UNITS[i - 1]  # dung so that tung toa
            total_floors = [34, 32, 32, 34][i - 1]
            basement = int(rng.integers(2, 5))
            upf = round(n_units_zone / total_floors)  # dan xuat tu chinh so can that (nhat quan)
            elev = int(rng.integers(3, 6))
            ztype, handover_std = "HIGH_RISE_TOWER", "BASIC_FINISH"
            total_floors_gen, upf_csv = total_floors, upf
        else:
            n_units_zone = round(project_total / n)  # chia deu cho cac toa cung phan khu
            total_floors = int(rng.integers(25, 39))
            basement = int(rng.integers(2, 5))
            upf = round(n_units_zone / total_floors)  # dan xuat de nhat quan voi so can thuc sinh
            elev = int(rng.integers(3, 6))
            ztype, handover_std = "HIGH_RISE_TOWER", "BASIC_FINISH"
            total_floors_gen, upf_csv = total_floors, upf
        elevator_ratio = round(upf / elev, 1) if elev else None
        # Thuoc tinh rieng phan khu (segment/construction_status/permit/bank/handover)
        # CHUYEN XUONG day tu dim_project_profile cu (xem ghi chu khoi "5.") - moi
        # zone ke thua dung 1 bo gia tri cua phan khu (sub_project_key=pk) no thuoc ve.
        sp = SUB_PROJECT_INFO[pk]  # (pk, sub_id, sub_name, seg, status, prog, permit, bank, handover, band, nzones)
        zone_rows.append([zone_key_seq, f"ZN-{zid}", VGP_PROJECT_KEY, zname, ztype, total_floors, basement,
                           upf_csv, elev if elev else None, elevator_ratio, handover_std,
                           sp[1], sp[2], sp[3], sp[4], sp[5], sp[6], sp[7], sp[8].isoformat()])
        ZONE_KEY_OF[zone_key_seq] = (pk, ztype, total_floors_gen, is_villa, n_units_zone)
        UNITS_BY_PROJECT_ZONE.append((zone_key_seq, pk, n_units_zone, is_villa))
        zone_key_seq += 1
write_csv_df("05_dim_zone_master.csv", pd.DataFrame(zone_rows, columns=[
    "zone_key","zone_id","project_key","zone_name","zone_type","total_floors","basement_floors",
    "units_per_floor","passenger_elevators","elevator_ratio","handover_standard",
    # 8 cot MOI - mo rong ngoai schema goc, chua thuoc tinh phan khu (truoc day o
    # dim_project_profile, nay chuyen xuong day vi project_key gio la 1 hang duy
    # nhat theo warehouse/id_registry.json - xem README):
    "sub_project_id","sub_project_name","segment","construction_status",
    "construction_progress_pct","is_sales_permit_issued","is_bank_guarantee_issued",
    "expected_handover_date"]))

TOTAL_UNITS = sum(n for _, _, n, _ in UNITS_BY_PROJECT_ZONE)
print(f"So zone: {len(zone_rows)} | Tong so can se sinh: {TOTAL_UNITS:,}")

# ---------------------------------------------------------------------------
# 7. dim_sales_channel
# ---------------------------------------------------------------------------
# channel_key re-key ve dai 3001-3099 theo warehouse/id_registry.json
_ck = CHANNEL_KEY_BAND[0]
channel_rows = [
    [_ck + 0, "AGENCY-KHAIHOANLAND", "Khai Hoan Land (Platinum Agency)", "TIER_1_EXCLUSIVE", 180],
    [_ck + 1, "AGENCY-DONGTAYLAND", "Dong Tay Land (Platinum Plus Agency)", "TIER_1_EXCLUSIVE", 220],
    [_ck + 2, "AGENCY-SAIGONREAL", "Saigon Real (Dat Xanh South)", "TIER_2_GENERAL", 95],
    [_ck + 3, "INHOUSE-VINHOMES", "Vinhomes Sales - Doi ban hang noi bo", "INHOUSE", 60],
    [_ck + 4, "AGENCY-GENERIC-01", "Dai ly phan phoi thu cap A (mock)", "TIER_2_GENERAL", 40],
]
write_csv_df("07_dim_sales_channel.csv", pd.DataFrame(channel_rows, columns=[
    "channel_key","channel_id","channel_name","channel_tier","active_brokers_count"]))
CHANNEL_KEYS = [r[0] for r in channel_rows]
CHANNEL_TIER = {r[0]: r[3] for r in channel_rows}
CHANNEL_COMMISSION_BASE = {"TIER_1_EXCLUSIVE": (2.5, 3.5), "TIER_2_GENERAL": (1.5, 2.5), "INHOUSE": (1.0, 2.0)}

print("Da xong: zone, sales_channel")

# ---------------------------------------------------------------------------
# 8. dim_unit_master - VECTORIZED cho toan bo TOTAL_UNITS cung luc
# ---------------------------------------------------------------------------
UNIT_TYPE_AREA = {
    "STUDIO": (25, 32), "1PN": (34, 50), "2PN": (55, 72), "3PN": (75, 95),
    "4PN": (100, 130), "PENTHOUSE": (140, 220), "DUPLEX": (150, 250),
}
BEDROOM_OF = {"STUDIO":0,"1PN":1,"2PN":2,"3PN":3,"4PN":4,"PENTHOUSE":4,"DUPLEX":4}
ORIENTATIONS = np.array(["N","NE","E","SE","S","SW","W","NW"])
COOL_ORIENT = {"S","SE","E"}
HOT_ORIENT = {"W","SW","NW"}
VIEWS = np.array(["RIVER","PARK","POOL","CITY_OPEN","INTERNAL_COURT","OBSTRUCTED"])
TABOO_FLOORS = {4,7,13,14}
HIGHRISE_TYPES = np.array(["STUDIO","1PN","2PN","3PN","4PN","PENTHOUSE","DUPLEX"])
HIGHRISE_TYPE_W = np.array([10,25,30,20,10,3,2], dtype=float); HIGHRISE_TYPE_W /= HIGHRISE_TYPE_W.sum()
VILLA_TYPES = np.array(["4PN","DUPLEX"])

# expand tu cap zone len cap unit bang np.repeat
zone_key_arr = np.repeat([z[0] for z in UNITS_BY_PROJECT_ZONE], [z[2] for z in UNITS_BY_PROJECT_ZONE])
# sub_project_key_arr (1-6, phan khu that) - dung NOI BO cho MOI logic nghiep vu
# (handover/band/is_permit/is_bank/is_selling/peer group/batch id) giu nguyen
# HOAN TOAN nhu truoc. project_key CSV output gio la hang so VGP_PROJECT_KEY=300
# (xem khoi "5." o tren) - KHONG con dung project_key de phan biet phan khu nua,
# dung zone_key -> dim_zone_master.sub_project_id/sub_project_name thay the.
sub_project_key_arr = np.repeat([z[1] for z in UNITS_BY_PROJECT_ZONE], [z[2] for z in UNITS_BY_PROJECT_ZONE])
project_key_arr = np.full(len(zone_key_arr), VGP_PROJECT_KEY)
is_villa_arr = np.repeat([z[3] for z in UNITS_BY_PROJECT_ZONE], [z[2] for z in UNITS_BY_PROJECT_ZONE])
total_floors_map = {zk: v[2] for zk, v in ZONE_KEY_OF.items()}
total_floors_arr = np.array([total_floors_map[zk] for zk in zone_key_arr])
N = len(zone_key_arr)
assert N == TOTAL_UNITS
# unit_key bat dau tu UNIT_KEY_OFFSET+1 (KHONG phai 1) - nam trong dai
# 300001-399999 danh cho VGP (project_key=300) theo warehouse/id_registry.json.
UNIT_KEY_OFFSET = 300_000
unit_key_arr = np.arange(1, N + 1) + UNIT_KEY_OFFSET

# unit_code: theo dung dinh dang hop dong id_registry.json - prefix "VGP-U" + so
# thu tu TOAN CUC (1..N, KHONG phai theo tung zone nhu ban truoc) zero-pad 5 chu
# so, vi du "VGP-U00001" (KHONG dau gach giua prefix va so, KHAC ban truoc day
# dung dinh dang "VGP-U-300001" tu unit_key va "01-00001" tu so thu tu trong zone).
unit_code_arr = np.array([f"{UNIT_CODE_PREFIX}{i:0{UNIT_CODE_WIDTH}d}" for i in range(1, N + 1)])

unit_type_arr = np.empty(N, dtype=object)
villa_mask = is_villa_arr.astype(bool)
unit_type_arr[villa_mask] = rng.choice(VILLA_TYPES, size=villa_mask.sum())
unit_type_arr[~villa_mask] = rng.choice(HIGHRISE_TYPES, size=(~villa_mask).sum(), p=HIGHRISE_TYPE_W)

floor_number_arr = (rng.random(N) * total_floors_arr).astype(int) + 1
floor_number_arr = np.minimum(floor_number_arr, total_floors_arr)

lo_arr = np.array([UNIT_TYPE_AREA[t][0] for t in unit_type_arr], dtype=float)
hi_arr = np.array([UNIT_TYPE_AREA[t][1] for t in unit_type_arr], dtype=float)
net_area_arr = np.round(rng.uniform(lo_arr, hi_arr), 2)
efficiency_arr = np.round(rng.uniform(0.76, 0.88, N), 3)
gross_area_arr = np.round(net_area_arr / efficiency_arr, 2)
bedroom_arr = np.array([BEDROOM_OF[t] for t in unit_type_arr])
bathroom_arr = np.maximum(1, bedroom_arr)

floor_band_arr = np.select(
    [floor_number_arr <= 5, floor_number_arr <= 20, floor_number_arr <= 35],
    ["LOW", "MID", "HIGH"], default="TOP")

balcony_arr = rng.choice(ORIENTATIONS, size=N)
door_mask = rng.random(N) > 0.1
door_arr = np.where(door_mask, rng.choice(ORIENTATIONS, size=N), "")
view_arr = rng.choice(VIEWS, size=N, p=np.array([15,20,15,25,15,10], dtype=float) / 100)
is_corner_arr = rng.random(N) < 0.20

# --- khuyet tat vat ly (vector hoa, giu nguyen ty le tu ban v1) ---
has_defect_arr = rng.random(N) < DEFECT_UNIT_SHARE
defect_subtype_arr = rng.random(N) < 0.6   # True = loi phong rac gan (hard), False = loi ke thang may
dist_trash_arr = np.where(
    ~is_villa_arr.astype(bool) & has_defect_arr & defect_subtype_arr, rng.uniform(0.5, 2.9, N),
    np.where(~is_villa_arr.astype(bool) & has_defect_arr & ~defect_subtype_arr, rng.uniform(6.0, 15.0, N),
             rng.uniform(6.0, 20.0, N)))
dist_trash_arr = np.round(dist_trash_arr, 1)
adj_elev_arr = (~is_villa_arr.astype(bool)) & has_defect_arr & (~defect_subtype_arr | (rng.random(N) < 0.3))

dark_bedroom_arr = np.where(
    has_defect_arr & (bedroom_arr >= 2) & (rng.random(N) < 0.35),
    rng.integers(1, np.maximum(2, bedroom_arr)), 0)

is_hot_orient = np.isin(balcony_arr, list(HOT_ORIENT))
is_cool_orient = np.isin(balcony_arr, list(COOL_ORIENT))
west_exposure_arr = np.where(is_hot_orient, rng.uniform(0.30, 0.75, N),
                     np.where(is_cool_orient, rng.uniform(0.0, 0.15, N), rng.uniform(0.10, 0.30, N)))
west_exposure_arr = np.round(west_exposure_arr, 2)

view_obstruction_arr = np.where(view_arr == "OBSTRUCTED", rng.uniform(3.0, 12.0, N), rng.uniform(15.0, 80.0, N))
view_obstruction_arr = np.round(view_obstruction_arr, 1)

taboo_view_arr = np.where(rng.random(N) < 0.05,
                           rng.choice(np.array(["CEMETERY","WASTE_STATION","TEMPLE"]), size=N), "NONE")
is_taboo_floor_arr = np.isin(floor_number_arr, list(TABOO_FLOORS))

# unit_code_arr da tinh o tren (khoi expand cap unit) theo dung id_registry.json.
# unit_id (rieng, prefix "VGP-U-" tu unit_key) cua ban truoc BI BO - da phat hien
# day KHONG phai field trong hop dong id_registry.json (chi co unit_code), giu ca
# 2 field gan-trung-lap khong can thiet sau khi unit_code da chuan hoa dung spec.

dim_unit_master = pd.DataFrame({
    "unit_key": unit_key_arr, "unit_code": unit_code_arr,
    "project_key": project_key_arr, "zone_key": zone_key_arr, "unit_type": unit_type_arr,
    "bedroom_count": bedroom_arr, "bathroom_count": bathroom_arr,
    "net_area_m2": net_area_arr, "gross_area_m2": gross_area_arr,
    "floor_number": floor_number_arr, "floor_band": floor_band_arr,
    "balcony_orientation": balcony_arr, "door_orientation": door_arr, "view_primary_type": view_arr,
    "is_corner_unit": is_corner_arr, "efficiency_ratio": efficiency_arr,
    "distance_to_trash_room_m": dist_trash_arr, "is_adjacent_elevator": adj_elev_arr,
    "dark_bedroom_count": dark_bedroom_arr, "west_facing_exposure_pct": west_exposure_arr,
    "view_obstruction_distance_m": view_obstruction_arr, "taboo_view_type": taboo_view_arr,
    "is_taboo_floor": is_taboo_floor_arr,
})
write_csv_df("06_dim_unit_master.csv", dim_unit_master)
print(f"Da xong: unit_master ({len(dim_unit_master):,} can)")

# ---------------------------------------------------------------------------
# 9. unit_state (thuoc tinh kinh doanh moi can) - VECTORIZED
# ---------------------------------------------------------------------------
SUB_PROJECT_HANDOVER = {pk: p[8] for pk, p in SUB_PROJECT_INFO.items()}
SUB_PROJECT_STATUS = {pk: p[4] for pk, p in SUB_PROJECT_INFO.items()}
IS_SELLING_PROJECT = {pk: (SUB_PROJECT_STATUS[pk] == "SUPERSTRUCTURE") for pk in SUB_PROJECT_INFO}

is_defective_arr = (dist_trash_arr < DEFECT_TRASH_ROOM_SOFT_M) | adj_elev_arr | (dark_bedroom_arr > 0)
is_hot_arr = west_exposure_arr >= THERMAL_WEST_EXPOSURE_SOFT_PCT

# release_date: theo tung phan khu (sub_project_key_arr, KHONG phai project_key_arr
# - gio la hang so 300 nen khong con phan biet duoc phan khu nua)
handover_days = np.array([pd.Timestamp(SUB_PROJECT_HANDOVER[pk]).toordinal() for pk in sub_project_key_arr])
is_selling_arr = np.array([IS_SELLING_PROJECT[pk] for pk in sub_project_key_arr])
lead_days_arr = rng.integers(900, 1301, N)
jitter_arr = rng.integers(0, 401, N)
release_ord_handedover = handover_days - lead_days_arr + jitter_arr
opus_base_ord = pd.Timestamp(d(2025,10,1)).toordinal()
release_ord_selling = opus_base_ord + rng.integers(0, 301, N)
release_ord_arr = np.where(is_selling_arr, release_ord_selling, release_ord_handedover)
release_date_arr = pd.to_datetime([date.fromordinal(int(o)) for o in release_ord_arr])

# base_ppm2 (trieu VND/m2, theo bang gia du an) + type premium
TYPE_PREMIUM = {"STUDIO":1.05,"1PN":1.0,"2PN":0.97,"3PN":0.95,"4PN":0.93,"PENTHOUSE":1.35,"DUPLEX":1.20}
band_lo_arr = np.array([SUB_PROJECT_BAND[pk][0] for pk in sub_project_key_arr])
band_hi_arr = np.array([SUB_PROJECT_BAND[pk][1] for pk in sub_project_key_arr])
premium_arr = np.array([TYPE_PREMIUM[t] for t in unit_type_arr])
base_ppm2_arr = rng.uniform(band_lo_arr, band_hi_arr) * premium_arr

mispriced_defect_arr = is_defective_arr & (rng.random(N) < DEFECT_MISPRICED_SHARE)
discount_factor = np.where(is_defective_arr & ~mispriced_defect_arr, rng.uniform(0.90, 0.97, N), 1.0)
ppm2_arr = base_ppm2_arr * discount_factor

channel_key_arr = rng.choice(np.array(CHANNEL_KEYS), size=N, p=np.array([25,25,15,25,10], dtype=float)/100)
tier_arr = np.array([CHANNEL_TIER[c] for c in channel_key_arr])
comm_lo = np.array([CHANNEL_COMMISSION_BASE[t][0] for t in tier_arr])
comm_hi = np.array([CHANNEL_COMMISSION_BASE[t][1] for t in tier_arr])
base_commission_arr = np.round(rng.uniform(comm_lo, comm_hi), 2)
low_incentive_arr = (base_commission_arr <= LOW_COMMISSION_THRESHOLD_PCT) & (rng.random(N) < 0.5)

friction_arr = (mispriced_defect_arr.astype(float) * 0.9 + is_hot_arr.astype(float) * 0.5
                + low_incentive_arr.astype(float) * 0.7)
scale_days_arr = 120 * (1 + friction_arr)
duration_days_arr = rng.exponential(scale_days_arr).astype(int)
planned_sold_ord_arr = release_ord_arr + duration_days_arr
today_ord = pd.Timestamp(TODAY).toordinal()
planned_sold_valid = planned_sold_ord_arr <= today_ord   # False = khong bao gio ban duoc trong 6 ky

discount_pct0_arr = np.round(rng.uniform(0, 4, N), 2)

print("Da xong: unit_state (vector hoa)")

# ---------------------------------------------------------------------------
# 9b. KICH BAN BENCHMARK CAY TAY: LEGAL_PERMIT_BARRIER (2 can Manhattan)
# Cac nguyen nhan con lai (defect/PIR/overprice/secondary) duoc kiem tra thuc te
# o cuoi script sau khi sinh xong - Opus One ~2.084 can (quy mo that) co the du
# hoac khong du de cac nguyen nhan hiem tu nhien xuat hien, xem log khi chay.
# ---------------------------------------------------------------------------
manhattan_idx = np.where(sub_project_key_arr == VILLA_PROJECT)[0][:2]
planned_sold_valid[manhattan_idx] = False
LEGAL_BARRIER_UNIT_KEYS = unit_key_arr[manhattan_idx].tolist()
print("LEGAL_PERMIT_BARRIER unit_key cay tay:", LEGAL_BARRIER_UNIT_KEYS)

# ---------------------------------------------------------------------------
# 10. fact_unit_inventory_snapshot + fact_unit_price_history - VECTORIZED,
# tuan tu qua 6 ky (path-dependent vi gia giam tich luy), moi ky vector hoa.
# ---------------------------------------------------------------------------
cur_ppm2 = ppm2_arr.copy()
cur_discount = discount_pct0_arr.copy()
release_year_arr = release_date_arr.year.values
launch_batch_arr = np.array([f"BATCH-{pk}-{y}" for pk, y in zip(sub_project_key_arr, release_year_arr)])
release_date_str_arr = release_date_arr.strftime("%Y-%m-%d").values

inv_frames = []
price_hist_frames = []
price_event_seq_start = 1

for sd in SNAPSHOT_DATES:
    sd_ts = pd.Timestamp(sd)
    sd_ord = sd_ts.toordinal()
    valid_mask = release_ord_arr <= sd_ord
    dom_arr = (sd_ord - release_ord_arr)

    is_sold = planned_sold_valid & (planned_sold_ord_arr <= sd_ord)
    is_booked = planned_sold_valid & (~is_sold) & ((planned_sold_ord_arr - sd_ord) <= 30)
    status_arr = np.where(is_sold, "SOLD", np.where(is_booked, "BOOKED", "AVAILABLE"))
    not_sold_mask = ~is_sold
    overdue_mask = valid_mask & not_sold_mask & (dom_arr > OVERDUE_THRESHOLD_DAYS)

    cut_roll = rng.random(N) < 0.18
    do_cut = overdue_mask & cut_roll
    cut_pct_arr = rng.uniform(0.02, 0.06, N)
    old_price_arr = np.round(cur_ppm2 * net_area_arr * 1_000_000)
    cur_ppm2 = np.where(do_cut, cur_ppm2 * (1 - cut_pct_arr), cur_ppm2)
    new_price_arr = np.round(cur_ppm2 * net_area_arr * 1_000_000)
    cap_arr = np.where(is_selling_arr, 23.8, 12.0)
    cur_discount = np.where(do_cut, np.minimum(cap_arr, cur_discount + rng.uniform(1, 3, N)), cur_discount)

    if do_cut.any():
        idxs = np.where(do_cut)[0]
        pe_ids = np.arange(price_event_seq_start, price_event_seq_start + len(idxs))
        price_event_seq_start += len(idxs)
        price_hist_frames.append(pd.DataFrame({
            "price_event_id": pe_ids, "unit_key": unit_key_arr[idxs],
            "effective_date_key": date_key(sd),
            "old_asking_price_vnd": old_price_arr[idxs].astype(np.int64),
            "new_asking_price_vnd": new_price_arr[idxs].astype(np.int64),
            "price_change_pct": np.round(-cut_pct_arr[idxs] * 100, 2),
            "change_reason": "STIMULATE_SLOW_MOVING",
        }))

    asking_price_arr = np.round(cur_ppm2 * net_area_arr * 1_000_000 / 1e5) * 1e5
    discount_pct_arr = np.round(cur_discount, 2)
    concession_arr = np.where(discount_pct_arr < 3,
                               np.round(asking_price_arr * rng.uniform(0, 0.01, N)),
                               np.round(asking_price_arr * rng.uniform(0.005, 0.02, N)))
    net_price_arr = np.round(asking_price_arr * (1 - discount_pct_arr / 100) - concession_arr)
    net_price_arr = np.minimum(net_price_arr, asking_price_arr)
    subsidy_arr = np.where(is_selling_arr, 18, 0)
    grace_arr = np.where(is_selling_arr, 12, 0)
    spiff_roll = (dom_arr > OVERDUE_THRESHOLD_DAYS) & not_sold_mask & (~low_incentive_arr) & (rng.random(N) < 0.2)
    spiff_arr = np.where(spiff_roll, rng.choice(np.array([50_000_000, 70_000_000, 100_000_000]), size=N), np.nan)
    lock_arr = (tier_arr == "TIER_1_EXCLUSIVE") & (dom_arr > OVERDUE_THRESHOLD_DAYS) & (rng.random(N) < 0.4)
    sold_date_arr = np.where(is_sold, release_date_str_arr, "")  # cap o duoi bang planned date thuc te
    # sold_date thuc: ngay planned_sold (khong phai release) - tinh rieng:
    planned_sold_date_str = np.array([date.fromordinal(int(o)).isoformat() for o in planned_sold_ord_arr])
    sold_date_arr = np.where(is_sold, planned_sold_date_str, "")

    df_period = pd.DataFrame({
        "snapshot_date_key": date_key(sd), "unit_key": unit_key_arr, "project_key": project_key_arr,
        "zone_key": zone_key_arr, "channel_key": channel_key_arr, "launch_batch_id": launch_batch_arr,
        "release_date": release_date_str_arr, "inventory_status": status_arr, "sold_date": sold_date_arr,
        "unsold_days_dom": dom_arr, "is_overdue_flag": (status_arr == "AVAILABLE") & (dom_arr > OVERDUE_THRESHOLD_DAYS),
        "asking_price_vnd": asking_price_arr.astype(np.int64), "discount_pct": discount_pct_arr,
        "concession_value_vnd": concession_arr.astype(np.int64), "net_price_vnd": net_price_arr.astype(np.int64),
        "asking_price_per_m2": np.round(asking_price_arr / net_area_arr).astype(np.int64),
        "net_price_per_m2": np.round(net_price_arr / net_area_arr).astype(np.int64),
        "subsidy_duration_mo": subsidy_arr, "principal_grace_mo": grace_arr,
        "base_commission_pct": base_commission_arr, "spiff_bonus_vnd": spiff_arr,
        "is_exclusive_lock": lock_arr,
    })[valid_mask]
    inv_frames.append(df_period)
    print(f"  ky {sd}: {len(df_period):,} dong (status: {pd.Series(status_arr[valid_mask]).value_counts().to_dict()})")

fact_inv = pd.concat(inv_frames, ignore_index=True)
write_csv_df("09_fact_unit_inventory_snapshot.csv", fact_inv)
fact_price_hist = pd.concat(price_hist_frames, ignore_index=True) if price_hist_frames else pd.DataFrame(
    columns=["price_event_id","unit_key","effective_date_key","old_asking_price_vnd","new_asking_price_vnd","price_change_pct","change_reason"])
write_csv_df("11_fact_unit_price_history.csv", fact_price_hist)
print("Da xong: inventory_snapshot, price_history")

# ---------------------------------------------------------------------------
# 11. fact_sales_funnel_daily - VECTORIZED (khong con dam bao ngay khong trung
# lap trong 1 can nhu ban dau tien - danh doi chap nhan duoc de vector hoa,
# xem README)
# ---------------------------------------------------------------------------
DIM_DATE_START_ORD = pd.Timestamp(DIM_DATE_START).toordinal()
start_ord_arr = np.maximum(release_ord_arr, DIM_DATE_START_ORD)
# Can da ban thi phau tuong tac chi keo dai den dung ngay ban (planned_sold_ord),
# KHONG tiep tuc den 2026-09-29 - sua loi khien touchpoint "roi ra ngoai" khi gan attribution.
funnel_end_ord_arr = np.where(planned_sold_valid, planned_sold_ord_arr, today_ord)
span_days_arr = np.maximum(0, funnel_end_ord_arr - start_ord_arr)

high_dropoff_arr = (~low_incentive_arr) & (rng.random(N) < 0.15)
n_events_arr = np.where(low_incentive_arr, rng.integers(2, 11, N),
                np.where(high_dropoff_arr, rng.integers(15, 31, N), rng.integers(6, 23, N)))
n_events_arr = np.minimum(n_events_arr, span_days_arr + 1)  # khong vuot qua so ngay co the
n_events_arr = np.maximum(n_events_arr, 0)

total_funnel_rows = int(n_events_arr.sum())
print(f"Tong so dong funnel se sinh: {total_funnel_rows:,}")

f_unit_key = np.repeat(unit_key_arr, n_events_arr)
f_start_ord = np.repeat(start_ord_arr, n_events_arr)
f_span = np.repeat(span_days_arr, n_events_arr)
f_low_inc = np.repeat(low_incentive_arr, n_events_arr)
f_high_drop = np.repeat(high_dropoff_arr, n_events_arr)
M = len(f_unit_key)

f_offset = (rng.random(M) * (f_span + 1)).astype(int)
f_offset = np.minimum(f_offset, f_span)
f_date_ord = f_start_ord + f_offset
f_date_key = np.array([int(date.fromordinal(int(o)).strftime("%Y%m%d")) for o in f_date_ord])

f_views = np.where(f_low_inc, rng.integers(1, 9, M),
           np.where(f_high_drop, rng.integers(20, 61, M), rng.integers(5, 31, M)))
f_leads = np.where(f_low_inc, rng.integers(0, 2, M),
           np.where(f_high_drop, rng.integers(2, 7, M), rng.integers(0, 4, M)))
f_visits = np.where(f_low_inc, rng.integers(0, 2, M),
            np.where(f_high_drop, rng.integers(1, 5, M), rng.integers(0, 3, M)))
f_book_p = np.where(f_low_inc, 0.05, np.where(f_high_drop, 0.35, 0.15))
f_bookings = (rng.random(M) < f_book_p).astype(int)
f_cancel_p = np.where(f_low_inc, 0.03, np.where(f_high_drop, 0.55, 0.10))
f_cancels = np.where(f_bookings == 0, (rng.random(M) < f_cancel_p).astype(int), 0)
CANCEL_REASONS = np.array(["PRICE_TOO_HIGH", "DEFECT_FOUND", "LOAN_REJECTED"])
f_reason = np.where(f_cancels == 1, rng.choice(CANCEL_REASONS, size=M), "")

fact_funnel = pd.DataFrame({
    "funnel_event_id": np.arange(1, M + 1), "date_key": f_date_key, "unit_key": f_unit_key,
    "web_listing_views": f_views, "inquiry_leads_count": f_leads, "site_visits_count": f_visits,
    "booking_reservations": f_bookings, "booking_cancellations": f_cancels, "cancellation_reason": f_reason,
})
write_csv_df("10_fact_sales_funnel_daily.csv", fact_funnel)
print("Da xong: sales_funnel_daily")

# ---------------------------------------------------------------------------
# 16. bridge_unit_channel_history (BANG MOI - Bridge table, NGOAI schema v3 goc)
# Grain: 1 dong / 1 giai doan can duoc 1 san phan phoi phu trach lien tuc.
# Da so can giu nguyen 1 san tu luc mo ban den gio (1 dong); ~10% can bi doi
# san giua chung (mo phong "sang tay" moi gioi) -> 2 dong.
# ---------------------------------------------------------------------------
reassign_mask = rng.random(N) < 0.10
end_ord_arr = np.where(planned_sold_valid, planned_sold_ord_arr, today_ord)
span_to_end = np.maximum(1, end_ord_arr - release_ord_arr)
switch_offset = (rng.uniform(0.2, 0.8, N) * span_to_end).astype(int)
switch_ord_arr = release_ord_arr + switch_offset
# channel_key KHONG con la so nguyen lien tiep 1..n_ch (da re-key ve dai
# 3001-3099 theo warehouse/id_registry.json) - phai anh xa qua VI TRI trong
# CHANNEL_KEYS thay vi lam toan tu module truc tiep tren gia tri channel_key
# (bug da phat hien: cong thuc cu gia dinh channel_key=1..n_ch, sinh ra gia tri
# ngoai dai 3001-3005 -> vo hieu FK cho bridge_unit_channel_history/
# fact_funnel_attribution).
n_ch = len(CHANNEL_KEYS)
CHANNEL_KEY_ARR_NP = np.array(CHANNEL_KEYS)
channel_idx_arr = np.searchsorted(CHANNEL_KEY_ARR_NP, channel_key_arr)
other_idx_arr = (channel_idx_arr + rng.integers(1, n_ch, N)) % n_ch
other_channel_arr = CHANNEL_KEY_ARR_NP[other_idx_arr]

def ord2str(o):
    return date.fromordinal(int(o)).isoformat()

bridge_rows_single = []
bridge_rows_multi = []
single_idx = np.where(~reassign_mask)[0]
multi_idx = np.where(reassign_mask)[0]

bridge_single = pd.DataFrame({
    "unit_key": unit_key_arr[single_idx],
    "channel_key": channel_key_arr[single_idx],
    "valid_from_date_key": [int(ord2str(o).replace("-", "")) for o in release_ord_arr[single_idx]],
    "valid_to_date_key": np.nan,
    "is_current": True,
    "assignment_type": np.where(tier_arr[single_idx] == "TIER_1_EXCLUSIVE", "EXCLUSIVE", "CO_LISTING"),
})
bridge_multi_1 = pd.DataFrame({
    "unit_key": unit_key_arr[multi_idx],
    "channel_key": channel_key_arr[multi_idx],
    "valid_from_date_key": [int(ord2str(o).replace("-", "")) for o in release_ord_arr[multi_idx]],
    "valid_to_date_key": [int(ord2str(o).replace("-", "")) for o in switch_ord_arr[multi_idx]],
    "is_current": False,
    "assignment_type": np.where(tier_arr[multi_idx] == "TIER_1_EXCLUSIVE", "EXCLUSIVE", "CO_LISTING"),
})
bridge_multi_2 = pd.DataFrame({
    "unit_key": unit_key_arr[multi_idx],
    "channel_key": other_channel_arr[multi_idx],
    "valid_from_date_key": [int(ord2str(o + 1).replace("-", "")) for o in switch_ord_arr[multi_idx]],
    "valid_to_date_key": np.nan,
    "is_current": True,
    "assignment_type": "EXCLUSIVE",
})
bridge_df = pd.concat([bridge_single, bridge_multi_1, bridge_multi_2], ignore_index=True)
bridge_df = bridge_df.sort_values(["unit_key", "valid_from_date_key"]).reset_index(drop=True)
bridge_df.insert(0, "bridge_id", np.arange(1, len(bridge_df) + 1))
write_csv_df("16_bridge_unit_channel_history.csv", bridge_df)
print(f"Da xong: bridge_unit_channel_history ({reassign_mask.sum():,} can bi doi san / {N:,})")

# ---------------------------------------------------------------------------
# 17. fact_funnel_attribution (BANG MOI - Attribution table, NGOAI schema v3 goc)
# Mo hinh LINEAR: voi moi can da chuyen doi (SOLD truoc/tai 2026-09-29), lay
# toan bo touchpoint phau (fact_sales_funnel_daily) truoc ngay ban, chia deu
# trong so 1/so_touchpoint; xac dinh channel_key tai thoi diem touchpoint qua
# bang bridge_unit_channel_history (16).
# ---------------------------------------------------------------------------
outcome_date_key_arr = np.array([int(ord2str(o).replace("-", "")) for o in planned_sold_ord_arr])
outcome_df = pd.DataFrame({"unit_key": unit_key_arr, "converted": planned_sold_valid,
                            "outcome_date_key": outcome_date_key_arr})

touch = fact_funnel.merge(outcome_df[outcome_df.converted][["unit_key", "outcome_date_key"]],
                           on="unit_key", how="inner")
touch = touch[touch.date_key <= touch.outcome_date_key]

bridge_small = bridge_df[["unit_key", "channel_key", "valid_from_date_key", "valid_to_date_key"]]
touch2 = touch.merge(bridge_small, on="unit_key", how="left")
mask = (touch2.date_key >= touch2.valid_from_date_key) & \
       (touch2.valid_to_date_key.isna() | (touch2.date_key <= touch2.valid_to_date_key))
touch2 = touch2[mask].drop_duplicates(subset=["funnel_event_id"]).copy()

touch2["attribution_weight"] = 1.0 / touch2.groupby("unit_key")["funnel_event_id"].transform("count")
touch2["attribution_weight"] = touch2["attribution_weight"].round(4)
touch2["attribution_model"] = "LINEAR"
touch2["outcome_type"] = "SOLD"
touch2 = touch2.sort_values(["unit_key", "date_key"]).reset_index(drop=True)
attribution_df = pd.DataFrame({
    "attribution_id": np.arange(1, len(touch2) + 1),
    "funnel_event_id": touch2["funnel_event_id"],
    "unit_key": touch2["unit_key"],
    "channel_key": touch2["channel_key"],
    "touchpoint_date_key": touch2["date_key"],
    "attribution_model": touch2["attribution_model"],
    "attribution_weight": touch2["attribution_weight"],
    "outcome_type": touch2["outcome_type"],
    "outcome_date_key": touch2["outcome_date_key"],
})
write_csv_df("17_fact_funnel_attribution.csv", attribution_df)
print(f"Da xong: fact_funnel_attribution ({len(attribution_df):,} touchpoint da gan attribution)")

# ---------------------------------------------------------------------------
# 12. dim_secondary_market_comps (CAO khoang gia that, xem README)
# ---------------------------------------------------------------------------
REAL_RESALE_BAND = {1: (42.0, 55.0), 2: (55.0, 68.0), 3: (58.0, 72.0), 4: (53.2, 77.7),
                     5: (60.0, 80.0), 6: (70.0, 90.0)}
PINK_BOOK_CHOICES = np.array(["PINK_BOOK_AVAILABLE", "SPA_ASSIGNMENT"])
comp_rows = []
comp_id_seq = 1
N_COMPS_PER_PROJECT = 60   # tang nhe so luong comp de tuong xung quy mo moi
for pk, pinfo in SUB_PROJECT_INFO.items():
    sub_pid, sub_pname = pinfo[1], pinfo[2]
    lo, hi = REAL_RESALE_BAND[pk]
    utypes = rng.choice(np.array(["1PN", "2PN", "3PN"]), size=N_COMPS_PER_PROJECT, p=[0.35, 0.45, 0.20])
    fbands = rng.choice(np.array(["LOW", "MID", "HIGH", "TOP"]), size=N_COMPS_PER_PROJECT)
    balconies = rng.choice(ORIENTATIONS, size=N_COMPS_PER_PROJECT)
    resale_offsets = rng.integers(0, 181, N_COMPS_PER_PROJECT)
    ppm2s = np.round(rng.uniform(lo, hi, N_COMPS_PER_PROJECT) * 1_000_000).astype(np.int64)
    pinks = rng.choice(PINK_BOOK_CHOICES, size=N_COMPS_PER_PROJECT, p=[0.8, 0.2])
    for i in range(N_COMPS_PER_PROJECT):
        rdate = TODAY - timedelta(days=int(resale_offsets[i]))
        # project_id gio la "PRJ-VGP" hang so (FK dung voi dim_project_profile 1
        # dong) - sub_project_id/sub_project_name (MOI, mo rong) giu phan biet
        # phan khu nhu truoc (dung cho int_secondary_stats/Q21 benchmark).
        comp_rows.append([f"COMP-{comp_id_seq:05d}", VGP_PROJECT_ID, sub_pid, sub_pname,
                           utypes[i], fbands[i], balconies[i],
                           rdate.isoformat(), int(ppm2s[i]), pinks[i]])
        comp_id_seq += 1
dim_comps = pd.DataFrame(comp_rows, columns=["comp_id", "project_id", "sub_project_id", "sub_project_name",
    "unit_type", "floor_band", "balcony_orientation", "recorded_resale_date",
    "resale_price_per_m2_vnd", "pink_book_status"])
write_csv_df("12_dim_secondary_market_comps.csv", dim_comps)

# ---------------------------------------------------------------------------
# 13. fact_market_macro_monthly (CAO lai suat/thu nhap, xem README)
# ---------------------------------------------------------------------------
REAL_AVG_FLOATING_RATE = 10.5
REAL_MEDIAN_HOUSEHOLD_INCOME_2026 = 330_000_000
macro_rows = []
macro_id = 1
months = []
y, m = 2025, 1
while (y, m) <= (2026, 9):
    months.append((y, m)); m += 1
    if m == 13: m = 1; y += 1
for month_idx, (y, m) in enumerate(months, start=1):
    last_day = 31 if m == 12 else (d(y, m + 1, 1) - timedelta(days=1)).day
    dt = d(y, m, last_day)
    rate = round(REAL_AVG_FLOATING_RATE + np.sin(month_idx / 5) * 0.6 + rng.uniform(-0.15, 0.15), 2)
    absorption = round(max(8.0, 34.0 - (rate - REAL_AVG_FLOATING_RATE) * 6.0 + rng.uniform(-2, 2)), 2)
    moi = round(max(2.0, 18.0 - absorption * 0.3 + rng.uniform(-1, 1)), 1)
    income = round(REAL_MEDIAN_HOUSEHOLD_INCOME_2026 * (1 + 0.005 * month_idx))
    typical_total_price = 60_000_000 * 65
    pir = round(typical_total_price / income, 1)
    macro_rows.append([f"MACRO-{macro_id:05d}", date_key(dt), "MKT-THUDUC-VGP", "MID_HIGH",
                        rate, moi, absorption, income, pir])
    macro_id += 1
fact_macro = pd.DataFrame(macro_rows, columns=["macro_record_id", "date_key", "market_id", "segment",
    "floating_mortgage_rate_pct", "months_of_inventory_moi", "absorption_rate_pct",
    "median_household_income_vnd", "macro_price_to_income_ratio"])
write_csv_df("13_fact_market_macro_monthly.csv", fact_macro)
LATEST_INCOME = int(fact_macro.iloc[-1]["median_household_income_vnd"])
print("Da xong: secondary_market_comps, market_macro_monthly")

# ---------------------------------------------------------------------------
# 14. fact_sales_channel_performance (tong hop tu fact_inv - vector hoa)
# ---------------------------------------------------------------------------
sold_mask_series = fact_inv["inventory_status"] == "SOLD"
grp = fact_inv.groupby(["snapshot_date_key", "channel_key", "project_key"])
perf = grp.agg(assigned_units_count=("unit_key", "count"),
                sold_units_count=("inventory_status", lambda s: (s == "SOLD").sum())).reset_index()
# avg_days_to_sell (docx: "So ngay ban trung binh cua 1 can") la sold_date - release_date
# (thoi gian THUC BAN DUOC), KHAC voi unsold_days_dom = snapshot_date - release_date
# (DOM luy ke theo tung ky, van tiep tuc tang ca sau khi da ban - dung theo dinh nghia
# rieng cua no o docx). Bug da phat hien: ban truoc day tai dung nham unsold_days_dom
# lam avg_days_to_sell, khien so ngay ban trung binh bi thoi phong toi hang nghin ngay.
sold_release_dt = pd.to_datetime(fact_inv.loc[sold_mask_series, "release_date"])
sold_actual_dt = pd.to_datetime(fact_inv.loc[sold_mask_series, "sold_date"])
days_to_sell_series = (sold_actual_dt - sold_release_dt).dt.days
dom_sold = (fact_inv[sold_mask_series].assign(days_to_sell=days_to_sell_series)
            .groupby(["snapshot_date_key", "channel_key", "project_key"])["days_to_sell"]
            .mean().round().rename("avg_days_to_sell"))
perf = perf.merge(dom_sold, on=["snapshot_date_key", "channel_key", "project_key"], how="left")
locked = fact_inv[(fact_inv["is_exclusive_lock"]) & (fact_inv["inventory_status"] != "SOLD") &
                   (fact_inv["unsold_days_dom"] > OVERDUE_THRESHOLD_DAYS)].groupby(
    ["snapshot_date_key", "channel_key", "project_key"]).size().rename("locked_inventory_over_90d")
perf = perf.merge(locked, on=["snapshot_date_key", "channel_key", "project_key"], how="left")
perf["locked_inventory_over_90d"] = perf["locked_inventory_over_90d"].fillna(0).astype(int)
perf["absorption_rate_pct"] = np.round(100.0 * perf["sold_units_count"] / perf["assigned_units_count"], 2)
perf = perf[["snapshot_date_key", "channel_key", "project_key", "assigned_units_count", "sold_units_count",
             "absorption_rate_pct", "avg_days_to_sell", "locked_inventory_over_90d"]]
write_csv_df("14_fact_sales_channel_performance.csv", perf)
print("Da xong: sales_channel_performance")

# ---------------------------------------------------------------------------
# 15. dm_unit_friction_diagnostics - TINH CHO CA 6 KY SNAPSHOT (sua loi "chi
# tinh ky 09-29"), vector hoa toan bo bang pandas groupby (Peer Group don gian
# hoa 2 tang: project+type+floor_band -> project+type, xem README).
# ---------------------------------------------------------------------------
um = dim_unit_master.set_index("unit_key")
# unit_key -> sub_project_key (1-6, phan khu that): dung de nhom peer group/tra
# cuu permit-bank ĐÚNG theo phan khu, vi dim_unit_master.project_key gio la hang
# so 300 (khong con phan biet phan khu duoc nua - xem khoi "5."/"8." o tren).
unit_to_subproject = pd.Series(sub_project_key_arr, index=unit_key_arr)
pinfo_df = pd.DataFrame(SUB_PROJECTS, columns=["sub_project_key","project_id","project_name","segment",
    "construction_status","progress","is_permit","is_bank","handover","band","nzones"]).set_index("sub_project_key")
zone_name_map = pd.Series({r[0]: r[3] for r in zone_rows})

def orientation_group(s):
    return np.select([s.isin(list(COOL_ORIENT)), s.isin(list(HOT_ORIENT))], ["COOL", "HOT"], default="NEUTRAL")

def defect_penalty_vec(u):
    pts = np.zeros(len(u))
    pts += np.where(u["distance_to_trash_room_m"] < DEFECT_TRASH_ROOM_HARD_M, 30,
             np.where(u["distance_to_trash_room_m"] < DEFECT_TRASH_ROOM_SOFT_M, 15, 0))
    pts += np.where(u["is_adjacent_elevator"], 25, 0)
    pts += np.minimum(40, u["dark_bedroom_count"] * DEFECT_DARK_BEDROOM_POINTS_PER)
    pts += np.where(u["efficiency_ratio"] < DEFECT_EFFICIENCY_HARD, 20,
             np.where(u["efficiency_ratio"] < DEFECT_EFFICIENCY_SOFT, 10, 0))
    return np.minimum(100, pts)

def thermal_penalty_vec(u):
    pts = np.zeros(len(u))
    is_hot_o = u["balcony_orientation"].isin(list(HOT_ORIENT))
    pts += np.where(is_hot_o & (u["west_facing_exposure_pct"] >= THERMAL_WEST_EXPOSURE_HARD_PCT), 40,
             np.where(is_hot_o & (u["west_facing_exposure_pct"] >= THERMAL_WEST_EXPOSURE_SOFT_PCT), 20, 0))
    pts += np.where((u["view_primary_type"] == "OBSTRUCTED") | (u["view_obstruction_distance_m"] < THERMAL_OBSTRUCTION_HARD_M), 25, 0)
    pts += np.where((u["taboo_view_type"] != "NONE") | (u["is_taboo_floor"]), 30, 0)
    return np.minimum(100, pts)

sec_med = dim_comps.groupby(["sub_project_id", "unit_type"])["resale_price_per_m2_vnd"].median()
# "gan day" tinh tu ky ACTIVE (06-30), khong phai ky moi nap gan nhat (09-29) -
# phai khop voi int_secondary_stats.sql ben dbt de 2 pipeline cho ket qua giong nhau.
sec_recent_flag = (dim_comps.assign(rdate=pd.to_datetime(dim_comps["recorded_resale_date"]))
                    .assign(recent=lambda x: (ACTIVE_SNAPSHOT_TS - x["rdate"]).dt.days <= 90)
                    .groupby(["sub_project_id", "unit_type"])["recent"].any())

fb = fact_funnel.groupby("unit_key").agg(book=("booking_reservations", "sum"),
                                          cancel=("booking_cancellations", "sum"))
fb["tot"] = fb["book"] + fb["cancel"]
fb["dropoff"] = np.where(fb["tot"] >= 3, np.round(100 * fb["cancel"] / fb["tot"], 2), np.nan)

CAUSE_ACTION = {
    "LEGAL_PERMIT_BARRIER": "EXPEDITE_LEGAL_PROCEDURES: Tam dung ban hang dai tra; hoan thien thu tuc So Xay dung va thu cam ket bao lanh ban giao.",
    "SEVERE_PHYSICAL_DEFECT": "DEFECT_COMPENSATION_DISCOUNT: Thiet lap chinh sach giam gia chao truc tiep 5%-8% de bu tru loi cong nang.",
    "EXTREME_THERMAL_EXPOSURE": "INSULATION_INTERIOR_PACKAGE: Tang goi thi cong noi that cach nhiet, dan kinh Low-E va mien 3 nam phi quan ly.",
    "SECONDARY_ARBITRAGE": "EXTENDED_PAYMENT_SCHEDULE: Gian tien do thanh toan, tang voucher de keo gia rong ve can bang.",
    "LUMP_SUM_TICKET_BARRIER": "BANK_SUBSIDY_EXTENSION: Tang thoi han ho tro lai suat 0% tu 18 len 36 thang va keo dai an han no goc.",
    "OVERPRICED_VS_PEER": "TARGETED_PRICE_CORRECTION: Dieu chinh don gia niem yet ve muc trung vi cua nhom tuong dong.",
    "LOW_SALES_INCENTIVE": "BOOST_BROKER_COMMISSION: Nang ty le hoa hong len 3.0% va kich hoat thuong nong 50-100 trieu VND.",
    "DEEP_FUNNEL_DROP_OFF": "SALES_PITCH_AUDIT: Thanh tra quy trinh tu van cua san moi gioi, ra soat cam ket tien do va phuong thuc giai ngan.",
    "MULTI_FACTOR_UNCLASSIFIED": "MANUAL_REVIEW: Khong khop du kien kich hoat ro rang trong ma tran 8 nguyen nhan; can chuyen gia ra soat thu cong.",
}

diag_frames = []
for sd in SNAPSHOT_DATES:
    sdk = date_key(sd)
    period = fact_inv[fact_inv["snapshot_date_key"] == sdk].copy()
    period = period.join(um[["unit_code","unit_type","floor_band","distance_to_trash_room_m",
        "is_adjacent_elevator","dark_bedroom_count","efficiency_ratio","balcony_orientation",
        "west_facing_exposure_pct","view_primary_type","view_obstruction_distance_m",
        "taboo_view_type","is_taboo_floor","net_area_m2"]], on="unit_key")
    period["sub_project_key"] = period["unit_key"].map(unit_to_subproject)

    grp1 = period.groupby(["sub_project_key","unit_type","floor_band"])["asking_price_per_m2"]
    cnt1 = grp1.transform("count")
    med1 = grp1.transform("median")
    grp2 = period.groupby(["sub_project_key","unit_type"])["asking_price_per_m2"]
    med2 = grp2.transform("median")
    peer_med = np.where(cnt1 >= PEER_MIN_SAMPLE_SIZE, med1, med2)
    period["price_spread_vs_peer_pct"] = np.round(((period["asking_price_per_m2"] - peer_med) / peer_med) * 100, 2)

    cand = period[(period["inventory_status"] == "AVAILABLE") & (period["unsold_days_dom"] > OVERDUE_THRESHOLD_DAYS)].copy()
    if len(cand) == 0:
        continue

    cand["pir"] = np.round(cand["asking_price_vnd"] / LATEST_INCOME, 1)
    cand["dpen"] = defect_penalty_vec(cand)
    cand["tpen"] = thermal_penalty_vec(cand)
    pinfo_j = pinfo_df.loc[cand["sub_project_key"], ["project_id","project_name","is_permit","is_bank"]].reset_index(drop=True)
    cand = cand.reset_index(drop=True)
    cand["sub_project_id"] = pinfo_j["project_id"].values
    cand["project_name_full"] = pinfo_j["project_name"].values
    cand["is_permit"] = pinfo_j["is_permit"].values
    cand["is_bank"] = pinfo_j["is_bank"].values
    cand["zone_name"] = zone_name_map.loc[cand["zone_key"]].values

    sec_key = list(zip(cand["sub_project_id"], cand["unit_type"]))
    cand["sec_med"] = [sec_med.get(k, np.nan) for k in sec_key]
    cand["sec_recent"] = [bool(sec_recent_flag.get(k, False)) for k in sec_key]
    cand["secondary_price_gap_pct"] = np.round(((cand["asking_price_per_m2"] - cand["sec_med"]) / cand["sec_med"]) * 100, 2)

    fb_j = fb.reindex(cand["unit_key"])["dropoff"].values
    cand["funnel_dropoff_rate_pct"] = fb_j

    price_spread = cand["price_spread_vs_peer_pct"]
    conditions = [
        (~cand["is_permit"]) | (~cand["is_bank"]),
        (cand["dpen"] >= 25) & price_spread.ge(0).fillna(False),
        (cand["tpen"] >= 40) & (cand["subsidy_duration_mo"] < 24),
        (cand["secondary_price_gap_pct"] >= SECONDARY_GAP_TRIGGER_PCT) & cand["sec_recent"],
        (cand["pir"] >= PIR_TRIGGER_RATIO) & price_spread.abs().lt(10).fillna(False),
        (price_spread >= PEER_OVERPRICE_TRIGGER_PCT) & (cand["dpen"] < 25) & (cand["tpen"] < 25),
        (cand["base_commission_pct"] <= LOW_COMMISSION_THRESHOLD_PCT) & (cand["spiff_bonus_vnd"].isna()),
        (cand["funnel_dropoff_rate_pct"] >= FUNNEL_DROPOFF_TRIGGER_PCT),
    ]
    choices = ["LEGAL_PERMIT_BARRIER","SEVERE_PHYSICAL_DEFECT","EXTREME_THERMAL_EXPOSURE",
               "SECONDARY_ARBITRAGE","LUMP_SUM_TICKET_BARRIER","OVERPRICED_VS_PEER",
               "LOW_SALES_INCENTIVE","DEEP_FUNNEL_DROP_OFF"]
    cand["primary_cause_code"] = np.select(conditions, choices, default="MULTI_FACTOR_UNCLASSIFIED")
    cand["recommended_action"] = cand["primary_cause_code"].map(CAUSE_ACTION)
    cand["diagnostic_id"] = "DIAG-" + sd.strftime("%Y%m%d") + "-" + cand["unit_code"]

    diag_frames.append(cand[["diagnostic_id","snapshot_date_key","unit_key","unit_code","project_name_full",
        "zone_name","unsold_days_dom","price_spread_vs_peer_pct","pir","dpen","tpen",
        "secondary_price_gap_pct","funnel_dropoff_rate_pct","primary_cause_code","recommended_action"]].rename(
        columns={"project_name_full":"project_name","pir":"ticket_size_vs_income_ratio",
                 "dpen":"physical_defect_penalty","tpen":"thermal_view_penalty"}))
    print(f"  ky {sd}: {len(cand):,} can chan doan qua han")

dm_diag = pd.concat(diag_frames, ignore_index=True)
write_csv_df("15_dm_unit_friction_diagnostics.csv", dm_diag)
print("Da xong: dm_unit_friction_diagnostics (ca 6 ky)")
print(dm_diag["primary_cause_code"].value_counts())
print("HOAN TAT.")
