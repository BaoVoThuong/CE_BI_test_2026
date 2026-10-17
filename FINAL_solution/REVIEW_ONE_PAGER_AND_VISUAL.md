# Phản biện gắt: `one_pager.html` và `report_visual.html`

**Ngày review:** 13/10/2026. **Phạm vi:** nội dung, phép suy luận, business recommendation và khả năng đọc. Tôi đối chiếu hai HTML với `report_visual_src.html`, `build_html.py`, `analysis.py`, `outputs/key_numbers.json` và các bảng đầu ra. Tôi chỉ review, chưa sửa hai bài.

## Kết luận thẳng

**Chưa nên nộp nguyên trạng.** Phần phân tích cohort, kiểm tra 104 dòng bất thường và tư duy dùng holdout có giá trị. Tôi không thấy lỗi cộng trừ lớn ở các số liệu cohort chính; vấn đề nằm ở **cách diễn giải và ra quyết định**. Headline và các khuyến nghị hiện **mạnh hơn bằng chứng**. Một số câu còn **sai về mặt toán học hoặc kinh tế**. Nếu reviewer hỏi “vì sao chỉ acquisition mới đảo chiều?”, “1,85 triệu GMV sao thành CAC ceiling?” hay “Jun 2026 đã qua rồi, sao vẫn gọi là next 12 months?”, bài sẽ mất điểm seniority rất nhanh.

`one_pager.html` có khoảng **802 từ, 6 biểu đồ, 5 action, 4 bullet phụ** dồn vào một A4. Phần nội dung khi in dùng **6,8 pt** (`build_html.py:106–125`). `report_visual.html` có khoảng **3.007 từ, 15 biểu đồ và in ra 19 trang A4**, trong khi README ghi “~1,850 words” (`README.md:9`). Đây là hai deliverable nhiều thông tin, nhưng chưa phải bản điều hành ngắn, sắc và dễ quyết định.

## BLOCKER — phải sửa trước khi gửi

### 1. “Only more new users can reverse the decline” là **sai**, dù acquisition có thể là ưu tiên số một

Xuất hiện ngay headline/subtitle của cả hai bản (`build_html.py:491–494`; `report_visual_src.html:9–10, 185–199`). Theo chính mô hình trong bài, với MAU = **3.019** và 596 người mua lần đầu/tháng, churn cần giảm xuống dưới **596 / 3.019 = 19,74%** để MAU tăng. Ví dụ, churn 15% cho tháng sau: `3.019 × 0,85 + 596 = 3.162`, **tăng 143 người mà không cần thêm một người mới**. Mức giảm đó có đạt được hay không là câu hỏi khác; không được viết thành bất khả thi.

“Best-case retention” trong biểu đồ chỉ là **một giả định cụ thể**: mọi user mua 1–3 lần có churn ngang nhóm 4+ (`analysis.py:775–783`). Nó đưa churn còn 20,85%, cao hơn ngưỡng 19,74%; bởi vậy kịch bản vẫn giảm nhẹ tới ~2.868 MAU vào Jun 2026, chứ không chứng minh retention không thể đảo chiều. Gọi nó là *best possible retention programme* (`build_html.py:519–524`) là sai phạm vi.

**Viết lại:** “Với các kịch bản đã thử, phục hồi người mua lần đầu là đòn bẩy có quy mô lớn nhất; cải thiện retention đủ mạnh cũng có thể đảo chiều MAU, nhưng chưa có bằng chứng can thiệp đạt mức đó.”

### 2. Dùng **GMV 1,85 triệu VND** làm “ceiling” cho CAC là sai đơn vị kinh tế

Action 4 của one-pager nói gross payment volume 1,85M VND trong 7 tháng “sets a ceiling for what we can pay to acquire a user” (`build_html.py:534–535`). Đây là **giá trị thanh toán**, không phải doanh thu hay contribution. Chú thích cuối trang “GMV is not revenue” không cứu được một action viết ngược lại. Bản visual tiến thêm một bước thành `take rate × 1.85M` (`report_visual_src.html:212–214`), nhưng vẫn bỏ funding cost, credit losses, servicing, incentive, thời điểm thu tiền và biên lợi nhuận.

**Viết lại:** “1,85M VND là GMV quan sát trong 7 tháng, chỉ là đầu vào để Finance tính CAC ceiling từ *net contribution* sau chi phí vốn, tổn thất tín dụng và vận hành. Hiện chưa đủ dữ liệu để đưa ra ceiling.” Không đưa con số CAC hay ROI trong bài này.

### 3. Report đang ra quyết định “hiện tại” bằng dữ liệu và kịch bản đã quá hạn

Hai bản dùng “now”, “today”, “next 12 months”, “by Jun 2026” và xin duyệt pilot 1–3 tháng (`report_visual_src.html:19–21, 39–43, 62, 179–180`; `build_html.py:491–531, 546–550`). **Hôm nay là 13/10/2026**; dữ liệu dừng **Jun 2025**, còn mốc dự báo **Jun 2026 đã qua**. Đó có thể là bài test phân tích lịch sử, nhưng không được trình bày như kế hoạch vận hành đang chờ quyết định.

**Viết lại:** gắn nhãn rõ “Historical analysis as of Jun 2025” cho mọi chart/kịch bản; dùng “as of Jun 2025” thay “today/now”. Nếu muốn khuyến nghị hiện tại, cần cập nhật số liệu đến 2026 và backtest đường Jun 2026 đã xảy ra. Không gọi đường kịch bản cũ là forecast còn hiệu lực.

### 4. Headline “acquisition problem” đang đánh tráo **first observed purchase** với **new sign-up/acquisition**

`new user` được định nghĩa từ **giao dịch BNPL đầu tiên quan sát được**, không có signup, approval hay nguồn traffic (`analysis.py:240–256`; `report_visual_src.html:75–79, 88–95`). Giảm first purchase có thể đến từ tiếp cận, approval, activation, eligibility, chiến dịch, hoặc cách trích xuất mẫu. In-sample replay giữ retention cố định chỉ cho thấy **số người có giao dịch lần đầu thấp đi là thành phần kế toán lớn của MAU giảm**; nó không xác định nguyên nhân ở acquisition funnel, càng không chứng minh “whole decline is an acquisition story” (`report_visual_src.html:69–79`). Chính report thừa nhận file có thể là sample.

**Viết lại:** “First observed BNPL purchasers fell sharply; churn is comparatively stable in this extract. Reconcile with official activation funnel before assigning a cause or budget.” Có thể ưu tiên audit funnel mà không khẳng định đã tìm ra lỗi marketing.

## MAJOR — kết luận có hướng đúng nhưng đang nói quá

### 5. “Flat churn for 18 months” sai cả số kỳ lẫn mức độ ổn định

18 tháng giao dịch chỉ có **17 chuyển tiếp tháng** để tính churn. Jan 2024 = **28,9%**, còn Feb 2024–May 2025 dao động **23,5–26,3%** (`key_numbers.json`: `churn_rate_jan24`, `churn_rate_range_*`). One-pager ghi “unchanged for 18 months”; visual KPI ghi “flat for 18 months” (`build_html.py:493–499`; `report_visual_src.html:10, 15`). Churn nhìn chung khá ổn định **sau tháng đầu**, nhưng câu hiện tại sai chính xác.

Tương tự, “we lose ~750 and gain ~600 **each month**” trong one-pager (`build_html.py:503–506`) lấy **một chuyển tiếp May→Jun 2025** (`users_lost_may_to_jun25`), không phải số mỗi tháng cố định. Ghi đúng cửa sổ thời gian.

**Sửa:** “Monthly lapse was broadly 23.5–26.3% from Feb 2024 to May 2025; Jan 2024 was 28.9%.”

### 6. “Planted rows”, “permanently exclude”, “the extract is simulated” là kết luận về **nguồn dữ liệu** chưa được xác nhận

104 dòng cuối có dấu hiệu cực mạnh: mỗi dòng làm một user M0=4 có thêm giao dịch M1; dư nợ khớp lịch sử của chính user (`report_visual_src.html:28–29, 52–54, 132–143`; `analysis.py:1454–1456`). Điều đó biện hộ **quarantine và phân tích nhạy cảm**, không tự chứng minh ai đã “planted” chúng. Tương tự, các quy tắc số dư/hạn mức gợi ý dữ liệu mô phỏng, nhưng không xác nhận provenance. Gọi purchase frequency/inflow là “real” sau khi nói cả extract synthetic (`report_visual_src.html:259–281`) là tự mâu thuẫn: chúng là **pattern trong extract**, chưa chắc là hành vi production.

**Sửa:** “104 structurally suspicious appended rows; main estimates exclude them pending source confirmation; raw sensitivity shown.” Và “synthetic-like patterns; validate source before applying to production.”

### 7. “Tháng đầu như một tháng đầy đủ, late joiners không cần điều chỉnh” là suy luận không đứng vững

Bản visual và caption chart dùng trung bình 3,23 giao dịch M0 vs 3,22 M1 của **cùng nhóm sống sót nhiều tháng** để kết luận không có exposure bias (`report_visual_src.html:94`; `visual_charts.py:181–183`). Đây là một nhóm được chọn sau khi biết họ tiếp tục hoạt động, không thể chứng minh mọi user có đủ thời gian đạt N trong M0. Chính bảng do bài tạo cho thấy **41,1%** người có first purchase ngày 1–15 đạt ≥4 giao dịch M0, so với **4,0%** ở ngày 16–31 (`key_numbers.json`: `q1c_share_early_joiners_reaching_4`, `q1c_share_late_joiners_reaching_4`; `analysis.py:507–512`). M1 theo N vẫn có xu hướng sau khi control join week, nhưng cơ hội chạm target rõ ràng khác nhau.

**Sửa:** giữ kết luận liên hệ dương với M1; bỏ câu “no join-day adjustment needed”. Nếu định ra milestone để can thiệp, dùng thời gian cố định sau first purchase hoặc phân tầng theo first-purchase day.

### 8. “Mid-month silence” không phải bằng chứng người dùng sắp churn hay treatment sẽ cứu họ

Tại ngày 15, 41% người active tháng trước chưa mua; 61% của nhóm này tiếp tục không mua tới cuối tháng (`key_numbers.json`: `lapse_share_silent_day15`, `lapse_p_lost_day15`). Nhưng đây gần như là hệ quả của **định nghĩa outcome “không mua trong tháng”**: mọi người mất tháng đó đều phải silent ở ngày 15. Nó là **quy tắc chọn đối tượng còn thời gian để liên hệ**, không phải một churn model độc lập hay causal effect. One-pager gọi đó là “earlier warning” (`build_html.py:541`); visual so precision 61% với churn nền 25% như thể model lift (`report_visual_src.html:154–174`). Nếu người dùng định mua ngày 20, reminder có thể chỉ kéo giao dịch về trước hoặc làm tốn contact cost.

**Sửa:** gọi là *in-month eligibility trigger*. Test primary month-end purchase, nhưng cần kiểm tra thêm 30/60-day cumulative GMV, net contribution, repayment và fatigue để biết có tạo hoạt động mới hay chỉ đổi thời điểm.

### 9. “29% lost payment volume” là **GMV đã phát sinh trước khi lapse**, không phải GMV bị mất hay cứu được

`analysis.py:1508–1518` lấy GMV **tháng hiện tại của user về sau churn** để tính tỷ trọng 28,9%. Nó không tính volume tương lai bị mất; các user đó có zero giao dịch tương lai trong extract. One-pager nói frequent users “take 29% of the lost payment volume with them” (`build_html.py:541`), khiến người đọc hiểu là GMV at risk có thể lấy lại. Không có counterfactual hay uplift để định giá như vậy.

**Sửa:** “Nhóm này tạo 29% **GMV tháng trước của những người sẽ lapse**.” Muốn gọi “recoverable GMV” phải có thử nghiệm và net contribution.

### 10. “Limit, ticket, category make no difference” và “new users are not worse” quá tuyệt đối

P-value lớn nghĩa là **chưa phát hiện thêm tín hiệu trong extract**, không chứng minh effect bằng 0 hay chất lượng người dùng mới tương đương. Hơn nữa chính report coi limit/ticket/category là quy tắc mô phỏng (`report_visual_src.html:75–77, 160–179`; `build_html.py:510–513`). Về cohort quality, 3,53 vs 3,65 giao dịch 30 ngày chỉ nói các chỉ số quan sát tương tự; không có DPD, fraud, loss hay channel mix. “No worse” dễ bị hiểu là đã kiểm tra chất lượng tín dụng.

**Sửa:** “No material deterioration in observed early purchase activity; repayment and channel quality are unknown.” Với feature khác: “No additional association detected after controlling for purchase frequency in this extract.”

### 11. Kích thước hiệu quả trong chart là **giả định**, không phải business case hay upper bound

`+2.150 MAU`, `+270`, `+390`, `+63% GMV` được vẽ cùng một chart/thang đo nhưng đến từ các assumption rất khác nhau (`analysis.py:775–849`; `visual_charts.py:225–250`; `build_html.py:519–533`). “+270 từ reminder” là mô phỏng giảm **toàn bộ churn 10%**, không phải bằng chứng “cứu 1/10 người silent” như caption one-pager; mẫu số đang bị diễn đạt khác với code. “+390 frequency rewards” giả định mọi người 1–3 lần đạt churn nhóm 4+, vốn là **association**, không phải ceiling được chứng minh. +100 người mới/tháng và thay đổi churn cho cả base cũng không có chi phí hay xác suất đạt được tương đương để gọi “like-for-like”.

Tương tự, “expect a few points of M1” cho nudge mua lần hai (`report_visual_src.html:135`) suy từ chênh retention quan sát, dù chính bài ghi đó là correlation. Hiệu quả can thiệp thực tế có thể bằng 0 hoặc âm sau chi phí.

**Sửa:** mỗi nhãn phải có công thức, đối tượng, thời gian, baseline và chữ **illustrative assumption** ngay cạnh số. Tách scenario accounting khỏi estimated treatment effect. Bỏ từ “upper bound/best-case” nếu không chứng minh được cận trên.

### 12. Kế hoạch test không khớp tính khả thi và thời điểm

Visual đưa Test A vào “next quarter” dù bảng ngay dưới nói cần **4 tháng** để tuyển mẫu cho +10pp và **13 tháng** cho +5pp (`report_visual_src.html:235–250`). Đây là tuyển mẫu, **chưa tính 30–59 ngày follow-up**. Nếu first-purchase inflow còn giảm 5%/tháng, thời gian thực có thể dài hơn; +2pp cần ~9.400 người/arm. One-pager xin duyệt cả Test A và B nhưng gọi kết quả 1–3 tháng, khoảng đó chỉ đúng cho **Test B với hiệu ứng +5 đến +10pp** (`build_html.py:546–547`).

**Sửa:** pilot B trước; A chỉ lên design/feasibility, không hứa readout gần. Ghi rõ minimum detectable effect lớn và lịch tuyển + follow-up. Nêu eligibility từ account status/DPD/consent trước khi gửi.

### 13. Đặt M1 ≥71% làm “quality guardrail” là tùy tiện

Visual nói scale channel nếu cohort mới có M1 ≥71% vì historical M1 thấp nhất khoảng 71,1% (`report_visual_src.html:223–227`). Một cohort nhỏ có thể tụt dưới 71% vì nhiễu; một cohort 73% vẫn có default/loss xấu. Không có interval theo cohort size, không có tolerance và không có DPD. Đây không phải tiêu chuẩn approval cho channel.

**Sửa:** dùng cohort M1 như monitoring metric với khoảng tin cậy và cùng tuổi quan sát; quyết định scale phải dựa thêm net contribution, DPD/loss, fraud và incrementality của channel.

### 14. “AUC 0,56” là benchmark của **một mô hình logistic**, không phải trần dự báo của data

Visual nói “prediction is weak (AUC 0.56)” rồi suy ra “practical lever is timing, not a score” (`report_visual_src.html:177–180`). Kết luận yếu của benchmark là hợp lý; suy ra không thể có tín hiệu khác trong transaction data thì quá mạnh. Workspace đã có XGBoost khác đạt AUC ~0,57 trên raw data; vẫn yếu nhưng chứng minh 0,56 không phải tối ưu. Nói rõ model, split và phiên bản dữ liệu. Không dùng accuracy model để suy ra response của reminder.

### 15. “No loyal core: only 0.2% below 10% churn” là kết quả **phụ thuộc mô hình**, không phải quan sát

Con số 0,2% trong Figure 9/visual (`report_visual_src.html:109–111`) đến từ giả định phân phối latent churn dạng shifted-beta-geometric (`analysis.py:1014–1040`), không phải từ việc nhìn thấy xác suất churn thật của từng user. Dữ liệu chỉ quan sát đến M12 cho 6 cohort và hoàn toàn không có reactivation. Nên phát biểu chắc: “Không thấy retention plateau đến M12 trong extract.” Đưa tỷ lệ 0,2% và M24 extrapolation vào phụ lục với mô hình/độ nhạy, đừng dùng để tuyên bố không có loyal core ngoài đời.

## EDITORIAL / PRESENTATION — hiện rất đẹp, nhưng đánh đổi độ rõ

1. **One-pager là một trang bằng cách thu chữ nhỏ.** Chữ body/table in khoảng **6,8 pt**, chú thích **6 pt** (`build_html.py:106–125`). 802 từ, 6 mini charts và 5 action làm Business Lead phải phóng to để đọc. Giữ 3 KPI, 2 visual, 3 action; đưa phương pháp, CAC, bonus, lưu ý data sang report. Mục tiêu khoảng 300–400 từ.
2. **Visual report lặp bằng chứng quá nhiều:** 2 chart inflow, 3 chart retention/survival, 2 chart về levers, thêm Option B dù đề chỉ cần một hướng. Tổng **15 chart/19 trang** làm kết luận chính bị loãng. Chọn một chart cho mỗi câu hỏi và cho các chart còn lại vào appendix. README nên sửa “~1,850 words” thành số thực hoặc làm đúng mức đó.
3. **Part 3 của visual report nằm ở file khác:** `report_visual_src.html:255` chỉ dẫn sang `one_pager.html`. Nếu gửi riêng `report_visual.html`, phần bắt buộc “one page for Business Lead” không nằm trong file. Nộp hai file như một package hoặc nhúng/đính kèm một-page appendix rõ ràng.
4. **“Two review agents re-checked…”** (`report_visual_src.html:262`) là mô tả quy trình tạo bài, không phải insight cho stakeholder. Bỏ. Đề còn ghi Bonus “keep it brief”, nhưng phần Bonus là cả Chapter 8 với hai figure và nhiều bullet. Chỉ giữ 1–2 ý data-quality ảnh hưởng quyết định.

## Điều tôi sẽ giữ

- Định nghĩa cohort theo first observed purchase và right-censor các M chưa thấy (`analysis.py:293–330`).
- So sánh **raw vs 104 dòng nghi vấn** làm rõ cú nhảy N=4; đây là insight mạnh nhất của bài, miễn không khẳng định provenance chưa kiểm chứng.
- Tách association khỏi treatment effect và đề xuất holdout; chủ trương không dùng số dư mô phỏng để ra quyết định hạn mức là đúng.
- Dùng `MAU[t+1] = MAU[t] × (1 − churn) + first purchasers` làm **accounting scenario trong extract không có reactivation**, không gọi là forecast hay causal attribution.

## Bản thông điệp thay thế có thể dùng ngay

> **As of Jun 2025, fewer people made their first observed BNPL purchase, while monthly purchase lapse changed little. This explains most of the MAU decline in the provided extract; the failing funnel step and production trend need validation.** Prioritise that reconciliation. In parallel, run a holdout test of a mid-month reminder and track incremental net contribution, not just month-end purchases. A stronger retention intervention could also reverse the decline; its effect is unproven here.

**Decision request phù hợp hơn:** “Approve a two-week validation of the activation funnel against official data and the design of Test B. Launch Test B only after eligibility, consent, repayment and measurement windows are confirmed.”

**Thứ tự sửa:** (1) thời điểm và headline; (2) bỏ CAC ceiling và “best-case/only”; (3) sửa caveat dữ liệu, join-day, silent trigger; (4) sửa đơn vị GMV at risk và sizing; (5) cắt one-pager/visual. Sau đó mới polish biểu đồ.
