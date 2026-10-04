Phân tích căn A12-08 @ SNAP-2026-09-28 / sc-1 (một phần — xem hạn chế bên dưới).
- net_asking_price_per_m2: 72.500.000 VND/m² so với trung vị 64.500.000 VND/m² của 5 căn tương đồng (chênh 12,40%) [art_0e8789905240]
- dom: 138 ngày so với trung vị 61 ngày của 5 căn tương đồng (chênh 126,23%) [art_0e8789905240]
- Nhóm tương đồng theo luật hiện hành của Compare: 5 căn (A12-11, A10-02, A14-03, B09-05, B11-07) [art_14d4710b4385]. Tập 7 căn golden chưa có luật được duyệt (B-11).
- OVERPRICED_VS_PEER: Căn A12-08 tồn 138 ngày; yếu tố có khả năng liên quan: giá cao hơn nhóm tương đồng (đơn giá/m² so với trung vị peer +12,4%). [art_fb76304c2a3a]
- Dữ liệu cho subsidy_duration_mo còn hạn chế: trường dữ liệu thiếu quá nhiều nên không được sử dụng; dữ liệu thiếu không ngẫu nhiên giữa căn quá hạn và căn đã bán. [art_fb76304c2a3a]
- Biểu đồ: art_0795a8bc8c06, art_9499f21a574a, art_cdbf8ba717cb, art_00c5d2e9244e, art_8c0f21340596
- Báo cáo đã lưu: art_c99f3356cea9

| Bước | Agent | Trạng thái | Artifact |
|---|---|---|---|
| B1 | data.fetch_units | hoàn tất | art_5b5ff1edc970, art_8db5d3360d25, art_ee8c885aa4b1 |
| B2 | insight.explain_unit | hoàn tất | art_fb76304c2a3a |
| B3 | compare.compare_to_peers | hoàn tất | art_14d4710b4385, art_0e8789905240 |
| B4 | chart.draw_chart | hoàn tất | art_0795a8bc8c06, art_9499f21a574a, art_cdbf8ba717cb, art_00c5d2e9244e, art_8c0f21340596 |
| B5 | report.draft_report | hoàn tất | art_c99f3356cea9 |

Hạn chế: BLOCKED:B-2_min_peer_count, BLOCKED:D2b_segment_mapping, CONFIG_PENDING:min_group_size, DQ_MISSING:asking_price_vnd:12, FIELD_UNAVAILABLE:asking_price_per_m2, METRIC_UNAVAILABLE:discount_pct, METRIC_UNAVAILABLE:subsidy_duration_mo, SYNTHETIC_SOURCE:net_area_m2, WINDOW_INCOMPLETE:inquiry_leads_30d:3

run_state: art_0234a87ca360 · plan pl_405f4c414f0b