# Pilot: nhắc giao dịch thứ hai ở ngày 14

## Mục tiêu

Kiểm tra **tác động nhân quả** của một lời nhắc/ưu đãi nhỏ đối với xác suất có ít nhất một giao dịch ở **ngày 30–59** sau giao dịch BNPL đầu tiên. Chênh lệch quan sát 60,0% so với 73,4% giữa nhóm một giao dịch và 2+ giao dịch ở ngày 14 chỉ dùng để chọn nhóm thử, **không phải hiệu quả dự kiến của chiến dịch**.

## Quy tắc triển khai

1. Tại đầu ngày `first_purchase_date + 14`, đếm giao dịch BNPL đã ghi nhận trong ngày 0–13. Chỉ user có **đúng một** giao dịch đi tiếp. Lấy `first_purchase_date` từ lịch sử đầy đủ, không chỉ từ một extract ngắn để tránh coi khách cũ là mới.
2. Trước khi randomize, join **account status, repayment/DPD, quyền nhận thông báo và điều kiện ưu đãi**. Bỏ user không đủ điều kiện. Những trường này không có trong `data.csv`, nên [next_steps.py](next_steps.py) chỉ tạo dry-run lịch sử, không tạo danh sách gửi thật.
3. Randomize ổn định theo `user_id`, 50/50 `prompt` và `holdout`; ghi assignment bất biến cùng `trigger_date`. Một user chỉ vào thử nghiệm một lần. Không để CRM gửi chương trình tương tự cho holdout trong cửa sổ đo.
4. Gửi chỉ cho `prompt` còn đủ điều kiện tại thời điểm gửi. Giữ user đã assign nhưng không gửi thành công trong **intention-to-treat**; theo dõi send/delivery riêng để chẩn đoán vận hành.

## Đo lường

| Loại | Metric |
|---|---|
| Primary | Tỷ lệ user có ≥1 giao dịch BNPL trong ngày 30–59 kể từ giao dịch đầu, tính trên **toàn bộ user đã randomize** trong mỗi nhánh. |
| Secondary | Giao dịch và GMV ngày 30–59 trên mỗi user được assign; tỷ lệ giao dịch thứ hai trong ngày 14–29; tỷ lệ gửi thành công. |
| Guardrail | Nợ quá hạn, repayment rate, credit losses, chi phí ưu đãi và liên hệ quá nhiều. Không thể tính các metric này từ CSV hiện có. |
| Kinh tế | `Incremental net contribution = incremental gross margin − incentive/notification cost − incremental credit losses`. Chỉ scale khi con số này dương và guardrail đạt. |

Phân tích theo assignment (intention-to-treat), không chỉ người mở thông báo hoặc thực sự dùng ưu đãi. Cố định cửa sổ đo và thời gian chạy trước khi xem kết quả. Không gọi GMV tăng là lợi nhuận tăng.

## Cỡ mẫu và tính khả thi

[Bảng cỡ mẫu](outputs/next_steps/pilot_sample_size.csv) dùng baseline 60,0%, kiểm định hai phía 5%, power 80%: **356/nhánh** cho hiệu ứng tuyệt đối +10 điểm %, **1.470/nhánh** cho +5 điểm %. Inflow Jun 2025 là 596 user; nếu 38,9% đạt điều kiện ngày 14, có khoảng 232 user đủ điều kiện mỗi tháng. Thời gian tuyển mẫu tương ứng khoảng **4 hoặc 13 tháng**, chưa kể phần bị loại bởi risk/consent hoặc thay đổi inflow. Vì vậy pilot ngắn chỉ đủ phát hiện hiệu ứng lớn.

## File đã có và cách chạy

```bash
python My_solution/next_steps.py
python My_solution/next_steps.py --cohort-month 2025-04
```

`outputs/next_steps/pilot_dry_run_2025-05.csv` minh họa assignment trên dữ liệu lịch sử. Cột `simulation_only=True`; **không dùng để gửi hoặc tuyên bố đã có treatment**.

Khi đã có pilot thật: xuất CSV assignment gồm `user_id,first_purchase_date,trigger_date,arm,simulation_only` (`False`), cập nhật giao dịch đến ít nhất ngày 59 của **mọi** user trong pilot, rồi chạy:

```bash
python My_solution/evaluate_pilot.py \
  --assignment actual_assignments.csv \
  --transactions updated_transactions.csv \
  --out actual_pilot_result.json
```

[evaluate_pilot.py](evaluate_pilot.py) kiểm tra user ID trùng, tính đúng điều kiện ngày 14, đủ follow-up và từ chối file dry-run. Output gồm retention mỗi nhánh, chênh lệch tuyệt đối, khoảng tin cậy, Fisher p-value và GMV trên mỗi user được assign. Cần join dữ liệu cost/risk riêng để kết luận kinh tế.
