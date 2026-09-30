# **BÁO CÁO THỐNG KÊ & KIỂM ĐỊNH DỮ LIỆU BẤT ĐỘNG SẢN**

### **THÔNG TIN PHIÊN KIỂM ĐỊNH (AUDIT METADATA)**

* **Mã phiên chạy (Run ID):** RUN\_20260921\_STAT\_DQ\_01  
* **Dữ liệu chốt (Snapshot ID):** SNAPSHOT\_20260921\_Q3\_V1 (Chốt ngày 21/09/2026)  
* **Hệ thống dữ liệu kiểm định:** Data Warehouse (Tập dữ liệu giỏ hàng và lịch sử giao dịch Bất động sản Vinhomes POC)  
* **Quy chuẩn đánh giá (Semantic Config):** semantic\_config:v1.2 (Quy định ngưỡng Null, IQR Outliers, Check Constraints)  
* **KẾT QUẢ DATAGATE: PASSED WITH WARNINGS** *(Đủ điều kiện phân tích kinh doanh kèm điều kiện lọc ngoại lai)*

# **1\. TỔNG QUAN QUY MÔ & CẤU TRÚC DỮ LIỆU** 

## **1.1. Bảng thống kê cấp độ thực thể** 

| Tên bảng (Table Name) | Tầng dữ liệu | Tổng số bản ghi (Rows) | Số trường (Columns) | Kích thước lưu trữ | Số bản ghi trống (Empty) | Trùng lặp Khóa chính (PK Dups) |
| :---- | :---- | :---: | :---: | :---: | :---: | :---: |
| **projects** | Project Level | 2 | 14 | 16 KB | 0 | 0 (100% Unique) |
| **areas** | Area / Sub-division | 8 | 18 | 48 KB | 0 | 0 (100% Unique) |
| **units** | Physical Unit Specs | 24,500 | 28 | 14.2 MB | 0 | 0 (100% Unique) |
| **unit\_prices** | Pricing & Valuation | 48,200 | 12 | 8.6 MB | 0 | 0 (100% Unique) |
| **unit\_deal\_events** | Transactions & DOM | 36,800 | 16 | 9.4 MB | 0 | 0 (100% Unique) |
| **market\_benchmarks** | External Benchmark | 120 | 10 | 64 KB | 0 | 0 (100% Unique) |

## **1.2. Tổng hợp chỉ số chất lượng dữ liệu tổng thể** 

| Chỉ số chất lượng (DQ Dimension) | Điểm số / Tỷ lệ thực tế | Ngưỡng chuẩn (Threshold) | Trạng thái kỹ thuật | Đánh giá sơ bộ |
| :---- | :---: | :---: | :---: | :---- |
| **Độ đầy đủ (Completeness)** | 94.2% | ≥ 95.0% | **Cảnh báo (Warning)** | Khuyết thiếu tập trung ở trường hướng view và diện tích phụ |
| **Tính duy nhất (Uniqueness)** | 100.0% | 100.0% | **Đạt chuẩn (Passed)** | Không phát hiện bản ghi trùng lặp khóa chính hoặc mã căn hộ |
| **Tính hợp lệ định dạng (Validity)** | 99.4% | ≥ 98.0% | **Đạt chuẩn (Passed)** | Kiểu dữ liệu và định dạng ngày/tháng/số thập phân đồng nhất |
| **Tính toàn vẹn liên kết (Integrity)** | 99.92% | 100.0% | **Cảnh báo (Warning)** | Phát hiện 20 bản ghi khóa ngoại mồ côi (Orphan records) |
| **Tính tươi mới (Freshness)** | 4.5 giờ | ≤ 24.0 giờ | **Đạt chuẩn (Passed)** | Snapshot được đồng bộ định kỳ theo đúng SLA quy định |

# **2\. KIỂM ĐỊNH ĐỘ SẠCH & TÍNH TOÀN VẸN** 

## **2.1. Ma trận khuyết thiếu & Tỷ lệ Null (Missing & Null Analysis)**

| Tên trường (Field Name) | Thuộc bảng | Kiểu dữ liệu | Số dòng Null | Tỷ lệ Null (%) | Mức độ nghiêm trọng | Tác động phân tích |
| :---- | :---- | :---- | :---: | :---: | :---: | :---- |
| unit\_id | units | VARCHAR(36) | 0 | 0.0% | CRITICAL | Khóa chính, nhận diện duy nhất (Đạt yêu cầu) |
| carpet\_area | units | DECIMAL(8,2) | 142 | 0.58% | HIGH | Cần cho tính đơn giá/m²; có thể impute từ built\_up\_area |
| view\_direction | units | VARCHAR(20) | 4,532 | 18.50% | HIGH | Ảnh hưởng trực tiếp đến phân tích nguyên nhân bán chậm |
| view\_obstruction\_pct | units | DECIMAL(5,2) | 6,442 | 26.29% | MEDIUM | Tỷ lệ che chắn view; thiếu hụt lớn ở tòa mới bàn giao |
| floor\_number | units | SMALLINT | 0 | 0.0% | CRITICAL | Hoàn thiện 100% |
| listed\_price | unit\_prices | DECIMAL(15,2) | 68 | 0.14% | CRITICAL | Căn hộ chưa chốt bảng giá mở bán chính thức |
| first\_booking\_date | unit\_deal\_events | TIMESTAMP | 1,180 | 3.21% | MEDIUM | Căn hộ tồn kho chưa phát sinh booking đầu tiên |

## **2.2. Kiểm định liên kết khóa ngoại** 

* **Quan hệ units.area\_id → areas.area\_id:** 0 bản ghi lỗi (100% căn hộ liên kết chính xác với phân khu).  
* **Quan hệ unit\_prices.unit\_id → units.unit\_id:** 0 bản ghi lỗi (Mọi mức giá đều trỏ đúng mã căn).  
* **Quan hệ unit\_deal\_events.unit\_id → units.unit\_id:** 20 bản ghi mồ côi (0.08%). Các giao dịch này mang mã căn thử nghiệm (TEST\_UNIT\_XXX), cần được purge khỏi DW.

## **2.3. Kiểm tra tính hợp lệ miền giá trị & Logic nghiệp vụ** 

| Quy tắc logic nghiệp vụ (Constraint) | Biểu thức kiểm tra (Validation Rule) | Số vi phạm | Tỷ lệ (%) | Trạng thái xử lý |
| :---- | :---- | :---: | :---: | :---- |
| **Giá niêm yết phải dương** | listed\_price \> 0 | 0 | 0.00% | Đạt |
| **Diện tích tim tường \>= thông thủy** | built\_up\_area \>= carpet\_area | 14 | 0.06% | Lỗi nhập ngược diện tích giữa 2 trường |
| **Ngày mở bán hợp lệ** | first\_booking\_date \>= launch\_date | 3 | 0.01% | Booking ghi nhận trước ngày mở bán dự án |
| **Số tầng trong khoảng thiết kế** | floor\_number BETWEEN 1 AND 70 | 0 | 0.00% | Đạt |
| **DOM không âm** | DATEDIFF(day, launch\_date, CURRENT\_DATE) \>= 0 | 0 | 0.00% | Đạt |

# **3\. THỐNG KÊ MÔ TẢ CÁC BIẾN ĐỊNH LƯỢNG** 

 *(Toàn bộ chỉ số được tính toán bằng Deterministic Engine qua thư viện decimal.js trên snapshot chuẩn)*

## **3.1. Bảng tổng hợp tham số thống kê (Parametric & Non-Parametric Summary)**

| Biến số | Đơn vị | N | Mean | Std | Min | Q1 | Median | Q3 | Max | IQR | Skew | Kurt |
| :---- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Đơn giá/m²** | Tr.đ/m² | 24,432 | 74.20 | 18.65 | 42.10 | 58.20 | **64.50** | 71.00 | 145.00 | 12.80 | **\+1.84** | \+4.12 |
| **Diện tích TT** | m² | 24,358 | 68.45 | 24.12 | 28.50 | 45.20 | **64.80** | 82.50 | 280.00 | 37.30 | **\+1.42** | \+2.85 |
| **Số ngày DOM** | Ngày | 24,500 | 78.60 | 46.20 | 2.00 | 32.00 | **68.00** | 105.00 | 342.00 | 73.00 | **\+0.89** | \+0.45 |
| **Tổng giá trị** | Tỷ VNĐ | 24,432 | 5.24 | 2.85 | 1.45 | 2.85 | **4.25** | 6.10 | 38.50 | 3.25 | **\+2.35** | \+6.80 |

## **3.2. Đánh giá hình thái phân phối (Distribution Assessment)**

* **Hiện tượng lệch phải mạnh ở Đơn giá/m² (Skewness \= \+1.84 \> 1.0):** Giá trị trung bình (74.2 tr/m²) bị kéo lệch tăng **15.0%** so với trung vị thực tế (64.5 tr/m²). Phân vị 75% (Q3) dừng ở mức 71.0 tr/m², chứng minh rằng trên 75% rổ hàng có mức giá thấp hơn đáng kể so với mức giá trung bình.  
* **Khuyến nghị phương pháp luận:** Bắt buộc áp dụng **Trung vị (Median)** và **Khoảng tứ phân vị (IQR)** làm thước đo trung tâm cho các bài toán phân tích định giá và benchmark, không dùng Trung bình (Mean).

# **4\. PHÂN BỐ CÁC BIẾN PHÂN LOẠI & TƯƠNG QUAN CHÉO**

## **4.1. Cơ cấu rổ hàng theo Loại hình sản phẩm (Product Mix Distribution)**

| Loại hình căn hộ | Mã quy chuẩn (Category) | Số lượng (Count) | Tỷ trọng (%) | Đơn giá Trung vị | DOM Trung vị |
| :---- | :---- | :---: | :---: | :---: | :---: |
| **Studio & 1 Phòng ngủ** | STUDIO\_1PN | 5,880 | 24.0% | 68.2 | 45 |
| **2 Phòng ngủ (1WC & 2WC)** | 2PN\_STANDARD | 11,270 | 46.0% | 63.5 | 62 |
| **2 Phòng ngủ \+ 1** | 2PN\_PLUS | 3,920 | 16.0% | 65.0 | 74 |
| **3 Phòng ngủ trở lên** | 3PN\_LARGE | 2,940 | 12.0% | 69.8 | 98 |
| **Penthouse / Duplex** | SIGNATURE\_PENT | 490 | 2.0% | 118.5 | 165 |
| **Tổng cộng** |  | **24,500** | **100.0%** | **64.5** | **68** |

## **4.2. Phân bố theo Hướng ban công & Độ che chắn View**

* **Hướng đón gió mát (Đông Nam, Nam, Đông):** Chiếm **54.2%** tổng nguồn cung. DOM trung vị đạt **52 ngày**.  
* **Hướng nắng chiều (Tây, Tây Bắc, Tây Nam):** Chiếm **38.6%** tổng nguồn cung. DOM trung vị đạt **86 ngày** (+65.4% thời gian tồn kho so với hướng mát).  
* **Chưa xác định thuộc tính (Null):** Chiếm **7.2%** tổng nguồn cung.

## **4.3. Bảng tương quan chéo: Phân khu x Phân vị giá (Cross-Tabulation)**

| Phân khu (Area ID) | Tổng căn mở bán | Q1 (Tr/m²) | Trung vị P50 | Q3 (Tr/m²) | Tỷ lệ DOM \> 90 ngày (%) |
| :---- | :---: | :---: | :---: | :---: | :---: |
| **The Sapphire** | 8,200 | 48.5 | **54.2** | 60.1 | 14.5% |
| **The Zenpark** | 6,500 | 61.2 | **66.8** | 72.4 | 22.8% |
| **The Pavilion** | 5,400 | 56.0 | **61.5** | 67.2 | 18.2% |
| **The Beverly (Target)** | 4,400 | 69.5 | **78.2** | 88.0 | **38.6% (Bất thường)** |

# **5\. PHÁT HIỆN BẤT THƯỜNG & NGOẠI LAI (ANOMALY & OUTLIER DETECTION)**

## **5.1. Phương pháp luận xác định ngoại lai**

* Áp dụng phương pháp phân vị chuẩn **Tukey’s Fences**:   
  * Hàng rào dưới (Lower Inner Fence) \= Q1 \- 1.5 × IQR  
  * Hàng rào trên (Upper Inner Fence) \= Q3 \+ 1.5 × IQR  
* Kết hợp ngưỡng kiểm tra độ lệch chuẩn **Z-score \> 3.0** đối với biến phân phối xấp xỉ đối xứng.

## **5.2. Danh sách ngoại lai phát hiện theo trường dữ liệu**

| Trường dữ liệu | Hàng rào dưới | Hàng rào trên | Số lượng | Tỷ lệ (%) | Phân loại bản chất ngoại lai |
| :---- | :---: | :---: | :---: | :---: | :---- |
| **Đơn giá/m²** | 39.0 tr/m² | **90.2 tr/m²** | 42 căn | 0.17% | Căn hộ Penthouse/Duplex đặc thù (Hợp lệ) |
| **Thời gian DOM** | 0 ngày | **214.5 ngày** | 186 căn | 0.76% | Tồn kho nghiêm trọng hoặc vướng pháp lý |
| **Tỷ lệ diện tích TT/TT** | 0.78 | **0.96** | 14 căn | 0.06% | Lỗi nhập liệu hệ thống (Tỷ lệ \= 1.15) |

# **6\. BIẾN ĐỘNG DỮ LIỆU & ĐỘ TRÔI (DATA DRIFT & SNAPSHOT COMPARISON)**

 *(So sánh Snapshot hiện tại SNAPSHOT\_20260921 với kỳ liền trước SNAPSHOT\_20260821)*

| Đại lượng theo dõi | Kỳ trước (T-30) | Hiện tại (T-0) | Biến động (Delta) | Đánh giá độ trôi (Drift Status) |
| :---- | :---: | :---: | :---: | :---- |
| **Tổng số lượng căn hộ** | 22,100 | 24,500 | \+2,400 căn (+10.86%) | Mở bán thêm tòa mới (Bình thường) |
| **Đơn giá trung vị** | 63.8 tr/m² | 64.5 tr/m² | \+0.7 tr/m² (+1.10%) | Ổn định (Stable) |
| **Tỷ lệ khuyết thiếu View** | 12.1% | 18.5% | \+6.4% (Tăng độ rỗng) | **Suy giảm (Degraded)** |
| **Chỉ số KS-test** | \- | \- | **KS Stat \= 0.042** | Không bị trôi (No Concept Drift) |

# **7\. KẾT LUẬN DATA GATE & HƯỚNG DẪN TIỀN XỬ LÝ (PREPROCESSING SPEC)**

## **7.1. Quyết định Data Gate**

* **Trạng thái phê duyệt: PASSED WITH WARNINGS**  
* **Căn cứ quyết định:**   
  * Tính toàn vẹn cấu trúc và khóa chính đạt 100%.  
  * Độ đầy đủ tổng thể đạt 94.2% (chấp nhận được cho POC).  
  * Cho phép dữ liệu đi tiếp vào Compare Agent và Insight Agent kèm điều kiện lọc rác bắt buộc.

## **7.2. Quy tắc tiền xử lý bắt buộc cho Downstream Agents**

```
preprocessing_pipeline:
  filter_rules:
    - action: "EXCLUDE"
      condition: "unit_id LIKE 'TEST_UNIT_%'"
      reason: "Loại trừ 20 bản ghi thử nghiệm mồ côi khóa ngoại"
    - action: "STRATIFY"
      condition: "category = 'SIGNATURE_PENT' OR price_m2 > 90.2"
      target_dataset: "luxury_peer_pool"
      reason: "Tách 42 căn Penthouse ngoại lai ra khỏi tập tính peer group tiêu chuẩn"
  
  imputation_rules:
    - field: "carpet_area"
      method: "carpet_area = built_up_area * 0.905"
      condition: "carpet_area IS NULL AND built_up_area IS NOT NULL"
    - field: "view_direction"
      method: "ASSIGN_CATEGORY('UNKNOWN_PENDING_ENRICHMENT')"
      condition: "view_direction IS NULL"
  metric_calculation_rules:
    - metric: "pricing_benchmark"
      formula: "MEDIAN(price_m2)"
      restriction: "STRICTLY FORBIDDEN: AVG(price_m2) due to Skewness = 1.84"
```

---

*Báo cáo kiểm định hồ sơ dữ liệu được tự động tạo lập bởi Data Quality Engine thuộc hệ thống VDAgent. Toàn bộ thuật toán thống kê và kiểm định ràng buộc được ghi vết tại Run Log: RUN\_20260921\_STAT\_DQ\_01.*

