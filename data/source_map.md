# Nguồn và provenance — Vinhomes Smart City Data Pack

Mốc POC: 30/06/2026. **Toàn bộ giá, tồn kho, tương tác, trạng thái pháp lý và kết quả chẩn đoán trong CSV hiện là synthetic mock**, không phải dữ liệu giao dịch hoặc CRM của Vinhomes. Các trang công khai dưới đây chỉ dùng để chọn tên tòa, loại căn và bối cảnh quy mô; dữ liệu thực chỉ được đưa vào pipeline khi có quyền truy cập, ngày lấy, URL/ID nguồn và kiểm chứng.

| Bảng | Nguồn cho bản mock hiện tại | Nguồn thực nếu được phép thu thập | Cách kiểm soát |
| --- | --- | --- | --- |
| `snapshot_manifest` | Cấu hình POC | Lịch chốt warehouse | Một `snapshot_id` cho 30/06/2026 |
| `semantic_config` | 12 ngưỡng từ ma trận chẩn đoán | Quy tắc được BA/PO duyệt | Version `3.1.0`, không sinh tham số đệm |
| `dim_date` | Lịch Gregorian 01/01–30/06/2026 | Không cần crawl | `date_key` khớp ngày |
| `dim_project_profile` | Một dự án `PRJ-VHSC`/200; thuộc tính pháp lý cấp dự án là mock | Hồ sơ dự án/chứng thư/công bố pháp lý | Không dùng thuộc tính mock để mô tả tình trạng pháp lý thật của Vinhomes |
| `dim_zone_master` | 6 tên tòa tham khảo từ Vinhomes và 1 phase pháp lý **hư cấu** `MOCK-LGL-01` | Sơ đồ mặt bằng chính thức | Phase hư cấu chỉ để kiểm thử; tất cả 7 zone thuộc project key 200 |
| `dim_unit_master` | 3.000 căn mock, gồm 16 fixture pháp lý hư cấu trong cùng dự án | Mặt bằng tòa, CRM giỏ hàng | `ext_attributes.data_origin=synthetic`; `fictional_phase_fixture` và `phase_sales_permit_issued` chỉ mô tả giả định kiểm thử; `tower_unit_label` giữ mã tòa/căn tham khảo; `unit_code` là `SMC-U` theo registry |
| `dim_sales_channel` | 8 sàn hư cấu | Danh mục kênh phân phối/CRM | ID `MOCK-AGENCY-*` |
| `dim_infrastructure_assets` | 4 tài sản hạ tầng trong kế hoạch POC | Công bố quy hoạch/tiến độ chính thức | Tiến độ trong CSV là mock, không dùng làm thông tin hiện trạng |
| `fact_unit_inventory_snapshot` | 3.000 dòng giá và trạng thái synthetic ở snapshot 30/06/2026 | Giỏ hàng, bảng giá, chính sách bán nội bộ | Grain căn × snapshot; DOM và giá ròng kiểm bằng SQL |
| `fact_sales_funnel_daily` | Sự kiện web/CRM synthetic | Web/app analytics, nhật ký dẫn xem, đặt/rút cọc | Chỉ tạo ngày có tương tác; không giả nhận đã có CRM |
| `fact_unit_price_history` | Sự kiện điều chỉnh giá synthetic | Lịch sử bảng giá nội bộ | Giá mới khớp snapshot |
| `dim_secondary_market_comps` | 96 đối sánh synthetic | Giao dịch thứ cấp **xác thực**; tin rao chỉ là tín hiệu tham khảo | ID `MOCK-COMP-*`; không gọi giá rao là giá giao dịch |
| `fact_market_macro_monthly` | 24 chỉ số synthetic | Báo cáo quý/tháng của tổ chức nghiên cứu | Không sao chép chỉ số công khai vào mock mà thiếu ngày và phạm vi |
| `fact_sales_channel_performance` | Tổng hợp từ giỏ hàng synthetic | CRM, phân bổ giỏ hàng theo sàn | Assigned/sold đối chiếu inventory |
| `dm_unit_friction_diagnostics` | Tính deterministic từ mock | Serving pipeline đã kiểm chứng | Chỉ căn AVAILABLE, DOM > 90 |
| `unit_diagnostic_causes` | Ma trận 8 nguyên nhân và điểm attribution | Ground truth được team AI/BA duyệt | Tổng điểm từng `diagnostic_id` = 1.000; TC-13/15 hiện chỉ là giả định tạm trong `tc_assumptions.json` |

## Tham khảo công khai đã xem

- [Vinhomes: giải mã Sapphire 1](https://vinhomes.vn/vi/giai-ma-phan-khu-s1-vinhomes-smart-city) — tên tòa, loại căn, ví dụ quy mô từng tòa.
- [Vinhomes: các tòa Vinhomes Smart City](https://vinhomes.vn/vi/vinhomes-smart-city-co-bao-nhieu-toa) — tham khảo nhiều phân khu/tòa và loại căn.
- [CBRE: Hanoi Figures Q2 2026](https://www.cbrevietnam.com/insights/figures/hanoi-figures-q2-2026) — ứng viên nguồn thị trường; **chưa** nạp chỉ số vào CSV.

Trước khi crawl một nguồn mới: kiểm tra điều kiện truy cập/sử dụng, lưu URL và thời điểm truy cập, chuẩn hóa đơn vị VND/m² thông thủy và ngày, khử trùng tin đăng, rồi tách trường `observed` khỏi `synthetic`. Nguồn CRM và giao dịch xác thực hiện chưa được cung cấp.
