# XGBoost dự báo ngừng giao dịch tháng kế tiếp

## Bài toán và phép đo

Tại **cuối tháng t**, lấy những khách hàng có ít nhất một giao dịch trong tháng t. Nhãn bằng 1 nếu khách hàng **không có giao dịch trong tháng t+1**. Đây là *lapse* một tháng theo hành vi mua, chưa phải trạng thái đóng tài khoản hay churn vĩnh viễn. Tháng 6/2025 chưa có nhãn vì file không chứa tháng 7/2025.

Chia theo thời gian: train 1–10/2024; chọn feature, độ sâu cây và số vòng boosting trên 11–12/2024; fit lại trên 1–12/2024; đánh giá **một lần** trên 1–5/2025 (17.431 user-month). Cùng khách hàng có thể xuất hiện ở nhiều tháng, đúng với bài toán chấm điểm tập khách hàng hiện có. Không dùng `user_id`, `transaction_id`, giao dịch t+1, nhãn tương lai hay target encoding làm feature.

## Feature engineering từ business sense và toán

Script [churn_xgboost_v2.py](churn_xgboost_v2.py) tạo 177 feature ứng viên. Các phép chia cho 0 giữ `NaN`, để XGBoost xử lý như giá trị thiếu; không ép thành số 0 có ý nghĩa sai. Hạn mức và dư nợ được đọc từ dòng giao dịch cuối tháng, với giả định các trường đó phản ánh trạng thái tại ngày giao dịch.

| Nhóm | Câu hỏi kinh doanh | Ví dụ phép tính |
|---|---|---|
| Tần suất và giá trị | Khách mua bao nhiêu, thường mua bao nhiêu? | Số giao dịch, GMV, ticket, số ngày mua, số loại dịch vụ. |
| Lịch sử theo **tháng lịch** | Khách có đều đặn hay vừa quay lại? | `n_txn_lag1/2/3/6`, số tháng hoạt động trong 3/6 tháng, chuỗi tháng hoạt động liên tiếp, số tháng vắng trước lần quay lại. Các tháng không mua được giữ là 0. |
| Chuyển trạng thái | Khách từng ngừng rồi quay lại nhiều lần không? | Số lần lapse/tái hoạt động đã hoàn tất, tỷ lệ lapse trong lịch sử, số tháng từ lần lapse gần nhất. |
| Lệch khỏi chính mình | Mức độ sử dụng hiện tại khác thói quen đến đâu? | `n_t / mean(n trước t)`, `n_t − n_(t−1)`, sai phân bậc hai `n_t − 2n_(t−1) + n_(t−2)`, tỷ lệ giao dịch tháng hiện tại trên tổng 3 tháng. |
| Nhịp mua trong tháng | Mua dồn một ngày hay rải đều? | Số ngày mua, khoảng cách giao dịch, hệ số biến thiên `sd(gap)/mean(gap)`, tỷ trọng giao dịch 7 ngày cuối tháng, ngày từ lần mua cuối đến cutoff. |
| Cơ cấu đơn hàng và merchant | Phụ thuộc một giao dịch lớn hay một loại dịch vụ? | `sum(ticket²)/GMV²` (HHI giá trị), HHI/entropy merchant, tỷ lệ chuyển merchant/package, mức thay đổi concentration. |
| Dư nợ và hạn mức | Người dùng còn room để mua không? | `outstanding/limit`, room còn lại, room/ticket trung bình, thay đổi dư nợ/hạn mức so với tháng hoạt động trước. |
| Tương tác giả thuyết | Tín hiệu có mạnh hơn trong một bối cảnh cụ thể? | Giảm tần suất × chỉ mua 1–2 lần; vừa quay lại × chỉ mua 1 lần; utilization × giảm tần suất; hạn mức còn lại/ticket; concentration × tần suất thấp. |

Đây là các giả thuyết dự báo, **không phải quan hệ nhân quả**. Feature importance theo gain cũng không chứng minh rằng thay đổi một feature sẽ làm giảm churn.

## Thử nghiệm feature và kết quả

Tổng cộng 8 bộ feature × 3 cấu hình XGBoost = 24 ứng viên, chọn hoàn toàn bằng AUC validation. Bảng là cấu hình tốt nhất của từng bộ trên validation, không dùng test để chọn:

| Bộ feature | Số feature | AUC validation |
|---|---:|---:|
| Base | 20 | 0,5538 |
| Base + lịch sử tháng lịch | 71 | 0,5651 |
| Base + lịch sử + chuyển trạng thái | 77 | 0,5649 |
| Base + lịch sử + nhịp mua trong tháng | 107 | 0,5648 |
| **Base + lịch sử + dư nợ/hạn mức** | **90** | **0,5663** |
| Base + lịch sử + dư nợ/hạn mức + chuyển trạng thái | 96 | 0,5653 |
| Tất cả trừ tương tác thủ công | 164 | 0,5613 |
| Tất cả, gồm tương tác | 177 | 0,5636 |

Các tương tác thủ công **không tăng AUC validation** ở lần thử này; cây XGBoost đã có khả năng học nhiều quan hệ phi tuyến từ các feature gốc. Thêm feature indiscriminately có thể làm model học nhiễu. Tập được chọn dùng cây sâu 4, `min_child_weight=20`, `reg_lambda=10`, 26 vòng boosting sau early stopping.

Trong bộ được chọn, các feature có gain cao nhất chủ yếu là **tần suất mua lịch sử theo tháng hoạt động/tháng lịch**, GMV lịch sử, số giao dịch cao nhất từng tháng và số ngày mua tháng này. Merchant mix và các tương tác thủ công không nằm trong bộ thắng validation. Gain chỉ mô tả cách cây dùng feature trong mẫu huấn luyện, không phải tác động nhân quả.

| Kết quả ngoài thời gian | XGBoost v1 | Feature engineering v2 |
|---|---:|---:|
| AUC test | 0,57157 | **0,57179** |
| Average precision | 0,29645 | 0,29686 |
| Brier score (thấp hơn tốt hơn) | **0,18246** | 0,18255 |
| Tỷ lệ churn thực tế ở 10% rủi ro cao nhất | **33,37%** | 32,63% |
| Tỷ lệ churn nền | 24,41% | 24,41% |

Chênh AUC v2 − v1 chỉ **+0,00022**; bootstrap ghép cặp theo khách hàng cho khoảng tin cậy 95% **[−0,00201; +0,00259]**. Không có bằng chứng đủ mạnh rằng v2 tốt hơn v1 trên giai đoạn test. AUC v2 riêng lẻ có khoảng tin cậy bootstrap theo khách hàng **[0,5612; 0,5813]**. Theo tháng, AUC dao động từ 0,5486 (5/2025) đến 0,5839 (2/2025). Nhóm 20% điểm cao nhất chứa 26,58% người lapse, mức phân tầng còn yếu.

Chạy lại toàn bộ bước chọn model sau khi loại 104 giao dịch cuối ID bị nghi vấn: ứng viên được chọn đổi thành 177 feature và AUC test **0,56490**. Nếu **giữ cố định cấu hình đã chọn trên file nguyên bản** rồi chỉ thay dữ liệu đầu vào, AUC test là **0,56909**. Sự đổi ứng viên khi dữ liệu thay đổi rất ít là dấu hiệu lựa chọn chưa ổn định; cả hai phép kiểm tra vẫn cùng kết luận về sức dự báo yếu. 104 dòng này được giữ trong mô hình chính vì chưa có xác nhận chúng là dữ liệu sai.

**Mục tiêu AUC 0,8 chưa đạt.** Không nên biến nhãn thành “không mua trong chính tháng đang chấm điểm”, dùng giao dịch của tháng t+1, hoặc chọn model theo test để báo AUC cao: các cách đó không trả lời bài toán dự báo tại cuối tháng t. Với 8 cột hiện có, tín hiệu quan sát được chỉ cho phép phân tầng rủi ro khá yếu. Đây là kết quả thực nghiệm, không phải chứng minh toán học rằng 0,8 bất khả thi.

## Hướng tăng chất lượng có khả năng hữu ích hơn

1. **Thêm nguồn dữ liệu có trước cutoff:** ngày đáo hạn và thanh toán, chậm trả/DPD, giao dịch thất bại, app sessions và tìm kiếm, eligibility, thay đổi hạn mức, lịch sử campaign/notification, nguồn acquisition. Ghi rõ thời điểm từng trường xuất hiện để tránh leakage.
2. **Xác nhận nhãn đúng mục đích:** lapse 1 tháng, không mua 60/90 ngày, hoặc đóng tài khoản là ba outcome khác nhau; phải chọn theo quyết định kinh doanh và chấm cùng horizon.
3. **Kiểm tra giá trị kinh doanh bằng pilot:** điểm rủi ro chỉ nên dùng để phân tầng thử nghiệm nhắc mua. So sánh incremental GMV hoặc active rate giữa nhóm được nhắc và holdout ngẫu nhiên; AUC không đo uplift của can thiệp.
4. **Theo dõi drift và calibration:** nếu dùng dữ liệu 2026 để vận hành, cần huấn luyện/kiểm tra lại trên giai đoạn gần hiện tại. Dữ liệu giao chỉ kết thúc 6/2025.

## Tệp để tái lập

```bash
python3 My_solution/churn_xgboost.py
python3 My_solution/churn_xgboost_v2.py
python3 My_solution/churn_xgboost_v2.py --exclude-tail
```

- [validation_search.csv](outputs/churn_xgboost_v2/validation_search.csv): toàn bộ 24 ứng viên; [metrics.json](outputs/churn_xgboost_v2/metrics.json): kết quả chính; [comparison_v1.json](outputs/churn_xgboost_v2/comparison_v1.json): so sánh ghép cặp; [without_tail/metrics.json](outputs/churn_xgboost_v2/without_tail/metrics.json): độ nhạy với 104 dòng.
- [feature_families.json](outputs/churn_xgboost_v2/feature_families.json), [feature_columns.json](outputs/churn_xgboost_v2/feature_columns.json), [feature_importance_gain.csv](outputs/churn_xgboost_v2/feature_importance_gain.csv): định nghĩa và đóng góp dự báo của feature được chọn.
- [test_scores.csv](outputs/churn_xgboost_v2/test_scores.csv), [test_deciles.csv](outputs/churn_xgboost_v2/test_deciles.csv), [test_by_month.csv](outputs/churn_xgboost_v2/test_by_month.csv): audit ngoài thời gian.
- [model_evaluated.json](outputs/churn_xgboost_v2/model_evaluated.json): model đã được test, fit đến 12/2024. [model_all_labeled.json](outputs/churn_xgboost_v2/model_all_labeled.json): refit đến 5/2025 để minh họa chấm [3.022 khách hoạt động trong 6/2025](outputs/churn_xgboost_v2/june_2025_scores.csv). **Không có nhãn tháng 7/2025** để đánh giá bản refit; danh sách này cũng không phải điểm số hiện tại của 2026.

Kiểm tra point-in-time: xóa toàn bộ giao dịch 6/2025 rồi tái tạo feature tháng 5/2025; cả **177/177 feature của 3.178 người dùng** giống hệt bản tạo từ file đầy đủ.
