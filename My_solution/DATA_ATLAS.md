# Data atlas: những gì toàn bộ file đang nói

Phần này quét toàn bộ 8 cột gốc của `data.csv`, kể cả những câu hỏi ngoài đề. [Code tái chạy](data_atlas.py), [summary JSON](outputs/data_atlas/summary.json), [field profile](outputs/data_atlas/field_profile.csv) và [anomaly register](outputs/data_atlas/anomaly_register.csv) chứa kết quả kiểm tra. “Bất thường” nghĩa là **cần giải thích nguồn**, chưa tự động là giao dịch sai.

## 1. Hình dạng và độ sạch bề mặt

File có **204.694 transaction**, **18.000 user**, từ **01/01/2024 đến 30/06/2025** — **18 tháng**, trong khi đề mô tả 6 tháng. Cả 8 cột không có null. `transaction_id` không trùng; có một cặp dòng giống nhau ở mọi trường khác ID. `trxn_amount` đều là bội 1.000 VND; `total_limit` là bội 100.000 VND, có 95 mức từ 0,5 đến 9,9 triệu VND. Việc làm tròn mệnh giá tự nó không phải vấn đề.

## 2. Dấu vết của cách tạo hoặc xuất dữ liệu

| Dấu hiệu | Đã đo | Vì sao đáng hỏi |
|---|---|---|
| ID rất có cấu trúc | User ID phủ kín `100000`–`117999`; transaction ID phủ kín `1`–`204694`. Trong **204.590** giao dịch đầu theo ID, user ID đi lên liên tục và mỗi user chiếm một block. **104** giao dịch cuối quay lại user cũ. | ID nhiều khả năng phản ánh thứ tự tạo/export theo user, không thể mặc định là dấu thời gian giao dịch. 104 dòng có thể là backfill hoặc batch chèn thêm. |
| New users giảm cực đều | Fit tuyến tính trên log số người mua lần đầu theo 18 tháng cho khoảng **−4,8%/tháng**, `R² = 0,975`. | Rất giống một cơ chế sinh hoặc lấy mẫu theo xu hướng; muốn gọi là acquisition thật phải đối chiếu dashboard nguồn. Fit chỉ mô tả, không phải bằng chứng nhân quả. |
| Không có reactivation | 0 user quay lại sau một tháng không mua trong toàn bộ extract. | Có thể do eligibility/khóa tài khoản, ETL chỉ giữ streak đầu, hoặc dữ liệu mô phỏng. Không kết luận user “biến mất vĩnh viễn”. |
| Lịch giao dịch rất phẳng | Chỉ số giao dịch ngày trong tuần nằm trong **0,986–1,008** lần mức bình quân. Median hệ số biến thiên ngày trong từng tháng là **5,02%**, gần mức Poisson với cùng volume (**5,03%**). | Chưa thấy nhịp cuối tuần/lễ hoặc nhiều biến động ngày ngoài nhiễu đếm. Không nên dùng file này để thiết kế lịch campaign theo ngày. [Bảng ngày](outputs/data_atlas/daily_regularity_by_month.csv), [thứ trong tuần](outputs/data_atlas/weekday_index.csv). |
| M0 lại dồn đầu tháng | **25,4%** first purchases ở ngày 1–3; chỉ **9,8%** toàn bộ transactions ở ngày 1–3. | Có thể có đợt mời/duyệt đầu tháng hoặc quy tắc tạo data; hỏi lịch onboarding trước khi suy ra nhu cầu tự nhiên. |
| Limit cố định | Không user nào thay đổi `total_limit` qua 18 tháng. | Có thể đây là snapshot của một thuộc tính tĩnh, không phải lịch sử limit thực tế; không dùng dữ liệu này để suy luận tác động tăng limit. |

Các dấu hiệu **gộp lại** khiến tôi coi đây là một extract có quy tắc tạo/lọc mạnh, có thể là dữ liệu thử nghiệm hoặc mô phỏng. Không thể chứng minh “synthetic” chỉ từ file. Nếu là dữ liệu sản phẩm thật đã được sample, cần tài liệu sampling và ETL trước khi ngoại suy kết quả ra toàn bộ ZaloPay.

## 3. Package và carrier: giá trị nằm ở volume, chưa thấy ngành hàng bứt phá

Có **7 package** và **22 nhãn carrier** (21 nếu chuẩn hóa `Other services`/`Other Services`). Có 38 cặp package–carrier trong file; **5 dòng** thuộc các cặp xuất hiện dưới 10 lần và cả 5 đều nằm trong 104 giao dịch cuối dải ID. [Bảng cặp đầy đủ](outputs/data_atlas/package_carrier_pairs.csv). Cần mapping chính thức trước khi gọi cặp hiếm là sai.

`Channel Partner` chiếm khoảng **35% GMV**, `Digital Services` khoảng **26%**, nhưng tỷ trọng package theo tháng chỉ dao động tối đa **3,1 điểm %** ở package biến động nhiều nhất. [Mix theo tháng](outputs/data_atlas/package_mix_by_month.csv). Ticket bình quân của các package nằm trong **168–171 nghìn VND** ([bảng](outputs/data_atlas/package_ticket.csv)). Trong [phân tích mở rộng](NEW_ANGLES.md), carrier đầu tiên cũng không cho thấy khác biệt M1 rõ ở kiểm định chung. Vì thế package lớn là nơi đang có nhiều GMV, **không tự động là nơi có tiềm năng tăng trưởng vượt trội**.

## 4. `total_outstanding`: không nên đọc như lịch sử nợ chắc chắn

- **35,1%** user có `total_outstanding` ở giao dịch đầu thấp hơn chính `trxn_amount` của giao dịch đó.
- **2.645** giao dịch ghi số dư bằng hạn mức. Trong **1.589** giao dịch, số dư ghi ở giao dịch trước cũng đã bằng hạn mức, nhưng giao dịch tiếp theo vẫn tồn tại và số dư vẫn bằng hạn mức.
- Không giao dịch nào có `total_outstanding > total_limit`; median số dư/hạn mức ở giao dịch cuối của một user-month là **6,8%**; chỉ **2,1%** user-month kết thúc tại ≥80% limit.

Có nhiều cách giải thích: balance chụp trước/sau giao dịch, giới hạn hiển thị, hoàn tiền, thanh toán xen giữa hoặc độ trễ cập nhật. File thiếu timestamp balance, khoản trả nợ và trạng thái tài khoản. Vì vậy không suy ra nợ quá hạn, lỗ tín dụng hay “hết hạn mức” từ những dòng này. Đặc biệt, một chiến dịch tăng hạn mức dựa trên `total_outstanding` sẽ có rủi ro chọn nhầm đối tượng.

## 5. Bonus nên đưa vào bài nộp, thật ngắn

> **Data provenance is the biggest unasked finding.** The file has 18 months instead of six, exactly 18,000 contiguous user IDs, a highly regular decline in first purchasers, no reactivation, static limits and 104 appended transactions that change the apparent “four purchases” threshold. Treat business projections and the threshold as provisional until the extract and transaction provenance are confirmed.

Chi tiết ở atlas phục vụ người chấm muốn kiểm toán; trong phần Bonus của bài nộp chỉ nên dùng đoạn ngắn trên.
