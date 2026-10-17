# Review bài Codex, đối chiếu với bài Claude và cách gộp thành bản hoàn chỉnh

**Phạm vi:**
- [Bài Codex](My_solution/REPORT.md) cùng các tài liệu mở rộng: [NEW_ANGLES](My_solution/NEW_ANGLES.md), [DATA_ATLAS](My_solution/DATA_ATLAS.md), [PILOT](My_solution/PILOT.md) và code.
- [Nhận xét của Codex về bài Claude](CLAUDE_REVIEW.md).
- [Bài Claude](AI_solution/REPORT.md).
- **Bản hoàn chỉnh:** [FINAL_solution](FINAL_solution/report.html).

Những con số của Codex được dùng lại trong FINAL đều đã được tính lại bằng code của FINAL, và agent QC số liệu đã tính lại độc lập một phần trong số đó. Các chênh lệch nhỏ là do Codex dùng file gốc, còn FINAL loại 104 dòng nghi vấn.

---

## 1. Tóm tắt

| | Codex | Claude (trước khi gộp) | FINAL |
|---|---|---|---|
| Hướng kết luận chính | Inflow giảm là nguyên nhân chính; retention ổn định; tần suất liên quan tới churn | Như Codex | Như hai bài |
| Bẫy 104 dòng | Phát hiện; giữ file gốc làm chính, báo kết quả khi loại dòng như sensitivity | Phát hiện; loại làm chính, có thêm 5 bằng chứng định lượng | Loại làm chính *tạm thời*; mọi số chính được báo song song trên file gốc (Appendix A2) |
| Q1c | "Không có N duy nhất"; mốc đề xuất: giao dịch thứ 2 trong 30 ngày (+17,3 điểm %) | Ban đầu cũng dùng +17 điểm %; sau QC phát hiện con số này **phần lớn là hiệu ứng cơ học do ranh giới tháng** | Kết luận của Claude, kèm đánh đổi thời điểm kích hoạt của Codex |
| Part 2 (churn) | Mỏng: chỉ phân tích theo tần suất, có chuẩn hóa theo tenure | Sâu: 6 nhóm tín hiệu, hồi quy và LR test, AUC out-of-time, phân tầng rủi ro, credit lens, quy mô từng đòn bẩy | Bản của Claude, bổ sung phân rã thay đổi churn và kế hoạch thử nghiệm |
| Kiểm định thử nghiệm | **Rất tốt:** pilot ngày 14 theo ITT, có guardrail, tính cỡ mẫu, code dry-run và code đánh giá | Chỉ nêu "cần A/B test" | 2 pilot (A ngày 14, B giữa tháng), **phân tầng**, kèm kiểm tra A/A |
| Insight ngoài đề | Khoảng 10 góc, tập trung vào quyết định và nguồn gốc dữ liệu | Khoảng 20 phát hiện (giá trị, hành vi, mô hình sống sót, ngành hàng, tín dụng, dữ liệu) | Gộp cả hai, khoảng 25 phát hiện |
| Trình bày | **Gọn** (~1.350 từ), dễ đọc; tài liệu mở rộng bằng tiếng Việt; one-pager dạng Markdown | 10 biểu đồ, HTML tự chứa, one-pager in vừa A4, nhưng **dài** | Bản của Claude; phần lõi nên đọc trước |

**Nhận định:** hai bài bổ sung cho nhau.
- **Codex mạnh về** kỷ luật nhân quả, nguồn gốc dữ liệu và biến khuyến nghị thành thử nghiệm chạy được.
- **Claude mạnh về** độ sâu phân tích, Part 2, mô hình hóa và trình bày.
- **FINAL** lấy phần mạnh của cả hai.

---

## 2. Điểm mạnh của bài Codex

1. **Nguyên tắc "giữ dữ liệu gốc, báo cả hai trường hợp"** khi chưa xác minh được nguồn gốc 104 dòng. Đây là lập trường thận trọng và đúng chuẩn kiểm toán.
2. **Tính lại MAU theo inflow trong kỳ quan sát.** Giữ nguyên tỷ lệ còn hoạt động của từng cohort, chỉ thay quy mô cohort Nov-24 đến Jun-25 bằng mức của Oct-24: MAU Jun-25 sẽ khoảng 4.346 thay vì 3.022 (số của Codex, trên file gốc). Trên dữ liệu sạch, FINAL ra 4.341 thay vì 3.019. Phép tính ít giả định hơn kịch bản dự phóng 12 tháng.
3. **Đánh đổi thời điểm kích hoạt (ngày 7/14/21):** tỷ lệ user đủ điều kiện, tỷ lệ hoạt động ngày 30–59, và **tỷ lệ tự mua lần 2 dù không can thiệp** (70%/54%/33%). Đây là cách lượng hóa chi phí "trả ưu đãi cho giao dịch vốn sẽ xảy ra".
4. **Giá trị theo cửa sổ cố định M0–M6:** 3,43 tháng hoạt động và 1,855 triệu GMV mỗi user (số của Codex; FINAL ra 3,42 tháng và 1,85 triệu trên dữ liệu sạch). Tránh được vấn đề "lifetime" bị cắt cụt.
5. **Phân rã thay đổi churn** Oct-24 → May-25 thành hiệu ứng cơ cấu tenure và hiệu ứng trong từng tenure.
6. **Chất lượng user mới theo quý**, đo trên cùng cửa sổ 30 ngày.
7. **Data atlas:**
   - Dao động giao dịch theo ngày ≈ nhiễu Poisson (5,0% so với 5,0%).
   - User mới giảm theo hàm mũ gần hoàn hảo (R² = 0,975).
   - Có 95 mức hạn mức cố định và 38 cặp package–carrier, trong đó 4 cặp chỉ tồn tại nhờ 104 dòng nghi vấn, còn 34 cặp là thật.
8. **Pilot hoàn chỉnh:**
   - Thiết kế theo intention-to-treat, có guardrail rủi ro và chi phí, công thức net contribution.
   - Cỡ mẫu 356/1.470 user mỗi nhánh, tương ứng 4/13 tháng để tuyển đủ.
   - Code dry-run gán nhóm bằng hash cố định nên nhánh của mỗi user ổn định qua các tháng. FINAL đã áp dụng lại cách này. Nhược điểm nhỏ: dry-run lệch cỡ nhóm (136/105). Code đánh giá từ chối file dry-run.
9. **Ngôn ngữ nhân quả cẩn trọng** xuyên suốt báo cáo.
10. **Ngắn gọn:** khoảng 1.350 từ trả lời đủ đề. Bài Claude và FINAL dài hơn nhiều; nếu cần bản ngắn, phần lõi gồm tóm tắt, Q1, Part 2 và one-pager.

## 3. Điểm yếu và lỗi của bài Codex

| # | Vấn đề | Bằng chứng | Mức độ |
|---|---|---|---|
| 1 | **Mốc "giao dịch thứ 2 trong 30 ngày, +17,3 điểm %" bị nhiễu bởi ranh giới tháng.** Công bằng mà nói, Codex đã ghi rõ đây là tương quan, không phải hiệu quả chiến dịch. Bài Claude cũng mắc đúng lỗi này cho đến vòng QC 3. Điểm Codex bỏ sót là phần cơ học. | Trong nhóm chỉ 1 giao dịch/30 ngày: 65% còn hoạt động nếu gia nhập ngày 1–3, chỉ 17% nếu gia nhập ngày 21–31. Hồi quy có kiểm soát cho thấy bước 1→2 không lớn hơn các bước sau (0,12 / 0,11 / 0,18 log-odds). | Cao (ảnh hưởng Q1c) |
| 2 | **Pilot ngày 14 không phân tầng theo ngày gia nhập.** | Baseline 60% thực ra trộn hai nhóm 69% (gia nhập ngày 1–3) và 42% (sau ngày 20). Phân tầng giảm phương sai và tránh mất cân bằng. | Trung bình |
| 3 | **Part 2 mỏng so với yêu cầu "How do they differ".** | Phần churn trong báo cáo chỉ so tần suất (có chuẩn hóa tenure). NEW_ANGLES có sàng lọc hạn mức, ticket, ngành đầu và độ rộng merchant, nhưng theo M1 của user mới, không theo churn. Chưa có momentum, trả nợ suy ra, khả năng dự báo hay phân tầng user có nguy cơ. | Cao (Part 2 là phần "go deep") |
| 4 | **Chưa kiểm tra hiệu ứng chạm trần hạn mức lên churn.** | Codex ghi "chỉ 2,1% user-month ≥80%". Tháng kết thúc ở hạn mức có churn 27,3% so với 24,9% (p = 0,02 riêng biến này). Nhưng khi gộp với các biến phi tần suất khác thì p = 0,19, và trường số dư còn đáng ngờ. | Thấp |
| 5 | **Khác đơn vị đo, không phải lỗi:** mức độ tập trung GMV đo theo user-month. | Top 10% user-month = 28,9% GMV; đo theo user thì top 10% = 39%, top 20% = 58%. Hai cách đều đúng nhưng trả lời câu hỏi khác nhau. | Thấp |
| 6 | **Chưa có mô hình sống sót.** | Codex có nêu retention giảm suốt vòng đời. Số liệu quan sát cho thấy churn vẫn 21–24% ở M9–M12. Con số "chỉ 0,2% user dưới 10%/tháng" là ngoại suy từ mô hình sBG của FINAL. | Thấp |
| 7 | **Trình bày** (đề cho phép mọi định dạng, nên đây là khác biệt chứ không phải lỗi). | Báo cáo chính tiếng Anh, tài liệu mở rộng tiếng Việt; one-pager dạng Markdown không biểu đồ; báo cáo chính có 3 biểu đồ. Bù lại rất gọn. | Thấp |
| 8 | **Sắc thái, không phải lỗi:** "MAU peaked at 4,162 in Oct 2024". | Đúng trên file gốc. Nên nói thêm là MAU đi ngang Jul–Oct (khoảng 4.110–4.160), và tháng 10 có đột biến user mới (+13% so với xu hướng). | Thấp |
| 9 | **Nhỏ:** "14,226 users whose lapse had at least two later months". | Con số đúng (14.226 trên file gốc) nhưng định nghĩa là "ít nhất *một* tháng sau tháng trống". | Thấp |
| 10 | **Nhỏ:** mốc tháng 10 cho phép tính lại MAU. | Tháng 10 là tháng đột biến. FINAL báo thêm mốc trung bình 2024: khoảng 4.630. | Thấp |

## 4. Phản hồi các nhận xét của Codex về bài Claude

| Nhận xét của Codex | Đồng ý? | Đã xử lý trong FINAL |
|---|---|---|
| 1. Loại 104 dòng chưa được chứng minh | **Đồng ý một phần.** Bằng chứng rất mạnh: 5 dấu hiệu độc lập, kể cả việc 104 dòng nhắm đúng user có 4 giao dịch M0 và hành vi số dư khác hẳn giao dịch tự nhiên. Nhưng chưa có xác nhận từ nguồn. | Giữ loại dòng làm chính nhưng gọi là "tạm thời". Thêm **Appendix A2** báo mọi số chính trên cả hai phiên bản; chỉ ô N = 4 của Q1c thay đổi. |
| 2. Con số kịch bản (+390, +270) dễ bị đọc như dự báo | **Đồng ý** | Gắn nhãn "minh họa theo giả định, chưa trừ chi phí ưu đãi và tổn thất tín dụng". Thêm **mục 2.6 Test plan** để đo hiệu quả thật. |
| 3. "Gone for good / permanent" khẳng định quá mức | **Đồng ý** | Đổi thành "không thấy quay lại trong extract này", kèm hành động kiểm tra account status và ETL. |
| 4. "Lifetime" bị cắt cụt; "cohort giống nhau" quá chắc | **Đồng ý** | Thêm giá trị theo cửa sổ cố định (M0–M6, M0–M11). Q1c dùng cửa sổ 12 tháng (3,7×). Viết lại thành "no large change detected". Giữ ước lượng sBG vì mô hình này đã xử lý censoring. |

Lưu ý: Codex nhận xét trên một phiên bản cũ của bài Claude. Một số điểm, như con số 30 ngày +17 điểm % hay mức +60 cho ưu đãi giao dịch thứ 2, đã được Claude tự sửa ở vòng QC 3 trước khi gộp.

## 5. Bản FINAL gồm những gì

| Thành phần | Nguồn |
|---|---|
| Q1a–Q1c, Part 2 Option A (2.1–2.5), Part 3, 11 biểu đồ, pipeline với khoảng 480 con số kiểm toán được | Claude |
| **Part 2 Option B (2.7–2.10)**: sàng lọc phân khúc, đợt onboarding là pattern có tiềm năng lớn nhất, giới hạn rủi ro chất lượng khi tăng volume, các đòn bẩy quy về GMV, phân khúc medium. Cả hai bài gốc đều chỉ làm Option A | Mới trong FINAL (làm theo yêu cầu của bạn) |
| Bảng song song file gốc / loại dòng (Appendix A2), ngôn ngữ "provisional" | Góp ý của Codex |
| Tính lại MAU theo inflow (4.340 / 4.630), chất lượng user mới theo quý, phân rã churn gần đây | Codex, tính lại trên dữ liệu sạch |
| Đánh đổi thời điểm kích hoạt 7/14/21, tỷ lệ giao dịch thứ 2 trên toàn bộ user (40/61/82%) | Codex |
| Giá trị cửa sổ cố định M0–M6 và M0–M11; Q1c so trên cửa sổ 12 tháng | Codex |
| Độ rộng merchant sau chuẩn hóa tần suất (6,9 → 2,0 điểm %), sàng lọc ngành đầu tiên, dao động ngày ≈ Poisson, user mới giảm theo hàm mũ | Codex |
| **2.6 Test plan:** 2 pilot, phân tích phân tầng, cỡ mẫu (kể cả mức +2 điểm % thực tế), thời gian tuyển; **chạy Test B trước** vì đủ mẫu sau 1–3 tháng thay vì 4–13 | Codex (thiết kế pilot A; cũng đề xuất nhắc giữa tháng) + Claude (thiết kế chi tiết pilot B, phân tầng, cỡ mẫu B) |
| `pilot.py`: nhánh cố định theo user (hash, theo cách của Codex), mỗi user vào một lần, đánh giá ITT có phân tầng, kiểm tra A/A trên lịch sử (khoảng tin cậy chứa 0; QC chạy 400 lần A/A cho tỷ lệ dương tính giả ~5%) | Claude, dựa trên `next_steps.py` và `evaluate_pilot.py` của Codex |

**Chạy lại:**

```bash
python3 FINAL_solution/analysis.py
python3 FINAL_solution/build_html.py
python3 FINAL_solution/pilot.py dry-run --test B --month 2025-05
```

## 6. Gợi ý dùng khi chấm sinh viên

Mức độ khó tăng dần:
1. Phát hiện dữ liệu 18 tháng, không phải 6.
2. Nhận ra MAU giảm do inflow, không phải do retention.
3. Đúng định nghĩa retention, xử lý censoring.
4. Q1c: không có N đặc biệt.
5. Phát hiện 104 dòng tạo ra N = 4 giả.
6. Phân biệt tương quan với nhân quả, đề xuất A/B test có holdout.
7. Nhận ra vấn đề ranh giới tháng làm nhiễu cửa sổ 30 ngày.
8. Nhận ra 0% user quay lại và đặt câu hỏi về cách trích xuất dữ liệu.

---

## 7. Cập nhật sau deep EDA (2 agent review, 10/2026)

Hai agent độc lập đã soát kỹ toàn bộ 8 cột dữ liệu. Kết luận: **file là dữ liệu mô phỏng, sinh theo vài luật đơn giản**. Vì vậy cả bài Claude lẫn bài Codex đều có một số "insight" thực chất chỉ là dấu vết của bộ sinh dữ liệu:

- **`total_outstanding`:** 100% số dòng tuân theo 3 luật.
  - Cộng dồn dư nợ: 63,7%.
  - Chặn ở hạn mức: 1,3%.
  - Trả bớt ngẫu nhiên: 35,0%. Đây giống tung đồng xu: không phụ thuộc khoảng cách giữa hai giao dịch, phần dư nợ giữ lại phân bố đều 0–70%.
  - Hệ quả: mọi kết luận về utilisation, "chạm hạn mức", "128 user khát tín dụng", trả nợ ngầm định đều phải bỏ.
- **Mỗi giao dịch bị chặn đúng ở 60% hạn mức**, nhưng không có kiểm tra hạn mức còn lại: 4.032 giao dịch vượt phần hạn mức trống.
- **"Làn sóng onboarding đầu tháng" là ảo giác thống kê.** Ngày mua đầu tiên chỉ là ngày sớm nhất trong các giao dịch rải đều cả tháng. Tháng đầu là tháng đầy đủ (3,23 giao dịch ở M0 so với 3,22 ở M1).
  - Kéo theo: nhóm "full first month (join ngày 1–3)" trong Q1c bị chọn lệch theo số giao dịch tháng đầu.
- **104 dòng được "chế tạo" từ chính lịch sử của user.** Số dư được copy từ dòng cũ của user ở cả 104/104 dòng. Vì vậy loại bỏ vĩnh viễn, không phải "tạm thời".
- **Phần thật và dùng được:**
  - Churn là đặc tính ổn định của user: trung bình 3 tháng phân tách churn từ 32,5% xuống 19,0%, còn biến động của một tháng lẻ không thêm thông tin.
  - Tenure không có tác dụng riêng.
  - Giá trị user = tần suất × thời gian sống.
  - Heavy user im lặng đến ngày 10 đã mất 60%.

**Gợi ý chấm:** bài sinh viên nào nhận ra dữ liệu là mô phỏng, hoặc nhận ra cột balance / "làn sóng đầu tháng" là artefact, thì đáng điểm cộng lớn ở phần Bonus. Bài nào khuyến nghị tăng hạn mức hay lập danh sách "khát tín dụng" từ cột balance thì nên trừ điểm vì kết luận quá đà.
