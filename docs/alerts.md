# Alert và Runbook

Mỗi alert dưới đây bám vào triệu chứng người dùng hoặc SLO. Quy trình điều tra chung là Metrics → Logs → Traces.

## HighRequestLatency

- Severity: `critical`; duration: `10m`; kênh: `#llmops-alerts`; owner: `llm-platform`.
- SLI/SLO: P95 latency của request thành công; cảnh báo khi `latency_p95 > 3000` liên tục 10 phút.
- Ảnh hưởng: người dùng chờ phản hồi lâu và error budget bị tiêu hao.
- Kiểm tra: xác định cửa sổ P95/TTFT; lọc log `response_sent` chậm và lấy `correlation_id`; mở trace cùng ID để so sánh retrieval và generation.
- Mitigation: giảm concurrency hoặc tạm chuyển sang dependency/model ổn định, sau đó xác nhận P95 trở lại dưới ngưỡng.

## HighRequestErrorRate

- Severity: `critical`; duration: `5m`; kênh: `#llmops-alerts`; owner: `llm-platform`.
- SLI/SLO: tỷ lệ request thành công; cảnh báo khi `error_rate_pct > 2` liên tục 5 phút.
- Ảnh hưởng: hơn 2% request không trả được câu trả lời.
- Kiểm tra: xem error breakdown và retrieval success; lọc `request_failed` theo `error_type`; dùng `correlation_id` mở trace và xác định observation lỗi.
- Mitigation: tạm tắt tính năng hoặc dependency gây lỗi, bật fallback đã kiểm thử và theo dõi error rate sau thay đổi.

## LowAnswerQuality

- Severity: `warning`; duration: `15m`; kênh: `#llmops-alerts`; owner: `ai-quality`.
- SLI/SLO: quality proxy trung bình; cảnh báo khi `quality_avg < 0.75` liên tục 15 phút.
- Ảnh hưởng: câu trả lời có thể thiếu ngữ cảnh hoặc không đáp ứng truy vấn.
- Kiểm tra: so sánh quality theo feature/prompt version; lọc request điểm thấp và lấy `correlation_id`; kiểm tra retrieval count, prompt version và generation trong trace.
- Mitigation: rollback label `production` về prompt version ổn định gần nhất và chạy lại cùng workload để xác nhận quality phục hồi.
