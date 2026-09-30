# -*- coding: utf-8 -*-
"""Sinh bo cau hoi-SQL chuan (gold standard) tu du lieu VGP mock da sinh,
chay that tung cau SQL bang DuckDB de lay ket qua dung, tranh viec tu bia ket qua."""
import csv
import duckdb
import os
import json

# Tu suy tu vi tri file script nay (data/) - KHONG hardcode duong dan tuyet doi,
# de ca project di chuyen duoc sang may/thu muc khac ma khong phai sua.
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

TABLE_FILES = {
    "snapshot_manifest": "01_snapshot_manifest.csv",
    "semantic_config": "02_semantic_config.csv",
    "dim_date": "03_dim_date.csv",
    "dim_project_profile": "04_dim_project_profile.csv",
    "dim_zone_master": "05_dim_zone_master.csv",
    "dim_unit_master": "06_dim_unit_master.csv",
    "dim_sales_channel": "07_dim_sales_channel.csv",
    "dim_infrastructure_assets": "08_dim_infrastructure_assets.csv",
    "fact_unit_inventory_snapshot": "09_fact_unit_inventory_snapshot.csv",
    "fact_sales_funnel_daily": "10_fact_sales_funnel_daily.csv",
    "fact_unit_price_history": "11_fact_unit_price_history.csv",
    "dim_secondary_market_comps": "12_dim_secondary_market_comps.csv",
    "fact_market_macro_monthly": "13_fact_market_macro_monthly.csv",
    "fact_sales_channel_performance": "14_fact_sales_channel_performance.csv",
    "dm_unit_friction_diagnostics": "15_dm_unit_friction_diagnostics.csv",
    "bridge_unit_channel_history": "16_bridge_unit_channel_history.csv",
    "fact_funnel_attribution": "17_fact_funnel_attribution.csv",
}

con = duckdb.connect()
for tbl, fname in TABLE_FILES.items():
    path = os.path.join(DATA_DIR, fname).replace("\\", "/")
    con.execute(f"CREATE VIEW {tbl} AS SELECT * FROM read_csv_auto('{path}', header=true)")

# Gan them warehouse THAT do dbt build ra (khong doc lai CSV) de test truc tiep
# tren artifact dbt - dung cho cac cau hoi ve model consolidation moi
# (mart_channel_attribution_performance). Can chay `dbt build` truoc trong
# dbt_vgp/ de file nay ton tai; neu chua co, cac cau hoi lien quan se bao LOI
# ro rang thay vi tu bia ket qua.
DBT_DB_PATH = os.path.join(DATA_DIR, "..", "dbt_vgp", "vgp.duckdb").replace("\\", "/")
DBT_ATTACHED = False
if os.path.exists(DBT_DB_PATH):
    con.execute(f"ATTACH '{DBT_DB_PATH}' AS dbtdb (READ_ONLY)")
    con.execute("CREATE VIEW mart_channel_attribution_performance AS "
                "SELECT * FROM dbtdb.main_marts.mart_channel_attribution_performance")
    DBT_ATTACHED = True
    print(f"Da gan dbt warehouse: {DBT_DB_PATH}")
else:
    print(f"CANH BAO: khong tim thay {DBT_DB_PATH} - can chay 'dbt build' truoc. "
          "Cac cau hoi dung mart_channel_attribution_performance se bao LOI.")

QUESTIONS = [
    dict(id=1, difficulty="EASY", tables="dim_project_profile + dim_zone_master", hop=1,
         question="Kho dữ liệu VGP đăng ký bao nhiêu dự án (project_key) theo hợp đồng khóa trung tâm, và có bao nhiêu phân khu (sub-project) bên trong?",
         sql="""SELECT
                    (SELECT COUNT(*) FROM dim_project_profile) AS so_du_an,
                    (SELECT COUNT(DISTINCT sub_project_id) FROM dim_zone_master) AS so_phan_khu"""),
    dict(id=2, difficulty="EASY", tables="dim_zone_master", hop=1,
         question="Liệt kê tên các phân khu đã bàn giao (construction_status = 'HANDED_OVER'), sắp xếp theo tên. (LƯU Ý: construction_status nay o cap dim_zone_master, KHONG con o dim_project_profile - xem câu #1).",
         sql="SELECT DISTINCT sub_project_name FROM dim_zone_master WHERE construction_status='HANDED_OVER' ORDER BY sub_project_name"),
    dict(id=3, difficulty="EASY", tables="dim_unit_master", hop=1,
         question="Căn hộ nào có diện tích thông thủy (net_area_m2) lớn nhất, diện tích bao nhiêu?",
         sql="SELECT unit_code, net_area_m2 FROM dim_unit_master ORDER BY net_area_m2 DESC LIMIT 1"),
    dict(id=4, difficulty="EASY", tables="semantic_config", hop=1,
         question="Ngưỡng số ngày tồn kho để một căn bị coi là 'quá hạn bán' (overdue) là bao nhiêu ngày?",
         sql="SELECT config_value FROM semantic_config WHERE config_key='overdue_threshold_days'"),
    dict(id=5, difficulty="EASY", tables="snapshot_manifest", hop=1,
         question="Kỳ MỚI NẠP gần nhất trong bộ dữ liệu là ngày nào, mã snapshot_id là gì? (LƯU Ý: đây là kỳ mới nạp, KHÔNG phải kỳ active dùng để báo cáo - xem câu #32).",
         sql="SELECT snapshot_id, snapshot_date FROM snapshot_manifest ORDER BY snapshot_date DESC LIMIT 1"),
    dict(id=6, difficulty="MEDIUM", tables="fact_unit_inventory_snapshot + dim_zone_master + snapshot_manifest", hop=3,
         question="Tại kỳ ACTIVE (2026-06-30), phân khu The Opus One còn bao nhiêu căn ở trạng thái AVAILABLE? (LƯU Ý: join qua zone_key/dim_zone_master, KHONG qua project_key nua vi project_key gio la 1 hang duy nhat cho ca VGP).",
         sql="""SELECT COUNT(*) AS so_can_available
                FROM fact_unit_inventory_snapshot f
                JOIN dim_zone_master z ON f.zone_key = z.zone_key
                WHERE f.snapshot_date_key = (SELECT CAST(REPLACE(CAST(snapshot_date AS VARCHAR),'-','') AS INTEGER)
                                              FROM snapshot_manifest WHERE is_active)
                  AND f.inventory_status = 'AVAILABLE'
                  AND z.sub_project_name LIKE 'The Opus One%'"""),
    dict(id=7, difficulty="MEDIUM", tables="fact_unit_inventory_snapshot + dim_unit_master + snapshot_manifest", hop=3,
         question="Căn hộ nào đang tồn kho lâu nhất (DOM cao nhất) tại kỳ ACTIVE? Cho biết mã căn và số ngày tồn.",
         sql="""SELECT u.unit_code, f.unsold_days_dom
                FROM fact_unit_inventory_snapshot f
                JOIN dim_unit_master u ON f.unit_key = u.unit_key
                WHERE f.snapshot_date_key = (SELECT CAST(REPLACE(CAST(snapshot_date AS VARCHAR),'-','') AS INTEGER)
                                              FROM snapshot_manifest WHERE is_active)
                  AND f.inventory_status = 'AVAILABLE'
                ORDER BY f.unsold_days_dom DESC LIMIT 1"""),
    dict(id=8, difficulty="MEDIUM", tables="fact_unit_inventory_snapshot + dim_zone_master + snapshot_manifest", hop=3,
         question="Tính tỷ lệ hấp thụ (% căn SOLD trên tổng số căn) của từng phân khu tại kỳ ACTIVE.",
         sql="""SELECT z.sub_project_name,
                       ROUND(100.0 * SUM(CASE WHEN f.inventory_status='SOLD' THEN 1 ELSE 0 END) / COUNT(*), 2) AS absorption_rate_pct
                FROM fact_unit_inventory_snapshot f
                JOIN dim_zone_master z ON f.zone_key = z.zone_key
                WHERE f.snapshot_date_key = (SELECT CAST(REPLACE(CAST(snapshot_date AS VARCHAR),'-','') AS INTEGER)
                                              FROM snapshot_manifest WHERE is_active)
                GROUP BY z.sub_project_name ORDER BY absorption_rate_pct"""),
    dict(id=9, difficulty="HARD", tables="dm_unit_friction_diagnostics", hop=1,
         question="Đếm số lượng căn được chẩn đoán theo từng mã nguyên nhân cốt lõi (primary_cause_code), sắp xếp giảm dần.",
         sql="""SELECT primary_cause_code, COUNT(*) AS so_can
                FROM dm_unit_friction_diagnostics
                GROUP BY primary_cause_code ORDER BY so_can DESC"""),
    dict(id=10, difficulty="HARD", tables="dm_unit_friction_diagnostics", hop=1,
         question="Liệt kê mã căn và tên phân khu của các căn được chẩn đoán nguyên nhân LEGAL_PERMIT_BARRIER.",
         sql="""SELECT unit_code, project_name FROM dm_unit_friction_diagnostics
                WHERE primary_cause_code = 'LEGAL_PERMIT_BARRIER'"""),
    dict(id=11, difficulty="HARD", tables="dm_unit_friction_diagnostics + dim_unit_master + dim_zone_master", hop=3,
         question="Với các căn chẩn đoán LEGAL_PERMIT_BARRIER, phân khu tương ứng có is_bank_guarantee_issued là gì? (LƯU Ý: is_bank_guarantee_issued nay o cap dim_zone_master - dm_unit_friction_diagnostics khong co zone_key truc tiep nen can di qua dim_unit_master).",
         sql="""SELECT DISTINCT d.project_name, z.is_bank_guarantee_issued
                FROM dm_unit_friction_diagnostics d
                JOIN dim_unit_master u ON d.unit_key = u.unit_key
                JOIN dim_zone_master z ON u.zone_key = z.zone_key
                WHERE d.primary_cause_code = 'LEGAL_PERMIT_BARRIER'"""),
    dict(id=12, difficulty="HARD", tables="dm_unit_friction_diagnostics", hop=1,
         question="Căn hộ nào có điểm phạt khuyết tật vật lý (physical_defect_penalty) cao nhất, và khuyến nghị hành động là gì?",
         sql="""SELECT unit_code, physical_defect_penalty, recommended_action
                FROM dm_unit_friction_diagnostics
                ORDER BY physical_defect_penalty DESC LIMIT 1"""),
    dict(id=13, difficulty="HARD", tables="fact_market_macro_monthly + dim_date", hop=2,
         question="Lãi suất vay thả nổi trung bình theo từng quý của năm 2026 là bao nhiêu?",
         sql="""SELECT d.year, d.quarter, ROUND(AVG(m.floating_mortgage_rate_pct), 2) AS avg_rate
                FROM fact_market_macro_monthly m
                JOIN dim_date d ON m.date_key = d.date_key
                WHERE d.year = 2026
                GROUP BY d.year, d.quarter ORDER BY d.quarter"""),
    dict(id=14, difficulty="MEDIUM", tables="fact_market_macro_monthly", hop=1,
         question="Tỷ lệ hấp thụ thị trường (absorption_rate_pct) ở tháng gần nhất là bao nhiêu, và thay đổi bao nhiêu điểm % so với tháng liền trước?",
         sql="""SELECT date_key, absorption_rate_pct,
                       absorption_rate_pct - LAG(absorption_rate_pct) OVER (ORDER BY date_key) AS thay_doi
                FROM fact_market_macro_monthly ORDER BY date_key DESC LIMIT 1"""),
    dict(id=15, difficulty="HARD", tables="fact_sales_channel_performance + dim_sales_channel + snapshot_manifest", hop=3,
         question="Tại kỳ ACTIVE, sàn phân phối nào đang khóa giữ (locked_inventory_over_90d) nhiều căn tồn >90 ngày nhất?",
         sql="""SELECT c.channel_name, SUM(p.locked_inventory_over_90d) AS tong_can_bi_khoa
                FROM fact_sales_channel_performance p
                JOIN dim_sales_channel c ON p.channel_key = c.channel_key
                WHERE p.snapshot_date_key = (SELECT CAST(REPLACE(CAST(snapshot_date AS VARCHAR),'-','') AS INTEGER)
                                              FROM snapshot_manifest WHERE is_active)
                GROUP BY c.channel_name ORDER BY tong_can_bi_khoa DESC LIMIT 1"""),
    dict(id=16, difficulty="HARD", tables="fact_unit_price_history + dim_unit_master", hop=2,
         question="Căn hộ nào đã bị điều chỉnh giảm giá (price_change_pct âm) nhiều lần nhất?",
         sql="""SELECT u.unit_code, COUNT(*) AS so_lan_giam_gia
                FROM fact_unit_price_history h
                JOIN dim_unit_master u ON h.unit_key = u.unit_key
                WHERE h.price_change_pct < 0
                GROUP BY u.unit_code ORDER BY so_lan_giam_gia DESC LIMIT 1"""),
    dict(id=17, difficulty="HARD", tables="fact_sales_funnel_daily + dim_unit_master", hop=2,
         question="Căn hộ nào có tổng số lượt rút cọc (booking_cancellations) cao nhất trong toàn bộ lịch sử phễu?",
         sql="""SELECT u.unit_code, SUM(f.booking_cancellations) AS tong_rut_coc
                FROM fact_sales_funnel_daily f
                JOIN dim_unit_master u ON f.unit_key = u.unit_key
                GROUP BY u.unit_code ORDER BY tong_rut_coc DESC LIMIT 1"""),
    dict(id=18, difficulty="MEDIUM", tables="dim_infrastructure_assets", hop=1,
         question="Công trình hạ tầng nào đang UNDER_CONSTRUCTION có tiến độ thi công (%) cao nhất?",
         sql="""SELECT infra_name, construction_progress_pct FROM dim_infrastructure_assets
                WHERE lifecycle_stage='UNDER_CONSTRUCTION' ORDER BY construction_progress_pct DESC LIMIT 1"""),
    dict(id=19, difficulty="MEDIUM", tables="fact_unit_inventory_snapshot + dim_zone_master + snapshot_manifest", hop=3,
         question="Đơn giá chào bán trung bình (asking_price_per_m2) tại kỳ ACTIVE của nhóm segment MID_HIGH so với MID là bao nhiêu? (LƯU Ý: segment nay o cap dim_zone_master, KHONG con o dim_project_profile).",
         sql="""SELECT z.segment, ROUND(AVG(f.asking_price_per_m2)) AS gia_binh_quan_m2
                FROM fact_unit_inventory_snapshot f
                JOIN dim_zone_master z ON f.zone_key = z.zone_key
                WHERE f.snapshot_date_key = (SELECT CAST(REPLACE(CAST(snapshot_date AS VARCHAR),'-','') AS INTEGER)
                                              FROM snapshot_manifest WHERE is_active)
                GROUP BY z.segment ORDER BY z.segment"""),
    dict(id=20, difficulty="MEDIUM", tables="dim_zone_master", hop=1,
         question="Tòa cao tầng (HIGH_RISE_TOWER) nào có tỷ số căn/thang máy (elevator_ratio) cao nhất?",
         sql="""SELECT zone_name, elevator_ratio FROM dim_zone_master
                WHERE zone_type='HIGH_RISE_TOWER' ORDER BY elevator_ratio DESC LIMIT 1"""),
    dict(id=21, difficulty="HARD", tables="dim_secondary_market_comps", hop=1,
         question="Đơn giá bán lại thứ cấp trung vị (resale_price_per_m2_vnd) của loại căn 2PN tại Glory Heights là bao nhiêu? (LƯU Ý: project_id nay la hang so 'PRJ-VGP' cho ca VGP - dung sub_project_name/sub_project_id de phan biet phan khu, khong can JOIN dim_project_profile nua).",
         sql="""SELECT MEDIAN(c.resale_price_per_m2_vnd) AS gia_trung_vi_thu_cap
                FROM dim_secondary_market_comps c
                WHERE c.sub_project_name LIKE 'Glory Heights%' AND c.unit_type = '2PN'"""),
    dict(id=22, difficulty="MEDIUM", tables="fact_unit_inventory_snapshot + snapshot_manifest", hop=2,
         question="Tổng giá trị tồn kho sơ cấp (tổng asking_price_vnd của các căn AVAILABLE) tại kỳ ACTIVE là bao nhiêu VND?",
         sql="""SELECT SUM(asking_price_vnd) AS tong_gia_tri_ton_kho
                FROM fact_unit_inventory_snapshot
                WHERE snapshot_date_key = (SELECT CAST(REPLACE(CAST(snapshot_date AS VARCHAR),'-','') AS INTEGER)
                                            FROM snapshot_manifest WHERE is_active)
                  AND inventory_status = 'AVAILABLE'"""),
    dict(id=23, difficulty="HARD", tables="dm_unit_friction_diagnostics", hop=1,
         question="Với căn được chẩn đoán SECONDARY_ARBITRAGE, cho biết tên tòa và tên phân khu của căn đó.",
         sql="""SELECT d.unit_code, d.zone_name, d.project_name
                FROM dm_unit_friction_diagnostics d
                WHERE d.primary_cause_code = 'SECONDARY_ARBITRAGE'"""),
    dict(id=24, difficulty="MEDIUM", tables="dim_sales_channel + fact_unit_inventory_snapshot + snapshot_manifest", hop=3,
         question="Sàn phân phối nào (channel_tier = 'TIER_1_EXCLUSIVE') đang được giao quản lý nhiều căn nhất tại kỳ ACTIVE?",
         sql="""SELECT c.channel_name, COUNT(*) AS so_can
                FROM fact_unit_inventory_snapshot f
                JOIN dim_sales_channel c ON f.channel_key = c.channel_key
                WHERE f.snapshot_date_key = (SELECT CAST(REPLACE(CAST(snapshot_date AS VARCHAR),'-','') AS INTEGER)
                                              FROM snapshot_manifest WHERE is_active)
                  AND c.channel_tier = 'TIER_1_EXCLUSIVE'
                GROUP BY c.channel_name ORDER BY so_can DESC LIMIT 1"""),
    dict(id=25, difficulty="MEDIUM", tables="bridge_unit_channel_history + dim_sales_channel", hop=2,
         question="Có bao nhiêu căn đã từng bị đổi sàn phân phối (có 2 giai đoạn phụ trách trở lên) trong lịch sử?",
         sql="""SELECT COUNT(*) AS so_can_doi_san FROM (
                    SELECT unit_key FROM bridge_unit_channel_history
                    GROUP BY unit_key HAVING COUNT(*) > 1
                )"""),
    dict(id=26, difficulty="HARD", tables="bridge_unit_channel_history + dim_unit_master", hop=2,
         question="Liệt kê 5 căn có nhiều giai đoạn đổi sàn phân phối nhất (số dòng bridge nhiều nhất).",
         sql="""SELECT u.unit_code, COUNT(*) AS so_giai_doan
                FROM bridge_unit_channel_history b
                JOIN dim_unit_master u ON b.unit_key = u.unit_key
                GROUP BY u.unit_code ORDER BY so_giai_doan DESC LIMIT 5"""),
    dict(id=27, difficulty="HARD", tables="fact_funnel_attribution + dim_sales_channel", hop=2,
         question="Theo mô hình attribution LINEAR, tổng trọng số đóng góp (attribution_weight) vào các giao dịch đã bán quy về từng sàn phân phối là bao nhiêu? Sắp xếp giảm dần.",
         sql="""SELECT c.channel_name, ROUND(SUM(a.attribution_weight), 1) AS tong_trong_so_dong_gop
                FROM fact_funnel_attribution a
                JOIN dim_sales_channel c ON a.channel_key = c.channel_key
                GROUP BY c.channel_name ORDER BY tong_trong_so_dong_gop DESC"""),
    dict(id=28, difficulty="HARD", tables="fact_funnel_attribution + fact_sales_funnel_daily + dim_unit_master", hop=3,
         question="Căn hộ nào có số touchpoint được gán attribution (đóng góp vào việc bán thành công) nhiều nhất?",
         sql="""SELECT u.unit_code, COUNT(*) AS so_touchpoint_duoc_gan
                FROM fact_funnel_attribution a
                JOIN dim_unit_master u ON a.unit_key = u.unit_key
                GROUP BY u.unit_code ORDER BY so_touchpoint_duoc_gan DESC LIMIT 1"""),
    # --- Cau hoi 29-31: doc TRUC TIEP tu mart consolidation moi do dbt build ra
    # (dbt_vgp/models/marts/mart_channel_attribution_performance.sql), KHONG
    # tinh lai bang SQL rieng - muc dich la kiem chung chinh artifact dbt that.
    dict(id=29, difficulty="MEDIUM", tables="mart_channel_attribution_performance (dbt mart)", hop=1,
         question="[dbt mart] Sàn phân phối nào có tổng trọng số đóng góp attribution (total_attribution_weight) cao nhất?",
         sql="""SELECT channel_name, total_attribution_weight
                FROM mart_channel_attribution_performance
                ORDER BY total_attribution_weight DESC LIMIT 1"""),
    dict(id=30, difficulty="MEDIUM", tables="mart_channel_attribution_performance (dbt mart)", hop=1,
         question="[dbt mart] Tỷ lệ chuyển đổi (conversion_rate_pct) của từng sàn phân phối là bao nhiêu, sắp xếp giảm dần?",
         sql="""SELECT channel_name, channel_tier, conversion_rate_pct
                FROM mart_channel_attribution_performance
                ORDER BY conversion_rate_pct DESC"""),
    dict(id=31, difficulty="HARD", tables="mart_channel_attribution_performance (dbt mart)", hop=1,
         question="[dbt mart] Sàn nào đang giữ độc quyền (exclusive_assignments_count) nhiều căn nhất nhưng lại có tỷ lệ chuyển đổi thấp nhất trong nhóm TIER_1_EXCLUSIVE?",
         sql="""SELECT channel_name, exclusive_assignments_count, conversion_rate_pct
                FROM mart_channel_attribution_performance
                WHERE channel_tier = 'TIER_1_EXCLUSIVE'
                ORDER BY conversion_rate_pct ASC LIMIT 1"""),
    dict(id=32, difficulty="MEDIUM", tables="snapshot_manifest", hop=1,
         question="Kỳ nào đang được đánh dấu ACTIVE (chính thức dùng để báo cáo), và có bao nhiêu kỳ đã nạp sau đó nhưng chưa chính thức active?",
         sql="""SELECT
                    (SELECT snapshot_id FROM snapshot_manifest WHERE is_active) AS active_snapshot_id,
                    (SELECT snapshot_date FROM snapshot_manifest WHERE is_active) AS active_snapshot_date,
                    (SELECT COUNT(*) FROM snapshot_manifest
                     WHERE snapshot_date > (SELECT snapshot_date FROM snapshot_manifest WHERE is_active)
                    ) AS so_ky_da_nap_nhung_chua_active"""),
]

rows_out = []
for q in QUESTIONS:
    sql = " ".join(q["sql"].split())
    try:
        res = con.execute(q["sql"]).fetchdf()
        if len(res) > 8:
            result_json = json.dumps(res.head(8).to_dict(orient="records"), ensure_ascii=False, default=str) + f" ...(+{len(res)-8} dong nua)"
        else:
            result_json = json.dumps(res.to_dict(orient="records"), ensure_ascii=False, default=str)
        row_count = len(res)
        status = "OK"
    except Exception as e:
        result_json = str(e)
        row_count = -1
        status = "LOI"
    rows_out.append([q["id"], q["question"], q["difficulty"], q["hop"], q["tables"], sql, status, row_count, result_json])
    print(f"[{q['id']:02d}] {status} ({row_count} dong): {q['question'][:60]}")

out_path = os.path.join(DATA_DIR, "18_benchmark_gold_sql.csv")
with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["question_id", "question_vi", "difficulty", "join_hop_count", "tables_used",
                "sql", "status", "expected_row_count", "expected_result_sample"])
    w.writerows(rows_out)
print(f"\nDa ghi {out_path}")
