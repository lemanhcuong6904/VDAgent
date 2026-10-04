Phân tích căn A12-08 @ SNAP-2026-09-28 / sc-1 (một phần — xem hạn chế bên dưới).
- net_asking_price_per_m2: 72.500.000 VND/m² so với trung vị 64.500.000 VND/m² của 5 căn tương đồng (chênh 12,40%) [art_2272e7dec8ac]
- dom: 138 ngày so với trung vị 61 ngày của 5 căn tương đồng (chênh 126,23%) [art_2272e7dec8ac]
- Nhóm tương đồng theo luật hiện hành của Compare: 5 căn (A12-11, A10-02, A14-03, B09-05, B11-07) [art_ef306632d8aa]. Tập 7 căn golden chưa có luật được duyệt (B-11).
- OVERPRICED_VS_PEER: Căn A12-08 đã tồn 138 ngày; giá cao hơn trung vị peer +12,4% và có khả năng liên quan đến giá cao hơn nhóm tương đồng. [art_251d6dbabb86]
- Chưa thể đánh giá đầy đủ thời hạn trợ giá do dữ liệu bị thiếu và khả năng thiếu không ngẫu nhiên. [art_251d6dbabb86]
- Biểu đồ: art_766549769743, art_4bad717beafd, art_5294e998218f, art_e28af1064a22, art_efd20f8310b7
- Báo cáo đã lưu: art_075de220626e

| Bước | Agent | Trạng thái | Artifact |
|---|---|---|---|
| B1 | data.fetch_units | hoàn tất | art_cf5ab027dd7e, art_a17af8f783ba, art_4faf90a9bc48 |
| B2 | insight.explain_unit | hoàn tất | art_251d6dbabb86 |
| B3 | compare.compare_to_peers | hoàn tất | art_ef306632d8aa, art_2272e7dec8ac |
| B4 | chart.draw_chart | hoàn tất | art_766549769743, art_4bad717beafd, art_5294e998218f, art_e28af1064a22, art_efd20f8310b7 |
| B5 | report.draft_report | hoàn tất | art_075de220626e |

Hạn chế: BLOCKED:B-2_min_peer_count, BLOCKED:D2b_segment_mapping, CONFIG_PENDING:min_group_size, DQ_MISSING:asking_price_vnd:12, FIELD_UNAVAILABLE:asking_price_per_m2, METRIC_UNAVAILABLE:discount_pct, METRIC_UNAVAILABLE:subsidy_duration_mo, SYNTHETIC_SOURCE:net_area_m2, WINDOW_INCOMPLETE:inquiry_leads_30d:3

run_state: art_1ff49f493238 · plan pl_78389e8c5081
