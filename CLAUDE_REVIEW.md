# Nhận xét bài Claude và đối chiếu với bài độc lập

**Phạm vi:** [đề bài](question.docx), [dữ liệu](data.csv), [bài Claude](AI_solution/REPORT.md), [code Claude](AI_solution/analysis.py) và [bài làm độc lập](My_solution/REPORT.md). Tôi đã chạy lại `AI_solution/analysis.py` và `My_solution/analysis.py`; cả hai chạy thành công trên dữ liệu hiện có. Nhận xét dưới đây tập trung vào độ tin cậy của kết luận kinh doanh, không chấm điểm hình thức.

## Đánh giá chung

Bài Claude **mạnh về độ bao phủ và khả năng kiểm tra lại**: trả lời đủ ba phần, có cohort matrix, kiểm tra dữ liệu bất thường, so sánh cửa sổ 30 ngày, mô hình churn kiểm tra theo thời gian và trang tóm tắt cho Business Lead. Các con số được tính nhất quán theo quyết định loại 104 dòng của Claude. Điểm cần sửa quan trọng nhất là **đã đưa một giả thuyết về chất lượng dữ liệu thành quy tắc loại dòng cho toàn bộ phân tích** khi chưa có metadata xác nhận 104 giao dịch sai.

| Nội dung | Bài Claude | Bài độc lập | Ý nghĩa khi so sánh |
|---|---:|---:|---|
| Giao dịch dùng làm kết quả chính | 204.590 | 204.694 | Khác chính sách xử lý 104 dòng cuối dải ID. |
| M1 retention, 17 cohort quan sát được | 73,0% | 73,6% | Chênh 0,6 điểm %, không làm đổi nhận định tổng quát. |
| M1 của nhóm đúng 4 giao dịch M0 | 77,1% | 82,1% | Chênh 5,0 điểm %, ảnh hưởng trực tiếp Q1c. |
| `≥4` so với `<4` giao dịch M0 | +6,8 điểm % | +8,7 điểm % | Độ nhạy lớn đối với lựa chọn ngưỡng. |
| MAU Jun 2025 | 3.019 | 3.022 | 104 dòng ít ảnh hưởng tổng quan. |
| Cách trình bày 104 dòng | Loại và gọi là dữ liệu nghi vấn | Giữ dữ liệu gốc, báo cả trường hợp loại | Cần xác minh nguồn trước khi quyết định số chính thức. |

## Những điểm làm tốt

1. **Định nghĩa cohort và xử lý censoring hợp lý.** Claude tính M1 chỉ cho cohort đã đủ thời gian quan sát, đồng thời bổ sung cửa sổ 30 ngày để giảm thiên lệch do người dùng bắt đầu vào cuối tháng ([báo cáo, Q1a–Q1c](AI_solution/REPORT.md)).
2. **Phát hiện 104 dòng thực sự có giá trị.** Toàn bộ 104 ID `TXN00204591`–`TXN00204694` đều ở cuối dải ID, thuộc 104 người đã có đúng bốn giao dịch M0, rồi bổ sung một giao dịch M1. Đây là tín hiệu bất thường rất đáng điều tra và Claude đã định lượng tác động chính xác.
3. **Không biến tương quan thành khẳng định nhân quả ở Q1c.** Báo cáo có ghi cần A/B test để biết một ưu đãi cho giao dịch thứ hai có làm tăng retention hay không. Mô hình churn AUC 0,56 cũng được mô tả là yếu, không thổi phồng sức dự báo.
4. **Tài liệu và pipeline dễ tái chạy.** Có code, bảng, chart, báo cáo đầy đủ và one-pager. Tôi chạy lại code thành công.

## Những điểm cần sửa, theo mức ảnh hưởng

### 1. Cao — Quyết định loại 104 dòng chưa được chứng minh

Trong [code Claude, phần kiểm tra ID](AI_solution/analysis.py), Claude đánh dấu giao dịch nằm ngoài block ID của từng user, rồi loại toàn bộ ở bước tạo `df = raw[~raw["out_of_sequence"]]` (dòng 147–155 và 222–225). Dấu hiệu được nêu thêm là vài cặp `package_code`/`carrier` hiếm và vài lần số dư tăng nhiều hơn tiền giao dịch. Tuy nhiên:

- ID được cấp sau có thể là giao dịch nạp lại muộn; đề bài không nói ID phải nằm liên tiếp theo user.
- Quy tắc coi cặp package/carrier xuất hiện dưới 10 lần là lỗi (`pair_n < 10`, dòng 174–178) là một heuristic, chưa phải danh mục mapping chính thức.
- `total_outstanding` chưa có định nghĩa thời điểm chụp. Suy ra “implied repayment âm” từ chênh lệch hai số dư (dòng 180–189) cần biết liệu có phí, lãi, chỉnh sửa số dư hoặc độ trễ cập nhật.

**Đề nghị sửa:** giữ dữ liệu gốc làm kết quả chính, trình bày kết quả không gồm 104 dòng như sensitivity, và gắn kết luận Q1c với yêu cầu kiểm tra provenance. Nếu Data Engineering xác nhận đây là dữ liệu test/lỗi thì mới dùng bản loại dòng làm official metric. Bài độc lập thực hiện cách này.

### 2. Cao — Một số kịch bản hành động bị đọc như hiệu quả dự báo

[Báo cáo Claude, phần 2.5](AI_solution/REPORT.md) đưa ra khoảng **+390 MAU** từ frequency rewards và **+270 MAU** từ nhắc giữa tháng vào Jun 2026. Đây là kết quả từ giả định “mọi user dùng ít sẽ churn như user dùng nhiều” hoặc “cứu được 1/10 user có nguy cơ”, chứ không phải tác động được ước lượng từ thí nghiệm ([code mô hình kịch bản](AI_solution/analysis.py), dòng 740–788 và 814 trở đi). Khoảng cách churn quan sát được có thể do mức quan tâm sẵn có của user, nên không thể mặc định một ưu đãi sẽ thu hẹp nó. Kịch bản cũng chưa tính chi phí ưu đãi và tổn thất tín dụng.

**Đề nghị sửa:** ghi rõ các con số là *illustrations under assumptions*, không đặt chúng ở mức chắc chắn gần bằng kết quả lịch sử. Thứ tự quyết định nên là tìm bước funnel giảm, thiết kế holdout, rồi tính incremental retention và net contribution sau chi phí/rủi ro.

### 3. Trung bình — “Không quay lại” trong extract bị diễn đạt thành “ra đi vĩnh viễn”

Claude phát hiện **0 user quay lại sau một tháng trống**; tôi cũng xác nhận 0 trên dữ liệu gốc. Nhưng [báo cáo](AI_solution/REPORT.md) dùng “gone for good”, “lapses are permanent” và suy ra 61% user im lặng đến ngày 15 sẽ mất vĩnh viễn. Điều đã đo chắc chắn chỉ là **không có giao dịch trở lại trong cửa sổ quan sát và theo quy tắc xuất dữ liệu hiện tại**. Chính báo cáo cũng nêu khả năng extract chỉ giữ streak đầu tiên hoặc tài khoản bị khóa.

**Đề nghị sửa:** gọi nhóm này là “không mua trong phần còn lại của tháng” hoặc “không thấy quay lại trong extract”; kiểm tra account status và ETL trước khi lập chiến dịch win-back hoặc khẳng định mất vĩnh viễn.

### 4. Trung bình — Tên “lifetime” và “cohort giống nhau” quá chắc

Các cohort Jan–Jun 2024 chỉ có **12–18 tháng theo dõi không bằng nhau** tại mốc Jun 2025. Vì vậy “lifetime GMV” và “average user active for 4.0 months” trong [báo cáo](AI_solution/REPORT.md) là giá trị **đã quan sát đến ngày chốt**, có thể bị cắt cụt với user còn hoạt động. Nên so sánh GMV trong cùng một cửa sổ 12 tháng theo cohort đủ trưởng thành, hoặc dùng phương pháp survival/censoring phù hợp.

Báo cáo cũng diễn giải các kiểm định cohort có `p > 0,05` thành “retention did not change” / “all cohorts follow the same curve”. Những kiểm định đó chỉ không tìm được khác biệt đủ mạnh; không chứng minh tương đương. Cách diễn đạt an toàn hơn là “không thấy thay đổi lớn trong 18 tháng, với độ dao động M1 khoảng 71–76%”.

## Kết luận đối chiếu

Hai bài **đồng ý về hướng chính**: cơ sở active user giảm, số người mua lần đầu giảm mạnh, retention khoảng 73–74% ở M1 rồi giảm tiếp, và tần suất mua có liên quan tới rời bỏ. Bài Claude phong phú hơn về chart và mô hình; bài độc lập đặt trọng tâm vào **giữ số gốc, trình bày độ nhạy, và gắn khuyến nghị với phép thử có holdout**. Trước khi dùng một trong hai để ra quyết định thật, cần xác minh 104 giao dịch và đối chiếu extract với số liệu sản phẩm chính thức.

## Bổ sung sau khi quét toàn bộ dữ liệu

[Phân tích mở rộng](My_solution/NEW_ANGLES.md) và [data atlas](My_solution/DATA_ATLAS.md) tìm thêm các góc dưới đây. Chúng giúp phân biệt một bài dừng ở mô tả retention với một bài biết chuyển dữ liệu thành quyết định có thể kiểm tra.

| Góc mới | Bằng chứng bổ sung | Phần Claude đã/ chưa làm |
|---|---|---|
| **Reweighting inflow theo từng cohort** | Nếu cohort Nov 2024–Jun 2025 có 1.063 người mới/tháng như Oct và giữ tỷ lệ còn hoạt động đến Jun đã quan sát, MAU Jun khoảng 4.346 thay vì 3.022. | Claude có kịch bản 12 tháng dựa churn cố định; phép tính này ở **trong kỳ quan sát**, ít giả định hơn và nêu rõ không phải forecast. |
| **Chọn thời điểm can thiệp và mức độ “tự mua lại”** | Nhóm chỉ mua một lần tới ngày 7/14/21 chiếm 60%/39%/27% user; 70%/54%/33% trong chính nhóm đó vẫn tự mua lần hai trước ngày 30. | Claude đề xuất second-purchase offer và mid-month reminder, nhưng chưa lượng hóa độ trễ trigger và nguy cơ trả ưu đãi cho giao dịch sẽ xảy ra tự nhiên. |
| **Fixed-horizon value** | Cùng 13.726 user đủ M0–M6 tạo 3,43 active user-months và 1,86 triệu VND GMV mỗi người trong bảy tháng đầu. | Dễ so sánh hơn “lifetime GMV” của cohort bị cắt cụt khác nhau; cả hai đều không phải lợi nhuận ròng. |
| **Tín hiệu nhiều carrier bị nhiễu bởi frequency** | Chênh retention ngày 30–59 thô 6,9 điểm %, sau chuẩn hóa theo số giao dịch còn 1,7 điểm %. | Claude có kiểm soát merchant categories trong churn model; phần mở rộng cho thấy độ lớn chênh thô và sau điều chỉnh theo cách một stakeholder dễ hiểu. |
| **Nguồn dữ liệu có quy tắc mạnh** | ID phủ kín dải, 104 dòng chèn sau block user, new-user trend gần log-linear (`R² = 0,975`), không reactivation, limit tĩnh, lịch giao dịch phẳng. | Claude có nêu nhiều dấu hiệu riêng lẻ; atlas gom chúng thành một câu hỏi ưu tiên về **provenance/ETL** trước khi ngoại suy thành quyết định kinh doanh. |

Ngoài insight, [pilot ngày 14](My_solution/PILOT.md) đã có [code tạo assignment dry-run](My_solution/next_steps.py) và [code đánh giá thử nghiệm thật](My_solution/evaluate_pilot.py) với kiểm tra đủ follow-up. Đây là triển khai phân tích offline; không có dữ liệu repayment/account status để gửi ưu đãi hay kết luận net value.
