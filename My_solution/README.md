# Bài làm AI độc lập — BNPL BI take-home

| Đọc theo thứ tự | Nội dung |
|---|---|
| [REPORT.md](REPORT.md) | Trả lời đủ Q1, Q2 Option A, Q3 và Bonus ngắn theo đúng đề. |
| [ONE_PAGE.md](ONE_PAGE.md) | Bản một trang cho Business Lead. |
| [NEW_ANGLES.md](NEW_ANGLES.md) | Nhiều góc phân tích thêm: inflow, giá trị cohort, thời điểm nhắc, phân khúc và độ nhạy. |
| [DATA_ATLAS.md](DATA_ATLAS.md) | Kiểm tra toàn bộ 8 cột, các quan hệ giữa cột và dấu hiệu về nguồn dữ liệu. |
| [PILOT.md](PILOT.md) | Thiết kế A/B test ngày 14 và hợp đồng dữ liệu để đánh giá sau khi có thử nghiệm thật. |
| [CHURN_MODEL.md](CHURN_MODEL.md) | XGBoost churn với 177 feature ứng viên, 24 lần thử validation, test ngoài thời gian và giới hạn của mục tiêu AUC 0,8. |

Code và output:

```bash
python My_solution/analysis.py
python My_solution/next_steps.py
python My_solution/data_atlas.py
python My_solution/segment_mix.py
python My_solution/churn_xgboost.py
python My_solution/churn_xgboost_v2.py
```

Các script chỉ đọc `data.csv` và ghi vào `My_solution/outputs/`. [evaluate_pilot.py](evaluate_pilot.py) dùng khi đã có assignment và giao dịch của **thử nghiệm thật**; nó từ chối file assignment dry-run lịch sử. Không có chức năng gửi tin nhắn hoặc tác động tới tài khoản.

Kết quả chính dùng CSV được giao nguyên vẹn. 104 giao dịch cuối ID được trình bày thành sensitivity, không bị tự động loại. File [nhận xét Claude](../CLAUDE_REVIEW.md) nằm ở thư mục gốc để so sánh hai bài.
